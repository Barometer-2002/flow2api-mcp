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

URL_CACHE_DIR = PROJECT_ROOT / "url_cache"
URL_CACHE_INDEX_FILE = PROJECT_ROOT / "url_cache.json"
URL_CACHE_ENABLED = os.environ.get("FLOW2API_MCP_URL_CACHE", "1") != "0"
URL_CACHE_MAX_ENTRIES = int(os.environ.get("FLOW2API_MCP_URL_CACHE_MAX_ENTRIES", "200"))
URL_CACHE_MAX_FILE_BYTES = int(
    os.environ.get("FLOW2API_MCP_URL_CACHE_MAX_FILE_BYTES", str(100 * 1024 * 1024))
)
HISTORY_MEDIA_CACHE_ENABLED = os.environ.get("FLOW2API_MCP_HISTORY_MEDIA_CACHE", "1") != "0"
HISTORY_MEDIA_CACHE_MAX_URLS = int(os.environ.get("FLOW2API_MCP_HISTORY_MEDIA_CACHE_MAX_URLS", "6"))
HISTORY_MEDIA_CACHE_TIMEOUT_SECS = float(
    os.environ.get("FLOW2API_MCP_HISTORY_MEDIA_CACHE_TIMEOUT_SECS", "20")
)
CACHE_FIRST_RENDERING_ENABLED = os.environ.get("FLOW2API_MCP_CACHE_FIRST_RENDERING", "1") != "0"

MAX_HISTORY_RECENT_SIZE = int(os.environ.get("FLOW2API_MCP_HISTORY_RECENT_SIZE", "50"))
MAX_HISTORY_ARCHIVE_SIZE = int(os.environ.get("FLOW2API_MCP_HISTORY_ARCHIVE_SIZE", "2000"))

GENERATE_MODEL_RETRY_COUNT = int(os.environ.get("FLOW2API_MCP_GENERATE_MODEL_RETRY_COUNT", "3"))

HTTP_TIMEOUT = 600.0
HTTP_CONNECT_TIMEOUT = 30.0
MAX_CONNECTIONS = 10
MAX_KEEPALIVE_CONNECTIONS = 5

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_MODEL = "gemini-3.0-pro-image-landscape"

SUPPORTED_MODELS: list[str] = [
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


def _model_selection_guide() -> str:
    return (
        "## 选型指南（如何选择 model）\n"
        "- 图片：优先 `gemini-3.0-pro-image-*`（质量最好）；追求速度用 `gemini-2.5-flash-image-*`；想要更“写实/摄影”可试 `imagen-4.0-generate-preview-*`\n"
        "- 视频（文生视频 T2V）：`veo_3_1_t2v_fast_*`（最新/推荐）> `veo_2_1_fast_d_15_t2v_*` > `veo_2_0_t2v_*`\n"
        "- 视频（图生视频 I2V，支持首帧/首尾帧）：`veo_3_1_i2v_s_fast_fl_*`（最新/推荐）> `veo_2_1_fast_d_15_i2v_*` > `veo_2_0_i2v_*`\n"
        "- 视频（多参考图 R2V）：`veo_3_0_r2v_fast_*`\n"
        "- 横竖屏：后缀 `-landscape`=横屏，`-portrait`=竖屏\n"
    )


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
        self._load_history()

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
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": model,
            "prompt": prompt,
            "urls": urls,
            "error": None,
        }
        self._recent.append(item)
        self._archive.append(item)
        self._save_history()

    def add_failure(self, model: str, prompt: str, error: str) -> None:
        item = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": model,
            "prompt": prompt,
            "urls": [],
            "error": error,
        }
        self._recent.append(item)
        self._archive.append(item)
        self._save_history()

    def get_recent(self, limit: int = 5) -> list[dict[str, Any]]:
        limit = min(int(limit), MAX_HISTORY_RECENT_SIZE)
        return list(self._recent)[-limit:][::-1]

    def get_archive(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = min(int(limit), MAX_HISTORY_ARCHIVE_SIZE)
        return list(self._archive)[-limit:][::-1]

    def get_by_index(self, index: int, scope: str = "recent") -> Optional[dict[str, Any]]:
        if scope == "archive":
            history_list = list(self._archive)
        else:
            history_list = list(self._recent)

        if 1 <= index <= len(history_list):
            return history_list[-index]
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

    # Backward-compatible aliases (older code paths)
    def get_recent_default(self, limit: int = 5) -> list[dict[str, Any]]:
        return self.get_recent(limit)

    def get_by_index_default(self, index: int) -> Optional[dict[str, Any]]:
        return self.get_by_index(index, scope="recent")

    def is_empty_default(self) -> bool:
        return self.is_empty(scope="recent")


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
            )
        return self._client


http_client = HttpClient()


def _is_image_model(model: str) -> bool:
    return not str(model).startswith("veo_")


def _orientation_suffix(model: str) -> str:
    s = str(model)
    if s.endswith("-portrait"):
        return "-portrait"
    if s.endswith("-landscape"):
        return "-landscape"
    return ""


def _select_fallback_model(model: str) -> str:
    """Select a different model for a single retry.

    Heuristic:
    - Keep orientation if possible (landscape/portrait).
    - Keep media type family: image vs video.
    - Prefer newer/recommended variants first.
    """

    model = str(model or "").strip() or DEFAULT_MODEL
    orient = _orientation_suffix(model)

    if _is_image_model(model):
        candidates = [
            f"gemini-3.0-pro-image{orient}",
            f"gemini-2.5-flash-image{orient}",
            f"imagen-4.0-generate-preview{orient}",
            "gemini-3.0-pro-image-landscape",
            "gemini-2.5-flash-image-landscape",
            "imagen-4.0-generate-preview-landscape",
        ]
    else:
        # Keep the video family (t2v/i2v/r2v) if possible.
        if "_t2v_" in model:
            candidates = [
                f"veo_3_1_t2v_fast{orient}",
                f"veo_2_1_fast_d_15_t2v{orient}",
                f"veo_2_0_t2v{orient}",
                "veo_3_1_t2v_fast_landscape",
                "veo_2_1_fast_d_15_t2v_landscape",
                "veo_2_0_t2v_landscape",
            ]
        elif "_i2v_" in model:
            candidates = [
                f"veo_3_1_i2v_s_fast_fl{orient}",
                f"veo_2_1_fast_d_15_i2v{orient}",
                f"veo_2_0_i2v{orient}",
                "veo_3_1_i2v_s_fast_fl_landscape",
                "veo_2_1_fast_d_15_i2v_landscape",
                "veo_2_0_i2v_landscape",
            ]
        elif "_r2v_" in model:
            candidates = [
                f"veo_3_0_r2v_fast{orient}",
                "veo_3_0_r2v_fast_landscape",
                "veo_3_0_r2v_fast_portrait",
            ]
        else:
            candidates = [
                f"veo_3_1_t2v_fast{orient}",
                f"veo_2_1_fast_d_15_t2v{orient}",
                f"veo_2_0_t2v{orient}",
                "veo_3_1_t2v_fast_landscape",
            ]

    for cand in candidates:
        if cand and cand != model and cand in SUPPORTED_MODELS:
            return cand

    for cand in SUPPORTED_MODELS:
        if cand != model:
            return cand
    return model


def _clamp_int(value: int, *, min_value: int, max_value: int) -> int:
    return max(min_value, min(int(value), max_value))


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

    try:
        async with client.stream(
            "POST",
            f"{base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "stream": True,
            },
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

                payload: Optional[str] = None
                if line.startswith("data: "):
                    payload = line[6:]
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

                if isinstance(data, dict) and data.get("error"):
                    err = data.get("error") or {}
                    err_msg = str(err.get("message") or err)[:2000]
                    return 500, "", "", err_msg

                delta = data.get("choices", [{}])[0].get("delta", {}) if isinstance(data, dict) else {}
                reasoning_delta = str(delta.get("reasoning_content") or "")
                if reasoning_delta:
                    reasoning_text += reasoning_delta

                content_delta = delta.get("content", "")
                if isinstance(content_delta, str) and content_delta:
                    content_text += content_delta
    except Exception as exc:
        return 0, "", "", str(exc)[:2000]

    return 200, reasoning_text, content_text, ""


# -----------------------------
# URL utils
# -----------------------------


def is_flow2api_cache_url(url: str) -> bool:
    base_url = get_base_url()
    return url.startswith(base_url) and "/tmp/" in url


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

    # Pattern 5: Some providers return signed video URLs without file extensions (e.g. GCS signed URLs).
    # Heuristic: treat /video/ URLs as media candidates.
    pattern5 = r"https?://[^\s\)\"'\]\[<>]+/video/[^\s\)\"'\]\[<>]+"
    urls.extend(re.findall(pattern5, text, re.I))

    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u))]


async def download_url_as_base64(url: str) -> Optional[str]:
    try:
        if URL_CACHE_ENABLED:
            cached = url_cache.get_data_uri(url)
            if cached:
                print(f"[MCP] URL缓存命中: {url}", file=sys.stderr)
                return cached

        client = await http_client.get_client()
        print(f"[MCP] 下载图片: {url}", file=sys.stderr)
        resp = await client.get(url, timeout=30)
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


def normalize_image(image: str) -> str:
    if image.startswith(("http://", "https://", "data:")):
        return image
    return f"data:image/jpeg;base64,{image}"


def _is_likely_image_url(url: str) -> bool:
    lower = url.lower().split("?", 1)[0]
    return lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))


def _is_likely_video_url(url: str) -> bool:
    lower = url.lower()
    if "/video/" in lower:
        return True
    base = lower.split("?", 1)[0]
    return base.endswith((".mp4", ".webm"))


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
                self._index = data
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
        meta = self._index.get(url)
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
        meta = self._index.get(url) or {}
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
        meta = self._index.get(url)
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
        key = hashlib.md5(url.encode("utf-8")).hexdigest()
        filename = f"{key}.{ext}"
        p = URL_CACHE_DIR / filename
        try:
            p.write_bytes(raw)
            self._index[url] = {
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

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), CacheHandler)
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
    if not (URL_CACHE_ENABLED and CACHE_FIRST_RENDERING_ENABLED):
        return None
    if not url_cache.has(url):
        return None

    url_cache._load()  # ensure index loaded
    meta = url_cache._index.get(url) or {}
    filename = meta.get("filename")
    if not filename and meta.get("path"):
        filename = Path(str(meta["path"])).name
    if not filename:
        return None

    base = _ensure_cache_http_server()
    if not base:
        return None
    return f"{base}/mcp-cache/{filename}"


def _replace_urls_with_cached_local_urls(text: str, urls: list[str]) -> str:
    if not text:
        return text
    if not (URL_CACHE_ENABLED and CACHE_FIRST_RENDERING_ENABLED):
        return text

    out = text
    for url in urls:
        if url not in out:
            continue
        local_url = _get_cached_local_url(url)
        if local_url:
            out = out.replace(url, local_url)
    return out


async def _cache_url_media(url: str) -> bool:
    if not URL_CACHE_ENABLED:
        return False
    if url_cache.has(url):
        return True

    try:
        client = await http_client.get_client()
        resp = await client.get(url, timeout=30)
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

        ok = url_cache.put(url, resp.content, mime=mime, ext=ext)
        if not ok:
            print(f"[MCP] 缓存写入失败: {url}", file=sys.stderr)
        return ok
    except Exception:
        return False


async def _cache_urls_blocking(urls: list[str]) -> None:
    async def _one(url: str) -> None:
        async with _cache_semaphore:
            try:
                await asyncio.wait_for(
                    _cache_url_media(url),
                    timeout=HISTORY_MEDIA_CACHE_TIMEOUT_SECS,
                )
            except Exception:
                return

    await asyncio.gather(*[_one(u) for u in urls], return_exceptions=True)


async def download_url_as_base64(url: str) -> Optional[str]:
    try:
        if URL_CACHE_ENABLED:
            cached = url_cache.get_data_uri(url)
            if cached:
                print(f"[MCP] URL缓存命中: {url}", file=sys.stderr)
                return cached

        client = await http_client.get_client()
        print(f"[MCP] 下载图片: {url}", file=sys.stderr)
        resp = await client.get(url, timeout=30)
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


def normalize_image(image: str) -> str:
    if image.startswith(("http://", "https://", "data:")):
        return image
    return f"data:image/jpeg;base64,{image}"


def _is_likely_image_url(url: str) -> bool:
    lower = url.lower().split("?", 1)[0]
    return lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))


def _is_likely_video_url(url: str) -> bool:
    lower = url.lower()
    if "/video/" in lower:
        return True
    base = lower.split("?", 1)[0]
    return base.endswith((".mp4", ".webm"))


# -----------------------------
# Tools (schema + handlers)
# -----------------------------


DEFAULT_IMAGE_TEXT_LANGUAGE_PROMPT_SUFFIX = (
    "\n\n"
    "【默认规则】画面/字幕/标牌/海报/界面等任何可见文字默认使用简体中文；"
    "除非我在提示词里明确指定其他语言或多语言。"
)


GENERATE_DESC = (
    """生成图片或视频的工具。

## 使用场景
调用工具前后请自然地与用户交流，不要只是默默调用。
1. 用户明确要求生成图片或视频时
2. 对话中需要可视化展示某个概念、想法、场景时可以主动调用
3. 用户发了图片想要修改、转换风格、生成视频时

## 输出规则（很重要）
很多客户端会把“工具返回结果”折叠/隐藏，用户只能看到你最后的正文回复。
因此：**调用本工具后，你必须把工具返回的结果（尤其是图片/视频的 Markdown/HTML 链接）原样粘贴到你的正文回复里**，不要只停留在工具返回区。
如果结果里包含 `思考/日志` 折叠块，也可以一并贴出（可选）。

## 画图元提示词（用于增强提交给模型的prompt）
在调用本工具前，先把用户的自然语言意图“改写/扩写”为更适合图像/视频生成模型的提示词，然后再把扩写后的文本作为 `prompt` 参数提交。
要求：
- 不改变用户核心需求与风格偏好；不擅自添加敏感/违规内容
- 信息不足时先提 1-3 个澄清问题；否则给出一版可直接生成的高质量提示词
- 输出一段“单段落”提示词，尽量包含：主体、场景、构图、镜头/视角、光线、色彩、材质细节、风格、氛围、质量/清晰度、（可选）负面约束
- 避免口水话；用具体可视化细节替代抽象词（如“好看”“高级”）
- 与本服务默认规则一致：画面内可见文字默认简体中文，除非用户明确指定其他语言

## 参数说明
- model: 必填，模型名称，从下面列表选
- prompt: 必填，描述你想生成什么
- history_index: 可选，基于历史结果继续生成

注意：`history_index` 目前只会复用“图片”结果作为参考图（图生图/图生视频）；不支持把“视频”作为参考输入进行视频生视频。

## 返回结果
返回markdown格式的图片或视频链接，直接展示给用户即可。"""
    "\n\n"
    + _model_selection_guide()
)


HISTORY_DESC = """查看生成历史。

返回最近的生成记录，包含：序号、时间、模型、提示词、结果URL。
用户想修改之前的结果时，可以先查历史，然后用URL作为images参数再次生成。

## 输出规则（很重要）
调用本工具后，请把返回的历史列表粘贴到你的正文回复里（而不是只让它留在工具返回区）。

参数：
- limit: 返回条数，默认5
- scope: recent=短期历史 / archive=长期归档（默认recent）"""


CACHE_DESC = """缓存/历史清理工具。

用于释放磁盘空间或重置状态：
- status: 查看当前缓存/历史统计
- clear: 清空本机媒体缓存（url_cache），可选同时清空历史
- prune: 只保留最近 N 条缓存/历史（默认 50）

注意：这会删除本地文件（`mcp_server/url_cache/` 等）。"""


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
                    "history_index": {
                        "type": "integer",
                        "description": "使用历史记录中的图片，1表示最近一条。会自动读取本地缓存转为base64",
                    },
                    "history_scope": {
                        "type": "string",
                        "enum": ["recent", "archive"],
                        "default": "recent",
                        "description": "history_index 的来源范围：recent=短期历史，archive=长期归档（默认recent）",
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
                },
            },
        ),
    ]


async def handle_generate(args: dict[str, Any]) -> list[TextContent]:
    images: list[str] = []
    warnings: list[str] = []
    used_history_index = False

    if args.get("images"):
        return [
            TextContent(
                type="text",
                text="错误: 当前 MCP 不支持透传用户上传图片进行图生图；请使用纯文本生成，或使用 history_index 基于历史结果继续生成。",
            )
        ]

    if args.get("history_index"):
        used_history_index = True
        idx = int(args["history_index"])
        history_scope = str(args.get("history_scope") or "recent").strip() or "recent"
        if history_scope not in ("recent", "archive"):
            history_scope = "recent"

        history_item = history_manager.get_by_index(idx, scope=history_scope)
        if history_item:
            print(f"[MCP] 使用history_index={idx} (scope={history_scope})", file=sys.stderr)
            for url in history_item.get("urls", []) or []:
                if not _is_likely_image_url(url):
                    continue
                b64 = await download_url_as_base64(url)
                if b64:
                    images.append(b64)
                    print(f"[MCP] ✅ 成功转换: {url[:50]}...", file=sys.stderr)
                else:
                    print(f"[MCP] ❌ 转换失败: {url}", file=sys.stderr)
        else:
            print(f"[MCP] ⚠️ history_index={idx} 无效", file=sys.stderr)

    prompt = args.get("prompt", "")
    if not prompt:
        return [TextContent(type="text", text="错误: prompt 不能为空")]

    prompt_to_send = f"{prompt}{DEFAULT_IMAGE_TEXT_LANGUAGE_PROMPT_SUFFIX}"

    content: Any = prompt_to_send
    if images:
        content = [{"type": "text", "text": prompt_to_send}]
        for img in images:
            content.append({"type": "image_url", "image_url": {"url": img}})
    elif used_history_index:
        warnings.append("⚠️ 未能获取到可用参考图（history_index），将按纯文本生成。")

    model = str(args.get("model") or "").strip()
    if not model:
        model = DEFAULT_MODEL

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

    reasoning_text = ""
    content_text = ""
    client = await http_client.get_client()
    base_url = get_base_url()
    api_key = get_api_key()

    messages: list[dict[str, Any]] = [{"role": "user", "content": content}]

    max_retries = _clamp_int(GENERATE_MODEL_RETRY_COUNT, min_value=0, max_value=5)
    attempt = 0
    used_model = model
    tried_models: set[str] = {used_model}

    status = 0
    reasoning_text = ""
    content_text = ""
    err_text = ""
    first_error_summary = ""

    while True:
        attempt += 1
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
            break

        if attempt > (1 + max_retries):
            break

        next_model = _select_fallback_model(used_model)
        if not next_model or next_model in tried_models:
            # Avoid infinite loops if candidates are exhausted.
            break

        if status != 200:
            warnings.append(f"⚠️ 生成失败（HTTP {status}），已切换模型重试：`{used_model}` → `{next_model}`")
        else:
            warnings.append(f"⚠️ 生成无有效结果，已切换模型重试：`{used_model}` → `{next_model}`")

        tried_models.add(next_model)
        used_model = next_model

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
    cache_urls = urls[: max(0, HISTORY_MEDIA_CACHE_MAX_URLS)]
    history_manager.add_success(used_model, prompt, urls)

    if HISTORY_MEDIA_CACHE_ENABLED and cache_urls:
        await _cache_urls_blocking(cache_urls)

    rendered_content = _replace_urls_with_cached_local_urls(content_text, urls)

    final_text = rendered_content.strip() or "无结果"
    if warnings:
        final_text = "\n".join([f"> {w}" for w in warnings]) + "\n\n" + final_text
    if reasoning_text.strip():
        final_text = (
            "<details><summary>思考/日志</summary>\n\n"
            f"```\n{reasoning_text.strip()}\n```\n\n"
            "</details>\n\n"
            f"{final_text}"
        )

    return [TextContent(type="text", text=final_text)]



async def handle_history(args: dict[str, Any]) -> list[TextContent]:
    scope = str(args.get("scope") or "recent").strip() or "recent"
    if scope not in ("recent", "archive"):
        scope = "recent"

    limit = int(args.get("limit", 5) or 5)

    if history_manager.is_empty(scope=scope):
        return [TextContent(type="text", text="暂无生成历史")]

    sizes = history_manager.sizes()
    lines: list[str] = [f"# 生成历史（{scope}）", f"- 统计: recent={sizes['recent']}, archive={sizes['archive']}", ""]

    items = history_manager.get_archive(limit) if scope == "archive" else history_manager.get_recent(limit)
    for i, h in enumerate(items, 1):
        lines.append(f"## {i}. {h.get('time', '')}")
        lines.append(f"- 模型: `{h.get('model', '')}`")
        prompt = str(h.get("prompt", ""))
        lines.append(f"- 提示: {prompt[:50]}{'...' if len(prompt) > 50 else ''}")

        if h.get("error"):
            err = str(h.get("error"))
            lines.append(f"- 状态: ❌ 失败 - {err[:100]}")
        else:
            urls = list(h.get("urls", []) or [])
            if urls:
                url_info: list[str] = []
                for url in urls:
                    display_url = url
                    local_url = _get_cached_local_url(url)
                    if local_url:
                        display_url = local_url

                    kind = "video" if _is_likely_video_url(url) else "image"
                    locality = "📦" if is_flow2api_cache_url(url) else "🌐"
                    url_info.append(f"{locality} [{kind}] {display_url}")
                lines.append(f"- 结果: {', '.join(url_info)}")
            else:
                lines.append("- 状态: ⚠️ 成功但未提取到URL")
        lines.append("")

    return [TextContent(type="text", text="\n".join(lines))]


async def handle_cache(args: dict[str, Any]) -> list[TextContent]:
    action = str(args.get("action") or "status").strip() or "status"
    if action not in ("status", "clear", "prune"):
        action = "status"

    include_history = bool(args.get("include_history", False))
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
