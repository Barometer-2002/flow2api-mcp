"""Flow2API MCP Server - single file MCP server.

This module is intentionally self-contained to keep the MCP integration simple.
"""

from __future__ import annotations

import asyncio
import base64
import difflib
import hashlib
import http.server
import json
import mimetypes
import os
import re
import sys
import threading
import time
import urllib.parse
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# 创建MCP服务器实例
server = Server("flow2api-mcp")


# -----------------------------
# Config
# -----------------------------

PROJECT_ROOT = Path(__file__).parent
HISTORY_FILE = PROJECT_ROOT / "history.json"
HISTORY_ARCHIVE_FILE = PROJECT_ROOT / "history_archive.json"
MODELS_CONFIG_FILE = PROJECT_ROOT / "models.json"

URL_CACHE_DIR = PROJECT_ROOT / "url_cache"
URL_CACHE_INDEX_FILE = PROJECT_ROOT / "url_cache.json"
URL_CACHE_ENABLED = os.environ.get("FLOW2API_MCP_URL_CACHE", "0") != "0"
URL_CACHE_MAX_ENTRIES = int(os.environ.get("FLOW2API_MCP_URL_CACHE_MAX_ENTRIES", "200"))
URL_CACHE_MAX_FILE_BYTES = int(os.environ.get("FLOW2API_MCP_URL_CACHE_MAX_FILE_BYTES", "100")) * 1024 * 1024

# User image import (Cherry Studio uploads)
# Disabled by default. Enable by setting FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR.
_default_cherrystudio_files_dir = Path(os.environ.get("APPDATA", "")).joinpath("CherryStudio", "Data", "Files")
_user_image_dir_env = (os.environ.get("FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR") or "").strip()
_legacy_local_files_root_env = (os.environ.get("FLOW2API_MCP_LOCAL_FILES_ROOT") or "").strip()
USER_IMAGE_DIR = (
    Path(_user_image_dir_env or _legacy_local_files_root_env).expanduser()
    if (_user_image_dir_env or _legacy_local_files_root_env)
    else None
)

MAX_HISTORY_RECENT_SIZE = int(os.environ.get("FLOW2API_MCP_HISTORY_RECENT_SIZE", "50"))
MAX_HISTORY_ARCHIVE_SIZE = int(os.environ.get("FLOW2API_MCP_HISTORY_ARCHIVE_SIZE", "2000"))

CACHE_HTTP_PORT = int(os.environ.get("FLOW2API_MCP_CACHE_HTTP_PORT", "46262"))
GENERATE_RETRY_COUNT = int(os.environ.get("FLOW2API_MCP_GENERATE_RETRY_COUNT", "3"))

HTTP_TIMEOUT = 600.0
HTTP_CONNECT_TIMEOUT = 30.0
MAX_CONNECTIONS = 10
MAX_KEEPALIVE_CONNECTIONS = 5

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_MODEL = "gemini-3.0-pro-image-landscape"

SUPPORTED_MODELS_FALLBACK: list[str] = [
    # Images
    "gemini-3.0-pro-image-landscape",
    "gemini-3.0-pro-image-portrait",
    "gemini-2.5-flash-image-landscape",
    "gemini-2.5-flash-image-portrait",
    "imagen-4.0-generate-preview-landscape",
    "imagen-4.0-generate-preview-portrait",
    # Text-to-video (T2V)
    "veo_3_1_t2v_fast_landscape",
    "veo_3_1_t2v_fast_portrait",
    "veo_2_1_fast_d_15_t2v_landscape",
    "veo_2_1_fast_d_15_t2v_portrait",
    "veo_2_0_t2v_landscape",
    "veo_2_0_t2v_portrait",
    # Image-to-video (I2V)
    "veo_3_1_i2v_s_fast_fl_landscape",
    "veo_3_1_i2v_s_fast_fl_portrait",
    "veo_2_1_fast_d_15_i2v_landscape",
    "veo_2_1_fast_d_15_i2v_portrait",
    "veo_2_0_i2v_landscape",
    "veo_2_0_i2v_portrait",
    # Reference-to-video (R2V)
    "veo_3_0_r2v_fast_landscape",
    "veo_3_0_r2v_fast_portrait",
]

MODEL_SELECTION_GUIDE_FALLBACK = (
    "## 选型指南（简版）\n"
    "- 图片：`gemini-3.0-pro-image-*`（质量） / `gemini-2.5-flash-image-*`（速度） / `imagen-4.0-generate-preview-*`（风格）\n"
    "- 文生视频：`veo_3_1_t2v_fast_*`（新）> `veo_2_1_fast_d_15_t2v_*` > `veo_2_0_t2v_*`\n"
    "- 图生视频：`*_i2v_*`（首尾帧 1-2 张图） / `*_r2v_*`（多图）\n"
    "- 横竖屏：`-landscape`=横屏，`-portrait`=竖屏\n"
)


def _load_models_config(path: Path) -> tuple[list[str], str, str]:
    if not path.exists():
        return list(SUPPORTED_MODELS_FALLBACK), DEFAULT_MODEL, MODEL_SELECTION_GUIDE_FALLBACK
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[MCP] 加载 models.json 失败: {exc}", file=sys.stderr)
        return list(SUPPORTED_MODELS_FALLBACK), DEFAULT_MODEL, MODEL_SELECTION_GUIDE_FALLBACK

    models_raw = data.get("models")
    models: list[str] = [str(x).strip() for x in (models_raw or []) if str(x).strip()]
    if not models:
        models = list(SUPPORTED_MODELS_FALLBACK)

    default_model = str(data.get("default_model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    if default_model not in models:
        default_model = models[0]

    selection_guide = str(data.get("selection_guide") or "").strip()
    if not selection_guide:
        lines = data.get("selection_guide_lines")
        if isinstance(lines, list) and lines:
            selection_guide = "\n".join(str(x) for x in lines if str(x).strip()).strip()
    if not selection_guide:
        selection_guide = MODEL_SELECTION_GUIDE_FALLBACK

    return models, default_model, selection_guide


SUPPORTED_MODELS, DEFAULT_MODEL, MODEL_SELECTION_GUIDE = _load_models_config(MODELS_CONFIG_FILE)


def _model_selection_guide() -> str:
    return MODEL_SELECTION_GUIDE


def get_base_url() -> str:
    return os.environ.get("FLOW2API_BASE_URL", DEFAULT_BASE_URL)


def get_api_key() -> str:
    return os.environ.get("FLOW2API_API_KEY", "")


# -----------------------------
# History
# -----------------------------


class HistoryManager:
    def __init__(self):
        self._recent: deque[dict[str, Any]] = deque(maxlen=MAX_HISTORY_RECENT_SIZE)
        self._archive: deque[dict[str, Any]] = deque(maxlen=MAX_HISTORY_ARCHIVE_SIZE)
        self._next_id: int = 1
        self._load_history()

    def _ensure_ids(self) -> None:
        # Ensure every history item has a stable incremental id.
        max_id = 0
        for item in list(self._archive) + list(self._recent):
            try:
                v = int(item.get("id") or 0)
            except Exception:
                v = 0
            if v > max_id:
                max_id = v

        archive_list = list(self._archive)
        has_any_id = any(isinstance(x.get("id"), int) and x.get("id") for x in archive_list)
        if archive_list:
            if not has_any_id:
                # First migration: assign ids in chronological order as stored in file.
                next_id = 1
                for item in archive_list:
                    item["id"] = next_id
                    next_id += 1
                max_id = next_id - 1
            else:
                # Partial migration: fill missing ids after the current max.
                next_id = max_id + 1
                for item in archive_list:
                    if not isinstance(item.get("id"), int) or int(item.get("id") or 0) <= 0:
                        item["id"] = next_id
                        next_id += 1
                max_id = next_id - 1

            self._archive = deque(archive_list, maxlen=MAX_HISTORY_ARCHIVE_SIZE)
            # Keep recent as a suffix of archive so ids match.
            self._recent = deque(archive_list[-MAX_HISTORY_RECENT_SIZE:], maxlen=MAX_HISTORY_RECENT_SIZE)

        self._next_id = max_id + 1 if max_id > 0 else 1

    def _load_history(self) -> None:
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._recent = deque(data, maxlen=MAX_HISTORY_RECENT_SIZE)
                print(f"[MCP] 已加载 recent={len(self._recent)} 条历史记录", file=sys.stderr)
            except Exception as exc:
                print(f"[MCP] 加载历史记录失败: {exc}", file=sys.stderr)
                self._recent = deque(maxlen=MAX_HISTORY_RECENT_SIZE)

        if HISTORY_ARCHIVE_FILE.exists():
            try:
                with open(HISTORY_ARCHIVE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._archive = deque(data, maxlen=MAX_HISTORY_ARCHIVE_SIZE)
                print(f"[MCP] 已加载 archive={len(self._archive)} 条历史记录", file=sys.stderr)
            except Exception as exc:
                print(f"[MCP] 加载历史归档失败: {exc}", file=sys.stderr)
                self._archive = deque(maxlen=MAX_HISTORY_ARCHIVE_SIZE)
        else:
            # Migration: if archive doesn't exist, seed it from recent to avoid "empty archive".
            if self._recent:
                self._archive = deque(list(self._recent), maxlen=MAX_HISTORY_ARCHIVE_SIZE)
                self._save_history()

        self._ensure_ids()

    def _save_history(self) -> None:
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(list(self._recent), f, ensure_ascii=False, indent=2)
            with open(HISTORY_ARCHIVE_FILE, "w", encoding="utf-8") as f:
                json.dump(list(self._archive), f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[MCP] 保存历史记录失败: {exc}", file=sys.stderr)

    def add_success(self, model: str, prompt: str, urls: list[str]) -> None:
        item = {
            "id": self._next_id,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": model,
            "prompt": prompt,
            "urls": urls,
            "error": None,
        }
        self._next_id += 1
        self._recent.append(item)
        self._archive.append(item)
        self._save_history()

    def add_failure(self, model: str, prompt: str, error: str) -> None:
        item = {
            "id": self._next_id,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": model,
            "prompt": prompt,
            "urls": [],
            "error": error,
        }
        self._next_id += 1
        self._recent.append(item)
        self._archive.append(item)
        self._save_history()

    def get_recent(self, limit: int = 5) -> list[dict[str, Any]]:
        limit = min(int(limit), MAX_HISTORY_RECENT_SIZE)
        return list(self._recent)[-limit:][::-1]

    def get_archive(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = min(int(limit), MAX_HISTORY_ARCHIVE_SIZE)
        return list(self._archive)[-limit:][::-1]

    def get_by_id(self, item_id: int, scope: str = "archive") -> Optional[dict[str, Any]]:
        try:
            target = int(item_id)
        except Exception:
            return None
        if target <= 0:
            return None

        history_list = list(self._archive) if scope == "archive" else list(self._recent)
        for item in reversed(history_list):
            if int(item.get("id") or 0) == target:
                return item
        return None

    def is_empty(self, scope: str = "recent") -> bool:
        if scope == "archive":
            return len(self._archive) == 0
        return len(self._recent) == 0

    def sizes(self) -> dict[str, int]:
        return {"recent": len(self._recent), "archive": len(self._archive)}

    def prune_to(self, keep: int) -> dict[str, int]:
        keep = max(0, int(keep))
        before = self.sizes()

        if keep == 0:
            self._recent.clear()
            self._archive.clear()
        else:
            if len(self._recent) > keep:
                self._recent = deque(
                    list(self._recent)[-keep:], maxlen=MAX_HISTORY_RECENT_SIZE
                )
            if len(self._archive) > keep:
                self._archive = deque(
                    list(self._archive)[-keep:], maxlen=MAX_HISTORY_ARCHIVE_SIZE
                )

        self._save_history()
        after = self.sizes()
        return {
            "recent_removed": before["recent"] - after["recent"],
            "archive_removed": before["archive"] - after["archive"],
        }

    def clear_all(self) -> dict[str, int]:
        before = self.sizes()
        self._recent.clear()
        self._archive.clear()
        self._save_history()
        return {"recent_removed": before["recent"], "archive_removed": before["archive"]}

    def get_latest_success_image_item(self, scope: str = "archive") -> Optional[dict[str, Any]]:
        history_list = list(self._archive) if scope == "archive" else list(self._recent)
        for item in reversed(history_list):
            if item.get("error"):
                continue
            urls = list(item.get("urls", []) or [])
            if any(_is_likely_image_url(u) for u in urls):
                return item
        return None


history_manager = HistoryManager()


# -----------------------------
# HTTP client
# -----------------------------


class HttpClient:
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(HTTP_TIMEOUT, connect=HTTP_CONNECT_TIMEOUT),
                limits=httpx.Limits(
                    max_connections=MAX_CONNECTIONS,
                    max_keepalive_connections=MAX_KEEPALIVE_CONNECTIONS,
                ),
                follow_redirects=True,
            )
        return self._client


http_client = HttpClient()


async def _flow2api_stream_chat_completions(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
) -> tuple[int, str, str, str]:
    reasoning_text = ""
    content_text = ""
    debug: dict[str, int] = {
        "events": 0,
        "json": 0,
        "choices": 0,
        "delta_content": 0,
        "message_content": 0,
        "delta_images": 0,
        "message_images": 0,
        "content_image_url_parts": 0,
    }
    debug_sample: list[str] = []
    first_json_payload: str = ""
    raw_lines: list[str] = []
    raw_chars = 0
    RAW_CAPTURE_LIMIT = 32_000

    def _append_url_line(url: str) -> None:
        nonlocal content_text
        u = str(url or "").strip()
        if not u:
            return
        if content_text and not content_text.endswith("\n"):
            content_text += "\n"
        content_text += u

    def _append_content_value(value: Any) -> None:
        nonlocal content_text
        if value is None:
            return
        if isinstance(value, str):
            if value:
                content_text += value
            return
        if isinstance(value, list):
            for part in value:
                if isinstance(part, str):
                    if part:
                        content_text += part
                    continue
                if not isinstance(part, dict):
                    continue
                # Common multimodal formats (varies by provider):
                # - {"type":"text","text":"..."}
                # - {"type":"output_text","text":"..."}
                # - {"type":"image_url","image_url":{"url":"..."}}
                part_type = str(part.get("type") or "").lower()
                if part_type in ("text", "output_text"):
                    text_val = part.get("text")
                    if isinstance(text_val, str) and text_val:
                        content_text += text_val
                    continue
                if part_type == "image_url":
                    image_url = part.get("image_url") or {}
                    if isinstance(image_url, dict):
                        url_val = image_url.get("url")
                        if isinstance(url_val, str) and url_val.strip():
                            debug["content_image_url_parts"] += 1
                            _append_url_line(url_val)
            return

    def _add_debug_sample(choice0: dict[str, Any], delta: dict[str, Any], message: dict[str, Any]) -> None:
        nonlocal debug_sample
        if debug_sample:
            return
        try:
            def _t(v: Any) -> str:
                if v is None:
                    return "null"
                if isinstance(v, list):
                    return "list"
                if isinstance(v, dict):
                    return "dict"
                return type(v).__name__

            debug_sample = [
                "choice0_keys=" + ",".join(sorted(choice0.keys()))[:200],
                "delta_keys=" + ",".join(sorted(delta.keys()))[:200],
                "message_keys=" + ",".join(sorted(message.keys()))[:200],
                "delta.content=" + _t(delta.get("content")),
                "message.content=" + _t(message.get("content")),
                "delta.images=" + _t(delta.get("images")),
                "message.images=" + _t(message.get("images")),
                "delta.image=" + _t(delta.get("image")),
                "message.image=" + _t(message.get("image")),
            ]
        except Exception:
            debug_sample = ["sample_failed"]

    def _append_images_field(value: Any, *, debug_key: str) -> None:
        """
        Accept a few shapes:
        - list[{"url": "..."}]
        - list[{"type":"image_url","image_url":{"url":"..."}}]  (proxy-specific)
        - {"url": "..."}
        - {"type":"image_url","image_url":{"url":"..."}}
        - "data:image/...;base64,..."
        """
        if value is None:
            return
        if isinstance(value, str) and value.strip():
            debug[debug_key] += 1
            _append_url_line(value)
            return
        if isinstance(value, dict):
            url_val = value.get("url")
            if isinstance(url_val, str) and url_val.strip():
                debug[debug_key] += 1
                _append_url_line(url_val)
                return

            image_url = value.get("image_url")
            if isinstance(image_url, dict):
                url_val2 = image_url.get("url")
                if isinstance(url_val2, str) and url_val2.strip():
                    debug[debug_key] += 1
                    _append_url_line(url_val2)
                    return
            if isinstance(image_url, str) and image_url.strip():
                debug[debug_key] += 1
                _append_url_line(image_url)
            return
        if isinstance(value, list):
            for img in value:
                if isinstance(img, dict):
                    url_val = img.get("url")
                    if isinstance(url_val, str) and url_val.strip():
                        debug[debug_key] += 1
                        _append_url_line(url_val)
                        continue
                    image_url = img.get("image_url")
                    if isinstance(image_url, dict):
                        url_val2 = image_url.get("url")
                        if isinstance(url_val2, str) and url_val2.strip():
                            debug[debug_key] += 1
                            _append_url_line(url_val2)
                            continue
                    if isinstance(image_url, str) and image_url.strip():
                        debug[debug_key] += 1
                        _append_url_line(image_url)
                elif isinstance(img, str) and img.strip():
                    debug[debug_key] += 1
                    _append_url_line(img)

    try:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }

        async with client.stream(
            "POST",
            f"{base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        ) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                return (
                    response.status_code,
                    "",
                    "",
                    error_text.decode(errors="ignore")[:2000],
                )

            async for line in response.aiter_lines():
                if not line:
                    continue
                debug["events"] += 1
                if raw_chars < RAW_CAPTURE_LIMIT:
                    raw_lines.append(line)
                    raw_chars += len(line) + 1

                payload: Optional[str] = None
                if line.startswith("data:"):
                    payload = line[5:].lstrip()
                    if payload == "[DONE]":
                        continue
                elif line.startswith("{"):
                    payload = line

                if payload is None:
                    continue

                try:
                    data = json.loads(payload)
                except Exception:
                    continue
                debug["json"] += 1
                if not first_json_payload:
                    first_json_payload = payload

                if isinstance(data, dict) and data.get("error"):
                    err = data.get("error") or {}
                    err_msg = str(err.get("message") or err)[:2000]
                    return 500, "", "", err_msg

                if not isinstance(data, dict):
                    continue

                choices = data.get("choices")
                if not isinstance(choices, list) or not choices:
                    # Some implementations may emit empty choices as keepalive.
                    continue
                debug["choices"] += 1
                choice0 = choices[0] if isinstance(choices[0], dict) else {}

                delta = choice0.get("delta") if isinstance(choice0.get("delta"), dict) else {}
                message = choice0.get("message") if isinstance(choice0.get("message"), dict) else {}
                _add_debug_sample(choice0, delta, message)

                # reasoning (streaming / non-streaming variants)
                reasoning_delta = delta.get("reasoning_content") or delta.get("reasoning") or ""
                if isinstance(reasoning_delta, str) and reasoning_delta:
                    reasoning_text += reasoning_delta
                reasoning_msg = message.get("reasoning_content") or message.get("reasoning") or ""
                if isinstance(reasoning_msg, str) and reasoning_msg:
                    reasoning_text += reasoning_msg

                # content (streaming / non-streaming variants)
                if delta.get("content") is not None:
                    debug["delta_content"] += 1
                _append_content_value(delta.get("content"))
                if message.get("content") is not None:
                    debug["message_content"] += 1
                _append_content_value(message.get("content"))

                # Some proxies emit images outside `content`:
                # - streaming: choices[0].delta.images = [{"url":"data:image/png;base64,..."}]
                # - non-stream: choices[0].message.images = [{"url":"data:image/png;base64,..."}]
                _append_images_field(delta.get("images"), debug_key="delta_images")
                _append_images_field(message.get("images"), debug_key="message_images")
                # Some proxies use singular `image` field.
                _append_images_field(delta.get("image"), debug_key="delta_images")
                _append_images_field(message.get("image"), debug_key="message_images")
    except Exception as exc:
        return 0, "", "", str(exc)[:2000]

    err_text = ""
    if not content_text.strip():
        # Make empty 200s actionable: provide parsing diagnostics (without leaking full payloads).
        counts = ", ".join(f"{k}={v}" for k, v in debug.items() if v)
        sample = "; ".join(debug_sample) if debug_sample else ""
        payload_prefix = ""
        if first_json_payload:
            s = first_json_payload
            # Avoid leaking large base64 blobs in error text.
            s = re.sub(r"(data:image/[a-zA-Z0-9.+-]+;base64,)[A-Za-z0-9+/=]+", r"\\1<base64>", s)
            s = re.sub(r"(\"b64_json\"\\s*:\\s*\")([^\"]+)(\")", r"\\1<base64>\\3", s)
            s = re.sub(r"(\"url\"\\s*:\\s*\")([^\"]{120,})(\")", r"\\1<omitted>\\3", s)
            payload_prefix = s[:400].replace("\n", " ")
        parts = ["empty content extracted"]
        if counts:
            parts.append(counts)
        if sample:
            parts.append(sample)
        if payload_prefix:
            parts.append(f"payload_prefix={payload_prefix}")
        if raw_lines:
            try:
                debug_path = Path(__file__).resolve().parent / "upstream_debug_last.txt"
                debug_path.write_text("\n".join(raw_lines), encoding="utf-8", errors="ignore")
                parts.append(f"debug_dump={debug_path}")
            except Exception:
                pass
        err_text = ("; ".join(parts))[:2000]

    return 200, reasoning_text, content_text, err_text


# -----------------------------
# URL utils
# -----------------------------


def _normalize_cache_key(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return url

    if not (parsed.query or parsed.fragment):
        return url

    normalized = parsed._replace(query="", fragment="")
    return urllib.parse.urlunparse(normalized)


def _auth_headers_for_url(url: str) -> dict[str, str]:
    """Return auth headers for Flow2API `/tmp/...` URLs on the same host as FLOW2API_BASE_URL."""
    api_key = get_api_key()
    if not api_key:
        return {}

    try:
        parsed = urllib.parse.urlparse(url)
        base = urllib.parse.urlparse(get_base_url())
    except Exception:
        return {}

    if "/tmp/" not in (parsed.path or ""):
        return {}

    url_host = (parsed.hostname or "").lower()
    base_host = (base.hostname or "").lower()
    url_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    base_port = base.port or (443 if base.scheme == "https" else 80)
    if not url_host or not base_host:
        return {}
    if url_host == base_host and url_port == base_port:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path = path.resolve()
        root = root.resolve()
    except Exception:
        return False
    try:
        path.relative_to(root)
        return True
    except Exception:
        return False


def _local_file_uri_to_path(value: str) -> Optional[Path]:
    s = str(value or "").strip()
    if not s:
        return None

    if s.lower().startswith("file:"):
        try:
            parsed = urllib.parse.urlparse(s)
            if parsed.scheme.lower() != "file":
                return None
            raw_path = urllib.parse.unquote(parsed.path or "")
            if re.match(r"^/[A-Za-z]:/", raw_path):
                raw_path = raw_path[1:]
            raw_path = raw_path.replace("/", "\\")
            return Path(raw_path)
        except Exception:
            return None

    return Path(s)


def _guess_mime_from_ext(ext: str) -> Optional[str]:
    ext = (ext or "").lower().lstrip(".")
    if ext == "png":
        return "image/png"
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    if ext == "webp":
        return "image/webp"
    if ext == "gif":
        return "image/gif"
    if ext == "bmp":
        return "image/bmp"
    if ext in ("tif", "tiff"):
        return "image/tiff"
    return None


def _store_local_media(raw: bytes, *, mime: str, ext: str) -> Optional[str]:
    if not raw:
        return None

    URL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(raw).hexdigest()
    ext = (ext or "jpg").lower().lstrip(".")
    filename = f"{key}.{ext}"
    path = URL_CACHE_DIR / filename
    try:
        if not path.exists():
            path.write_bytes(raw)
    except Exception as exc:
        print(f"[MCP] 保存本地文件失败: {exc}", file=sys.stderr)
        return None

    try:
        url_cache._load()
        url_cache._index[f"local:{filename}"] = {
            "path": str(path),
            "mime": mime,
            "size": len(raw),
            "filename": filename,
            "time": time.time(),
        }
        url_cache._prune()
        url_cache._save()
    except Exception:
        pass

    return filename


async def _import_local_file(value: str) -> tuple[Optional[str], Optional[str]]:
    """Import a local image file and return (data_uri, local_url)."""
    s = str(value or "").strip()
    if s.lower().startswith(("http://", "https://")):
        raise ValueError(
            "local_file 仅支持本地文件路径或 file:/// URI；不要传 http(s) 链接。"
            "如需使用 Cherry Studio 上传的图片，请改用 use_latest_user_image=true，"
            "或提供 file:///C:/... 的本地路径。"
        )

    p = _local_file_uri_to_path(value)
    if not p:
        return None, None

    if USER_IMAGE_DIR is None:
        raise ValueError("未启用用户图生图：请设置环境变量 FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR")
    if not _is_under_root(p, USER_IMAGE_DIR):
        raise ValueError(f"本地文件不在允许目录下: {p}（允许目录: {USER_IMAGE_DIR}）")

    if not p.exists() or not p.is_file():
        raise ValueError("本地文件不存在或不可读")

    ext = p.suffix.lower().lstrip(".")
    mime = _guess_mime_from_ext(ext)
    if not mime:
        raise ValueError("仅支持图片文件: png/jpg/jpeg/webp/gif/bmp/tif/tiff")

    raw = p.read_bytes()
    filename = _store_local_media(raw, mime=mime, ext=ext)
    if not filename:
        raise ValueError("保存本地文件失败")

    base = _ensure_cache_http_server()
    if base:
        local_url = f"{base}/mcp-cache/{filename}"
    else:
        local_url = f"http://127.0.0.1:{CACHE_HTTP_PORT}/mcp-cache/{filename}"

    data = base64.b64encode(raw).decode()
    data_uri = f"data:{mime};base64,{data}"
    return data_uri, local_url


def _pick_latest_user_image_path() -> Path:
    if USER_IMAGE_DIR is None:
        raise ValueError("未启用用户图生图：请设置环境变量 FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR")

    root = USER_IMAGE_DIR
    if not root.exists() or not root.is_dir():
        raise ValueError(f"用户图片目录不存在或不可读: {root}")

    allowed_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
    candidates: list[tuple[float, Path]] = []
    for p in root.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in allowed_exts:
            continue
        try:
            st = p.stat()
        except Exception:
            continue
        if st.st_size <= 0:
            continue
        candidates.append((float(st.st_mtime), p))

    if not candidates:
        raise ValueError(f"用户图片目录下未找到可用图片: {root}")

    candidates.sort(key=lambda x: x[0], reverse=True)
    _latest_mtime, latest_path = candidates[0]
    return latest_path


def extract_urls(text: str) -> list[str]:
    urls: list[str] = []

    pattern1 = (
        r"https?://[^\s\)\"'\]\[<>]+\.(?:png|jpg|jpeg|gif|mp4|webm|webp)"
        r"(?:\?[^\s\)\"'\]\[<>]*)?"
    )
    urls.extend(re.findall(pattern1, text, re.I))

    pattern2 = r"https?://[^\s\)\"'\]\[<>]+/tmp/[a-f0-9]{32}\.(?:jpg|png|mp4|webm)"
    urls.extend(re.findall(pattern2, text, re.I))

    pattern3 = r"!\[[^\]]*\]\((https?://[^\)]+)\)"
    for match in re.findall(pattern3, text, re.I):
        urls.append(match)

    # Pattern 4: HTML video tag (Flow2API may return ```html <video src='...'>```)
    pattern4 = r"<video[^>]*\s+src=['\"](https?://[^'\"]+)['\"][^>]*>"
    for match in re.findall(pattern4, text, re.I):
        urls.append(match)

    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u))]


def _convert_html_video_tags_to_markdown(text: str) -> str:
    if not text:
        return text
    pattern = re.compile(
        r"<video[^>]*\s+src=['\"](https?://[^'\"]+)['\"][^>]*>(?:\s*</video>)?",
        re.I,
    )

    def _one(match: re.Match[str]) -> str:
        url = match.group(1)
        return f"[video]({url})"

    return pattern.sub(_one, text)


def _wrap_video_urls_in_markdown(text: str) -> str:
    """Wrap bare video URLs as Markdown links: [video](url).

    Keep existing Markdown links intact.
    """
    if not text:
        return text

    # Avoid re-wrapping URLs already in Markdown link: ](https://...)
    pattern = re.compile(
        r"(?<!\]\()(?P<url>https?://[^\s\)\"'\]\[<>]+\.(?:mp4|webm)(?:\?[^\s\)\"'\]\[<>]*)?)",
        re.I,
    )

    def _one(match: re.Match[str]) -> str:
        url = match.group("url")
        return f"[video]({url})"

    return pattern.sub(_one, text)


async def download_url_as_base64(url: str) -> Optional[str]:
    try:
        # If the URL points to our own local cache HTTP server, read the cached file directly.
        try:
            parsed = urllib.parse.urlparse(url)
            path = parsed.path or ""
            if "/mcp-cache/" in path:
                filename = path.split("/mcp-cache/", 1)[1].split("?", 1)[0]
                filename = os.path.basename(filename)
                if filename:
                    file_path = URL_CACHE_DIR / filename
                    if file_path.exists():
                        content = file_path.read_bytes()
                        mime, _ext = _guess_mime_and_ext(filename, "")
                        data = base64.b64encode(content).decode()
                        return f"data:{mime};base64,{data}"
        except Exception:
            pass

        if URL_CACHE_ENABLED:
            cached = url_cache.get_data_uri(url)
            if cached:
                print(f"[MCP] URL缓存命中: {url}", file=sys.stderr)
                return cached

        client = await http_client.get_client()
        print(f"[MCP] 下载图片: {url}", file=sys.stderr)
        resp = await client.get(url, timeout=30, headers=_auth_headers_for_url(url))
        print(f"[MCP] 响应状态: {resp.status_code}", file=sys.stderr)

        if resp.status_code != 200:
            print(f"[MCP] 下载失败: {resp.status_code} - {resp.text[:200]}", file=sys.stderr)
            return None

        ct = resp.headers.get("content-type", "")
        mime, ext = _guess_mime_and_ext(url, ct)
        if URL_CACHE_ENABLED:
            url_cache.put(url, resp.content, mime=mime, ext=ext)

        print(f"[MCP] 下载成功, 大小: {len(resp.content)} bytes", file=sys.stderr)
        data = base64.b64encode(resp.content).decode()
        return f"data:{mime};base64,{data}"
    except Exception as exc:
        print(f"[MCP] 下载异常: {exc}", file=sys.stderr)
        return None


def _is_likely_image_url(url: str) -> bool:
    lower = url.lower().split("?", 1)[0]
    return lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))


"""
Reference image selection policy is intentionally *not* implemented via keyword heuristics.

This MCP server only uses explicit tool parameters:
- history_id: reference from history
- use_latest_user_image/local_file: reference from Cherry Studio upload directory (when enabled)

All "what does the user mean by this image?" decisions should be made by the model
according to the tool descriptions.
"""


def _is_likely_video_url(url: str) -> bool:
    base = url.lower().split("?", 1)[0]
    return base.endswith((".mp4", ".webm"))


def _model_requires_reference_images(model: str) -> bool:
    s = str(model or "")
    return s.startswith("veo_") and ("_i2v_" in s or "_r2v_" in s)


def _guess_mime_and_ext(url: str, content_type: str) -> tuple[str, str]:
    content_type = (content_type or "").lower()
    url_lower = url.lower()

    if "png" in content_type or url_lower.endswith(".png"):
        return "image/png", "png"
    if "mp4" in content_type or url_lower.endswith(".mp4"):
        return "video/mp4", "mp4"
    if "webm" in content_type or url_lower.endswith(".webm"):
        return "video/webm", "webm"
    return "image/jpeg", "jpg"


def _ext_from_mime(mime: str) -> str:
    mime = (mime or "").lower().strip()
    if mime == "image/png":
        return "png"
    if mime in ("image/jpg", "image/jpeg"):
        return "jpg"
    if mime == "image/webp":
        return "webp"
    if mime == "image/gif":
        return "gif"
    if mime in ("image/tif", "image/tiff"):
        return "tiff"
    return "jpg"


def _extract_data_image_urls(text: str) -> list[str]:
    if not text:
        return []
    # Keep it simple: stop at whitespace or ')' to cover common Markdown usage.
    pattern = re.compile(r"(data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+)")
    seen: set[str] = set()
    out: list[str] = []
    for m in pattern.findall(text):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _parse_data_image_url(data_url: str) -> Optional[tuple[str, bytes]]:
    s = str(data_url or "").strip()
    if not s.startswith("data:image/"):
        return None
    try:
        header, b64 = s.split(",", 1)
    except ValueError:
        return None
    header = header.lower()
    if ";base64" not in header:
        return None
    # data:image/png;base64
    try:
        mime = header.split(":", 1)[1].split(";", 1)[0].strip()
    except Exception:
        return None
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        try:
            raw = base64.b64decode(b64)
        except Exception:
            return None
    if not raw:
        return None
    return mime, raw


def _replace_data_urls_with_local_urls(text: str, mapping: dict[str, str]) -> str:
    if not text or not mapping:
        return text
    out = text
    for k, v in mapping.items():
        if k in out:
            out = out.replace(k, v)
    return out


def _wrap_bare_mcp_cache_images(text: str) -> str:
    """Wrap bare /mcp-cache image URLs as Markdown images for better rendering."""
    if not text:
        return text
    pattern = re.compile(
        r"(?<!\]\()(?P<url>https?://(?:127\.0\.0\.1|localhost):\d+/mcp-cache/[^\s\)\"'\]\[<>]+\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s\)\"'\]\[<>]*)?)",
        re.I,
    )

    def _one(match: re.Match[str]) -> str:
        url = match.group("url")
        return f"![Generated Image]({url})"

    return pattern.sub(_one, text)


class UrlCache:
    def __init__(self) -> None:
        self._index: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not URL_CACHE_INDEX_FILE.exists():
            return
        try:
            with open(URL_CACHE_INDEX_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # Drop invalid/stale entries to keep index consistent with disk.
                cleaned: dict[str, dict[str, Any]] = {}
                dirty = False
                for k, meta in data.items():
                    if not isinstance(meta, dict):
                        dirty = True
                        continue
                    path = meta.get("path")
                    mime = meta.get("mime")
                    if not path or not mime:
                        dirty = True
                        continue
                    try:
                        p = Path(str(path))
                    except Exception:
                        dirty = True
                        continue
                    if not p.exists() or not p.is_file():
                        dirty = True
                        continue
                    cleaned[str(k)] = meta
                self._index = cleaned
                if dirty:
                    self._save()
        except Exception as exc:
            print(f"[MCP] 加载URL缓存索引失败: {exc}", file=sys.stderr)
            self._index = {}

    def _save(self) -> None:
        try:
            URL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(URL_CACHE_INDEX_FILE, "w", encoding="utf-8") as f:
                json.dump(self._index, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[MCP] 保存URL缓存索引失败: {exc}", file=sys.stderr)

    def _prune(self) -> None:
        if len(self._index) <= URL_CACHE_MAX_ENTRIES:
            return

        items = sorted(
            self._index.items(),
            key=lambda kv: float(kv[1].get("time", 0.0) or 0.0),
        )
        remove_count = max(0, len(items) - URL_CACHE_MAX_ENTRIES)
        for url, meta in items[:remove_count]:
            try:
                path = meta.get("path")
                if path:
                    p = Path(path)
                    if p.exists():
                        p.unlink()
            except Exception:
                pass
            self._index.pop(url, None)

    def get_data_uri(self, url: str) -> Optional[str]:
        self._load()
        meta = self._index.get(_normalize_cache_key(url))
        if not meta:
            return None

        path = meta.get("path")
        mime = meta.get("mime")
        if not path or not mime:
            return None

        p = Path(path)
        if not p.exists() or not p.is_file():
            return None

        try:
            raw = p.read_bytes()
            data = base64.b64encode(raw).decode()
            return f"data:{mime};base64,{data}"
        except Exception as exc:
            print(f"[MCP] 读取URL缓存失败: {exc}", file=sys.stderr)
            return None

    def get_file_size(self, url: str) -> Optional[int]:
        self._load()
        meta = self._index.get(_normalize_cache_key(url)) or {}
        size = meta.get("size")
        if isinstance(size, int) and size >= 0:
            return size

        path = meta.get("path")
        if not path:
            return None
        p = Path(path)
        try:
            return p.stat().st_size
        except Exception:
            return None

    def has(self, url: str) -> bool:
        self._load()
        meta = self._index.get(_normalize_cache_key(url))
        if not meta:
            return False
        path = meta.get("path")
        mime = meta.get("mime")
        if not path or not mime:
            return False
        p = Path(path)
        return p.exists() and p.is_file()

    def put(self, url: str, raw: bytes, mime: str, ext: str) -> bool:
        self._load()
        if not raw:
            return False
        if len(raw) > URL_CACHE_MAX_FILE_BYTES:
            return False

        URL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_key = _normalize_cache_key(url)
        key = hashlib.md5(cache_key.encode("utf-8")).hexdigest()
        filename = f"{key}.{ext}"
        p = URL_CACHE_DIR / filename
        try:
            p.write_bytes(raw)
            self._index[cache_key] = {
                "path": str(p),
                "mime": mime,
                "size": len(raw),
                "filename": filename,
                "time": time.time(),
            }
            self._prune()
            self._save()
            return True
        except Exception as exc:
            print(f"[MCP] 写入URL缓存失败: {exc}", file=sys.stderr)
            return False

    def size(self) -> int:
        self._load()
        return len(self._index)

    def prune_to(self, keep: int) -> int:
        self._load()
        keep = max(0, int(keep))

        if keep == 0:
            removed = len(self._index)
            self.clear_all()
            return removed

        if len(self._index) <= keep:
            return 0

        items = sorted(
            self._index.items(),
            key=lambda kv: float(kv[1].get("time", 0.0) or 0.0),
        )
        remove_count = max(0, len(items) - keep)
        removed = 0
        for url, meta in items[:remove_count]:
            try:
                path = meta.get("path")
                if path:
                    p = Path(path)
                    if p.exists():
                        p.unlink()
            except Exception:
                pass
            self._index.pop(url, None)
            removed += 1

        self._save()
        return removed

    def clear_all(self) -> None:
        self._load()
        self._index = {}
        self._save()
        try:
            if URL_CACHE_DIR.exists():
                for p in URL_CACHE_DIR.iterdir():
                    if p.is_file():
                        p.unlink()
        except Exception:
            pass


url_cache = UrlCache()


_cache_semaphore = asyncio.Semaphore(3)


async def _cache_url_media(url: str) -> bool:
    if not URL_CACHE_ENABLED:
        return False
    if url_cache.has(url):
        return True

    try:
        client = await http_client.get_client()
        resp = await client.get(url, timeout=60, headers=_auth_headers_for_url(url))
        if resp.status_code != 200:
            return False

        ct = resp.headers.get("content-type", "")
        mime, ext = _guess_mime_and_ext(url, ct)

        if len(resp.content) > URL_CACHE_MAX_FILE_BYTES:
            print(
                f"[MCP] 跳过缓存(超过大小限制 {URL_CACHE_MAX_FILE_BYTES} bytes): {url} ({len(resp.content)} bytes)",
                file=sys.stderr,
            )
            return False

        return url_cache.put(url, resp.content, mime=mime, ext=ext)
    except Exception:
        return False


async def _cache_urls(urls: list[str]) -> int:
    if not (URL_CACHE_ENABLED and urls):
        return 0

    async def _one(url: str) -> bool:
        async with _cache_semaphore:
            try:
                return await asyncio.wait_for(_cache_url_media(url), timeout=90)
            except Exception:
                return False

    results = await asyncio.gather(*[_one(u) for u in urls], return_exceptions=True)
    count = 0
    for r in results:
        if r is True:
            count += 1
    return count


_cache_httpd: Optional[http.server.ThreadingHTTPServer] = None
_cache_httpd_thread: Optional[threading.Thread] = None
_cache_http_base_url: Optional[str] = None


def _ensure_cache_http_server() -> Optional[str]:
    global _cache_httpd, _cache_httpd_thread, _cache_http_base_url

    if _cache_http_base_url is not None:
        return _cache_http_base_url
    if not URL_CACHE_ENABLED:
        return None

    URL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    class CacheHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            try:
                if not self.path.startswith("/mcp-cache/"):
                    self.send_response(404)
                    self.end_headers()
                    return

                filename = self.path[len("/mcp-cache/") :].split("?", 1)[0]
                if not re.fullmatch(r"[a-f0-9]{32}\.[a-z0-9]+", filename):
                    self.send_response(400)
                    self.end_headers()
                    return

                file_path = URL_CACHE_DIR / filename
                if not file_path.exists() or not file_path.is_file():
                    self.send_response(404)
                    self.end_headers()
                    return

                content_type, _ = mimetypes.guess_type(str(file_path))
                self.send_response(200)
                self.send_header("Content-Type", content_type or "application/octet-stream")
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                self.end_headers()
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
            except Exception:
                try:
                    self.send_response(500)
                    self.end_headers()
                except Exception:
                    pass

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    requested_port = max(0, min(int(CACHE_HTTP_PORT), 65535))
    bind_port = requested_port
    try:
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", bind_port), CacheHandler)
    except OSError as exc:
        if requested_port > 0:
            print(
                f"[MCP] 本地缓存HTTP服务端口 {requested_port} 启动失败，将回退为随机端口: {exc}",
                file=sys.stderr,
            )
            httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), CacheHandler)
        else:
            print(f"[MCP] 本地缓存HTTP服务启动失败: {exc}", file=sys.stderr)
            return None

    port = httpd.server_address[1]
    base_url = f"http://127.0.0.1:{port}"

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    _cache_httpd = httpd
    _cache_httpd_thread = thread
    _cache_http_base_url = base_url

    print(f"[MCP] 本地缓存HTTP服务已启动: {base_url}/mcp-cache/...", file=sys.stderr)
    return base_url


def _get_cached_local_url(url: str) -> Optional[str]:
    if not URL_CACHE_ENABLED:
        return None
    if not url_cache.has(url):
        return None

    url_cache._load()  # ensure index loaded
    meta = url_cache._index.get(_normalize_cache_key(url)) or {}
    filename = meta.get("filename")
    if not filename and meta.get("path"):
        filename = Path(str(meta["path"])).name
    if not filename:
        return None

    base = _ensure_cache_http_server()
    if not base:
        return None
    return f"{base}/mcp-cache/{filename}"


def _is_local_cache_url(url: str) -> bool:
    s = str(url or "").strip()
    if not s:
        return False
    try:
        parsed = urllib.parse.urlparse(s)
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        if host in ("127.0.0.1", "localhost") and path.startswith("/mcp-cache/"):
            return True
    except Exception:
        return False
    return False


def _replace_urls_with_cached_local_urls(text: str, urls: list[str]) -> str:
    if not text:
        return text
    if not URL_CACHE_ENABLED:
        return text

    out = text
    for url in urls:
        if url not in out:
            continue
        local_url = _get_cached_local_url(url)
        if local_url:
            out = out.replace(url, local_url)
    return out


 


# -----------------------------
# Tools (schema + handlers)
# -----------------------------


DEFAULT_IMAGE_TEXT_LANGUAGE_PROMPT_SUFFIX = (
    "\n\n"
    "【默认规则】画面/字幕/标牌/海报/界面等任何可见文字默认使用简体中文；"
    "除非我在提示词里明确指定其他语言或多语言。"
)


GENERATE_DESC = (
    """生成图片或视频。

规则（必须遵守）：
1) 调用后把工具返回的图片/视频链接原样贴到最终正文里（不要只留在工具返回区）。
2) 历史确认（严格）：未开启 Cherry 上传目录时，图生图只能基于历史记录；用户说“基于这张图/继续改/上一张”这类模糊指代时，必须先调用 `history`（默认 recent）把列表贴给用户确认，再用 `history_id` 调用 generate。
3) 禁止“假调用”：未实际调用工具时不得编造“正在生成/结果链接”等内容。
4) 参考图判定与选参（不要脑补，不要死查历史）：
   - 如果用户提供了 `history_id`（数字）→ 用 `history_id`（历史参考图）
   - 如果已开启 Cherry 上传目录（设置了 `FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR`）且你在对话里确实看见用户上传的新图片 → 默认用 `use_latest_user_image=true`（更省事）
   - 如果用户提供了本地 `file:///...` 或绝对路径（且在允许目录下）→ 用 `local_file`
   - 文字里的图片 URL / 描述关键词不等于“上传图片附件”，通常属于历史/外链引用：此时不要用 `use_latest_user_image`，应走 `history_id`
5) 禁止把 http(s) 链接塞进 `local_file`（它只接受本地路径/file URI）。

prompt 写法：
- 先把用户意图改写成适合生成模型的“单段落提示词”（主体/场景/构图/光线/风格/细节/负面约束）。
- 信息不足先问 1-3 个澄清问题。
- 画面内可见文字默认简体中文，除非用户指定。

参数：
- model: 必填（从枚举选择）
- prompt: 必填
- use_latest_user_image: 可选（从 Cherry Studio 上传目录提取最新图片；需设置 `FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR`）
- local_file: 可选（本地图片路径或 file:/// URI；仅允许 Cherry Studio 上传目录；不支持 http(s) URL）
- history_id: 可选（稳定历史序号；仅复用图片作为参考图，不支持视频作参考）"""
    "\n\n"
    + _model_selection_guide()
)


HISTORY_DESC = """查看生成历史（跨会话混合累计）。

规则（必须遵守）：
1) 用户“明确要求查看历史”时，调用后把返回的历史列表粘贴到最终正文里。
2) 如果调用 history 只是为了“定位参考图”（给 generate 用的 history_id），默认不要贴全列表：只输出你最终选中的那条（history_id + 参考图/链接），然后继续调用 generate。
3) 只有在以下情况才把列表/候选贴出来让用户确认：找不到目标，或候选不唯一。
4) 禁止“假调用”：未实际调用工具时不得编造历史列表。

参数：
- history_id: 可选（指定则只返回该条记录；用于“查某一条历史信息”，避免输出全列表）
- query: 可选（关键词搜索：匹配不唯一则返回候选摘要；唯一则直接返回单条）
- keyword: 可选（同 query，兼容别名）
- limit: 返回条数（默认 5）
- scope: recent / archive（默认 recent）"""


CACHE_DESC = """缓存/历史清理工具。

规则（必须遵守）：
1) 禁止“假调用”：未实际调用工具时不得编造“已清理/已裁剪/状态”。
2) 删除历史记录需要显式确认：当 include_history=true 且 action=clear/prune 时，必须传 confirm=true。

参数：
- action: status / clear / prune（默认 status）
- keep: prune 保留条数（默认 50）
- include_history: 是否同时清理/裁剪历史（默认 false）
- confirm: 删除历史记录确认开关（默认 false；仅 include_history=true 时生效）

注意：clear/prune 会删除本地文件（`mcp_server/url_cache/` 等）。"""


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="generate",
            description=GENERATE_DESC,
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "模型名称（必须从枚举里选）",
                        "enum": SUPPORTED_MODELS,
                        "default": DEFAULT_MODEL,
                    },
                    "prompt": {
                        "type": "string",
                        "description": "生成描述。写得越详细越好，包括：主体、场景、风格、光线、颜色、构图等。",
                    },
                    "use_latest_user_image": {
                        "type": "boolean",
                        "default": False,
                        "description": "可选：从 Cherry Studio 上传目录提取“最新”图片作为参考图（需设置 FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR）",
                    },
                    "local_file": {
                        "type": "string",
                        "pattern": "^(file://|[A-Za-z]:\\\\\\\\|/).+",
                        "description": "可选：本地图片路径或 file:/// URI（仅允许 Cherry Studio 上传目录；不支持 http(s) URL）",
                    },
                    "history_id": {
                        "type": "integer",
                        "description": "可选：稳定历史序号（在 history 列表中显示）；不会随列表变化",
                    },
                },
                "required": ["model", "prompt"],
            },
        ),
        Tool(
            name="history",
            description=HISTORY_DESC,
            inputSchema={
                "type": "object",
                "properties": {
                    "history_id": {
                        "type": "integer",
                        "description": "可选：指定则只返回该条记录（稳定 history_id）",
                    },
                    "query": {
                        "type": "string",
                        "description": "可选：关键词搜索（匹配不唯一返回候选摘要；唯一返回单条）",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "可选：同 query（兼容别名）",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回条数，默认5",
                    }
                    ,
                    "scope": {
                        "type": "string",
                        "enum": ["recent", "archive"],
                        "default": "recent",
                        "description": "recent=短期历史，archive=长期归档（默认recent）",
                    },
                },
            },
        ),
        Tool(
            name="cache",
            description=CACHE_DESC,
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "clear", "prune"],
                        "default": "status",
                        "description": "status=查看；clear=清空；prune=只保留最近N条",
                    },
                    "keep": {
                        "type": "integer",
                        "default": 50,
                        "description": "prune 时保留的条目数（默认50）",
                    },
                    "include_history": {
                        "type": "boolean",
                        "default": False,
                        "description": "是否同时清理/裁剪历史记录（history.json + history_archive.json）",
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": "删除历史记录需要显式确认（include_history=true 且 action=clear/prune 时必须为 true）",
                    },
                },
            },
        ),
    ]


async def handle_generate(args: dict[str, Any]) -> list[TextContent]:
    images: list[str] = []
    mcp_logs: list[str] = []
    used_history_ref = False

    model = str(args.get("model") or "").strip() or DEFAULT_MODEL

    if args.get("use_latest_user_image") and args.get("local_file"):
        return [TextContent(type="text", text="错误: use_latest_user_image 与 local_file 只能二选一")]

    if args.get("use_latest_user_image"):
        try:
            p = _pick_latest_user_image_path()
            data_uri, local_url = await _import_local_file(str(p))
            if data_uri:
                images.append(data_uri)
                mcp_logs.append("user_image: imported latest 1 image")
            if local_url:
                history_manager.add_success("user_image", f"user_image: {p.name}", [local_url])
                mcp_logs.append("user_image: recorded to history")
        except Exception as exc:
            return [TextContent(type="text", text=f"❌ 用户图片导入失败: {exc}")]

    if args.get("local_file"):
        try:
            data_uri, local_url = await _import_local_file(str(args.get("local_file")))
            if data_uri:
                images.append(data_uri)
                mcp_logs.append("local_file: imported 1 image")
            if local_url:
                history_manager.add_success(
                    "local_file",
                    f"local_file: {os.path.basename(str(args.get('local_file')))}",
                    [local_url],
                )
                mcp_logs.append("local_file: recorded to history")
        except Exception as exc:
            return [TextContent(type="text", text=f"❌ 本地文件导入失败: {exc}")]

    if args.get("images"):
        return [
            TextContent(
                type="text",
                text="错误: 当前 MCP 不支持透传用户上传图片进行图生图；请使用纯文本生成，或使用 history_id 基于历史结果继续生成。",
            )
        ]

    if args.get("history_id") is not None:
        used_history_ref = True
        try:
            item_id = int(args.get("history_id"))
        except Exception:
            return [TextContent(type="text", text="错误: history_id 必须是整数")]

        mcp_logs.append(f"history_id: {item_id}")
        history_item = history_manager.get_by_id(item_id, scope="archive")
        if history_item:
            urls_in_history = list(history_item.get("urls", []) or [])
            mcp_logs.append(f"history urls: {len(urls_in_history)}")
            hits = 0
            misses = 0
            for url in urls_in_history:
                if not _is_likely_image_url(url):
                    continue
                if URL_CACHE_ENABLED and url_cache.has(url):
                    hits += 1
                else:
                    misses += 1
                b64 = await download_url_as_base64(url)
                if b64:
                    images.append(b64)
                    if "_i2v_" in model and len(images) >= 2:
                        break
            mcp_logs.append(f"reference images: {len(images)} (cache_hit={hits}, cache_miss={misses})")
        else:
            mcp_logs.append("history_id invalid (no such item)")

    prompt = args.get("prompt", "")
    if not prompt:
        return [TextContent(type="text", text="错误: prompt 不能为空")]

    if used_history_ref and not images:
        return [
            TextContent(
                type="text",
                text=(
                    "❌ 未能从该 history_id 获取到可用参考图。\n\n"
                    "请先调用 `history`，确认该条记录里确实有图片结果（并复制正确的 history_id），"
                    "或改用 `use_latest_user_image=true` / `local_file=file:///...` 提供参考图。"
                ),
            )
        ]

    # Note: This server does not infer reference intent from prompt text.
    # If the user wants image-to-image, the model must pass history_id / use_latest_user_image / local_file explicitly.

    prompt_to_send = f"{prompt}{DEFAULT_IMAGE_TEXT_LANGUAGE_PROMPT_SUFFIX}"

    content: Any = prompt_to_send
    if images:
        content = [{"type": "text", "text": prompt_to_send}]
        for img in images:
            content.append({"type": "image_url", "image_url": {"url": img}})
    elif used_history_ref:
        mcp_logs.append("⚠️ 未能获取到可用参考图（history_id），将按纯文本生成。")

    mcp_logs.append(f"model: {model}")

    if model not in SUPPORTED_MODELS:
        suggestions = difflib.get_close_matches(model, SUPPORTED_MODELS, n=3, cutoff=0.2)
        hint = f"\n你可能想用: {', '.join(suggestions)}" if suggestions else ""
        return [
            TextContent(
                type="text",
                text=(
                    f"错误: 不支持的 model: {model}{hint}\n"
                    f"请从以下模型中选择: {', '.join(SUPPORTED_MODELS)}"
                ),
            )
        ]

    if _model_requires_reference_images(model) and not images:
        return [
            TextContent(
                type="text",
                text=(
                    "❌ 生成失败：该视频模型需要至少 1 张参考图，但当前提供了 0 张。\n\n"
                    "排查建议：\n"
                    "- 先调用 `history` 查看历史记录，找到包含图片的那条\n"
                    "- 再用 `generate` 的 `history_id` 指向那条记录的稳定序号\n"
                ),
            )
        ]

    reasoning_text = ""
    content_text = ""
    client = await http_client.get_client()
    base_url = get_base_url()
    api_key = get_api_key()

    messages: list[dict[str, Any]] = [{"role": "user", "content": content}]

    attempt = 0
    used_model = model
    tried_models: set[str] = {used_model}
    retry_count = max(0, min(int(GENERATE_RETRY_COUNT), 10))
    max_attempts = 1 + retry_count
    if retry_count > 0:
        mcp_logs.append(f"auto retry: {retry_count} (sleep 2s, same model)")

    status = 0
    reasoning_text = ""
    content_text = ""
    err_text = ""
    first_error_summary = ""

    while True:
        attempt += 1
        mcp_logs.append(f"attempt {attempt}: {used_model}")
        status, reasoning_text, content_text, err_text = await _flow2api_stream_chat_completions(
            client,
            base_url=base_url,
            api_key=api_key,
            model=used_model,
            messages=messages,
        )

        if attempt == 1:
            first_error_summary = (err_text.strip() or reasoning_text.strip() or "")[:500]

        ok = status == 200 and bool(content_text.strip())
        if ok:
            mcp_logs.append("status: 200 OK")
            break
        if status != 200:
            brief_err = (err_text.strip() or reasoning_text.strip() or "")[:120].replace("\n", " ")
            if brief_err:
                mcp_logs.append(f"status: HTTP {status} ({brief_err})")
            else:
                mcp_logs.append(f"status: HTTP {status}")
        else:
            mcp_logs.append("status: 200 but empty content")
            # Empty parsing results are not retryable; retrying wastes quota.
            if err_text.strip().startswith("empty content extracted"):
                break

        if attempt >= max_attempts:
            break

        mcp_logs.append("retry after 2s (same model)")
        await asyncio.sleep(2)

    if status != 200:
        error_summary = (err_text.strip() or reasoning_text.strip() or first_error_summary or "无结果")[:500]
        error_msg = (
            f"❌ 生成失败：{error_summary}\n\n"
            "排查建议：\n"
            "- 检查 `FLOW2API_API_KEY` 是否正确/有权限（403 常见原因）\n"
            "- 确认模型名称是否可用/账号是否有配额\n"
            "- 如仍失败，可尝试更换 `FLOW2API_BASE_URL` 指向的上游或换其他模型\n"
        )
        history_manager.add_failure(used_model, prompt, error_summary)
        return [TextContent(type="text", text=error_msg)]

    if not content_text.strip():
        error_summary = (err_text.strip() or reasoning_text.strip() or first_error_summary or "无结果")[:500]
        error_msg = f"❌ 生成失败：{error_summary}"
        history_manager.add_failure(used_model, prompt, error_summary)
        return [TextContent(type="text", text=error_msg)]

    urls = extract_urls(content_text)
    data_urls = _extract_data_image_urls(content_text)
    mcp_logs.append(f"extracted urls: {len(urls)}")
    if data_urls:
        mcp_logs.append(f"extracted data_urls: {len(data_urls)}")

    # If upstream returned data:image/...;base64,..., store them locally and replace in output.
    data_url_map: dict[str, str] = {}
    stored_local_urls: list[str] = []
    for durl in data_urls:
        parsed = _parse_data_image_url(durl)
        if not parsed:
            continue
        mime, raw = parsed
        filename = _store_local_media(raw, mime=mime, ext=_ext_from_mime(mime))
        if not filename:
            continue
        base = _ensure_cache_http_server()
        local_url = f"{base}/mcp-cache/{filename}" if base else f"http://127.0.0.1:{CACHE_HTTP_PORT}/mcp-cache/{filename}"
        data_url_map[durl] = local_url
        stored_local_urls.append(local_url)

    # History should not store huge base64; prefer local mcp-cache links when present.
    urls_to_record = list(urls)
    if stored_local_urls:
        urls_to_record.extend(stored_local_urls)
    history_manager.add_success(used_model, prompt, urls_to_record)

    cached_count = 0
    if URL_CACHE_ENABLED and urls:
        cached_count = await _cache_urls(urls)
        mcp_logs.append(f"cached urls: {cached_count}/{len(urls)}")

    rendered_content = content_text
    if data_url_map:
        rendered_content = _replace_data_urls_with_local_urls(rendered_content, data_url_map)
    rendered_content = _replace_urls_with_cached_local_urls(rendered_content, urls)
    rendered_content = _convert_html_video_tags_to_markdown(rendered_content)
    rendered_content = _wrap_video_urls_in_markdown(rendered_content)
    rendered_content = _wrap_bare_mcp_cache_images(rendered_content)
    if URL_CACHE_ENABLED:
        if _cache_http_base_url:
            mcp_logs.append(f"local cache base: {_cache_http_base_url}")
        elif url_cache.size() > 0:
            mcp_logs.append("local cache: enabled")

    final_text = rendered_content.strip() or "无结果"
    mcp_block = ""
    if mcp_logs:
        mcp_block = "\n".join(mcp_logs).strip()

    upstream_block = reasoning_text.strip()

    if mcp_block or upstream_block:
        sections: list[str] = []
        if mcp_block:
            sections.append("### MCP\n\n```text\n" + mcp_block + "\n```")
        if upstream_block:
            sections.append("### 上游\n\n```text\n" + upstream_block + "\n```")

        final_text = (
            "<details><summary>思考/日志</summary>\n\n"
            + "\n\n".join(sections)
            + "\n\n</details>\n\n"
            + final_text
        )

    return [TextContent(type="text", text=final_text)]



async def handle_history(args: dict[str, Any]) -> list[TextContent]:
    scope = str(args.get("scope") or "recent").strip() or "recent"
    if scope not in ("recent", "archive"):
        scope = "recent"

    limit = int(args.get("limit", 5) or 5)

    def _render_one(item: dict[str, Any], *, title: str) -> str:
        sizes = history_manager.sizes()
        lines: list[str] = [
            title,
            f"- 统计: recent={sizes['recent']}, archive={sizes['archive']}",
            "",
        ]

        hid = item.get("id")
        hid_text = str(hid) if isinstance(hid, int) and hid > 0 else ""
        lines.append(f"## {hid_text}. {item.get('time', '')}")
        lines.append(f"- 模型: `{item.get('model', '')}`")
        prompt = str(item.get("prompt", ""))
        lines.append(f"- 提示: {prompt}")

        if item.get("error"):
            err = str(item.get("error"))
            lines.append(f"- 状态: ❌ 失败 - {err[:500]}")
        else:
            urls = list(item.get("urls", []) or [])
            if urls:
                lines.append("- 结果:")
                for j, url in enumerate(urls, 1):
                    display_url = url
                    local_url = _get_cached_local_url(url)
                    if local_url:
                        display_url = local_url
                    is_local = bool(local_url) or _is_local_cache_url(url)

                    kind = "video" if _is_likely_video_url(url) else "image"
                    locality = "📦" if is_local else "🌐"

                    if kind == "image":
                        lines.append(f"  - {locality} ![history-{hid_text}-{j}]({display_url})")
                    else:
                        lines.append(f"  - {locality} [video]({display_url})")
            else:
                lines.append("- 状态: ⚠️ 成功但未提取到URL")
        lines.append("")
        return "\n".join(lines)

    if args.get("history_id") is not None:
        try:
            item_id = int(args.get("history_id"))
        except Exception:
            return [TextContent(type="text", text="错误: history_id 必须是整数")]

        # Use archive by default for stable lookup; fall back to recent if needed.
        item = history_manager.get_by_id(item_id, scope="archive") or history_manager.get_by_id(item_id, scope="recent")
        if not item:
            return [TextContent(type="text", text=f"未找到该 history_id: {item_id}")]

        return [TextContent(type="text", text=_render_one(item, title="# 生成历史（单条）"))]

    query = str(args.get("query") or args.get("keyword") or "").strip()
    if query:
        items = history_manager.get_archive(MAX_HISTORY_ARCHIVE_SIZE) if scope == "archive" else history_manager.get_recent(MAX_HISTORY_RECENT_SIZE)
        q = query.lower()

        def _match(it: dict[str, Any]) -> bool:
            haystacks = [
                str(it.get("prompt", "")),
                str(it.get("model", "")),
                str(it.get("time", "")),
                " ".join([str(u) for u in (it.get("urls", []) or [])]),
            ]
            return any(q in h.lower() for h in haystacks if h)

        matches = [it for it in items if _match(it)]
        if not matches:
            return [
                TextContent(
                    type="text",
                    text=(
                        f"未找到匹配记录：`{query}`\n\n"
                        "建议：\n"
                        "- 调大 limit 或改用 scope=archive\n"
                        "- 或直接用 history_id 精准查询：`history { \"history_id\": 123 }`"
                    ),
                )
            ]

        if len(matches) == 1:
            return [TextContent(type="text", text=_render_one(matches[0], title="# 生成历史（搜索结果-单条）"))]

        sizes = history_manager.sizes()
        lines: list[str] = [
            "# 生成历史（搜索候选）",
            f"- query: `{query}`",
            f"- 命中: {len(matches)}",
            f"- 统计: recent={sizes['recent']}, archive={sizes['archive']}",
            "",
            "请从下列候选中选择一个 `history_id`：",
        ]
        for it in matches[: min(10, len(matches))]:
            hid = it.get("id")
            hid_text = str(hid) if isinstance(hid, int) and hid > 0 else "?"
            time_text = str(it.get("time", ""))
            model_text = str(it.get("model", ""))
            prompt_text = str(it.get("prompt", "")).replace("\n", " ").strip()
            if len(prompt_text) > 80:
                prompt_text = prompt_text[:80] + "..."
            lines.append(f"- `{hid_text}` | {time_text} | `{model_text}` | {prompt_text}")

        if len(matches) > 10:
            lines.append(f"\n（仅展示前 10 条候选；可改用 scope=archive 或更具体的 query）")

        return [TextContent(type="text", text="\n".join(lines))]

    if history_manager.is_empty(scope=scope):
        return [TextContent(type="text", text="暂无生成历史")]

    sizes = history_manager.sizes()
    lines: list[str] = [f"# 生成历史（{scope}）", f"- 统计: recent={sizes['recent']}, archive={sizes['archive']}", ""]

    items = history_manager.get_archive(limit) if scope == "archive" else history_manager.get_recent(limit)
    for i, h in enumerate(items, 1):
        hid = h.get("id")
        hid_text = str(hid) if isinstance(hid, int) and hid > 0 else str(i)
        lines.append(f"## {hid_text}. {h.get('time', '')}")
        lines.append(f"- 模型: `{h.get('model', '')}`")
        prompt = str(h.get("prompt", ""))
        lines.append(f"- 提示: {prompt[:50]}{'...' if len(prompt) > 50 else ''}")

        if h.get("error"):
            err = str(h.get("error"))
            lines.append(f"- 状态: ❌ 失败 - {err[:100]}")
        else:
            urls = list(h.get("urls", []) or [])
            if urls:
                lines.append("- 结果:")
                for j, url in enumerate(urls, 1):
                    display_url = url
                    local_url = _get_cached_local_url(url)
                    if local_url:
                        display_url = local_url
                    is_local = bool(local_url) or _is_local_cache_url(url)

                    kind = "video" if _is_likely_video_url(url) else "image"
                    locality = "📦" if is_local else "🌐"

                    # Prefer direct rendering for better UX (most clients render Markdown images).
                    if kind == "image":
                        lines.append(f"  - {locality} ![history-{i}-{j}]({display_url})")
                    else:
                        lines.append(f"  - {locality} [video]({display_url})")
            else:
                lines.append("- 状态: ⚠️ 成功但未提取到URL")
        lines.append("")

    return [TextContent(type="text", text="\n".join(lines))]


async def handle_cache(args: dict[str, Any]) -> list[TextContent]:
    action = str(args.get("action") or "status").strip() or "status"
    if action not in ("status", "clear", "prune"):
        action = "status"

    include_history = bool(args.get("include_history", False))
    confirm = bool(args.get("confirm", False))
    keep = int(args.get("keep", 50) or 50)

    if action == "status":
        sizes = history_manager.sizes()
        return [
            TextContent(
                type="text",
                text=(
                    "# 缓存/历史状态\n\n"
                    f"- url_cache_entries: {url_cache.size()}\n"
                    f"- recent_history: {sizes['recent']}\n"
                    f"- archive_history: {sizes['archive']}\n"
                    f"- url_cache_dir: {URL_CACHE_DIR}\n"
                ),
            )
        ]

    if include_history and (action in ("clear", "prune")) and (not confirm):
        sizes = history_manager.sizes()
        return [
            TextContent(
                type="text",
                text=(
                    "⚠️ 该操作将删除历史记录，但未提供确认参数。\n\n"
                    "当前统计：\n"
                    f"- url_cache_entries: {url_cache.size()}\n"
                    f"- recent_history: {sizes['recent']}\n"
                    f"- archive_history: {sizes['archive']}\n\n"
                    "如确认执行，请在原参数基础上增加 `confirm=true`：\n"
                    f"- `cache {{ \"action\": \"{action}\", \"include_history\": true, \"confirm\": true"
                    + (f", \"keep\": {keep}" if action == "prune" else "")
                    + " }`"
                ),
            )
        ]

    if action == "clear":
        cache_removed = url_cache.size()
        url_cache.clear_all()

        history_removed = {"recent_removed": 0, "archive_removed": 0}
        if include_history:
            history_removed = history_manager.clear_all()

        return [
            TextContent(
                type="text",
                text=(
                    "# 已清理\n\n"
                    f"- url_cache_removed: {cache_removed}\n"
                    f"- history_recent_removed: {history_removed['recent_removed']}\n"
                    f"- history_archive_removed: {history_removed['archive_removed']}\n"
                ),
            )
        ]

    # prune
    cache_removed = url_cache.prune_to(keep)
    history_removed = {"recent_removed": 0, "archive_removed": 0}
    if include_history:
        history_removed = history_manager.prune_to(keep)

    return [
        TextContent(
            type="text",
            text=(
                "# 已裁剪\n\n"
                f"- keep: {keep}\n"
                f"- url_cache_removed: {cache_removed}\n"
                f"- history_recent_removed: {history_removed['recent_removed']}\n"
                f"- history_archive_removed: {history_removed['archive_removed']}\n"
            ),
        )
    ]


@server.list_tools()
async def list_tools():
    """列出可用的工具"""
    return get_tools()


@server.call_tool()
async def call_tool(name: str, args: dict):
    """处理工具调用"""
    if name == "history":
        return await handle_history(args)
    elif name == "cache":
        return await handle_cache(args)
    elif name == "generate":
        return await handle_generate(args)
    else:
        return [TextContent(type="text", text=f"未知工具: {name}")]


async def main():
    """启动MCP服务器"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


def run() -> None:
    """Console script entrypoint."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
