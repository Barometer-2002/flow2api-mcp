"""Configuration constants and environment variable parsing."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .env_loader import load_project_env

load_project_env()

PROJECT_ROOT = Path(__file__).parent
HISTORY_FILE = PROJECT_ROOT / "history.json"
HISTORY_ARCHIVE_FILE = PROJECT_ROOT / "history_archive.json"
MODELS_CONFIG_FILE = PROJECT_ROOT / "models.json"

URL_CACHE_DIR = PROJECT_ROOT / "url_cache"
URL_CACHE_INDEX_FILE = PROJECT_ROOT / "url_cache.json"
URL_CACHE_ENABLED = os.environ.get("FLOW2API_MCP_URL_CACHE", "0") != "0"
URL_CACHE_MAX_ENTRIES = int(os.environ.get("FLOW2API_MCP_URL_CACHE_MAX_ENTRIES", "200"))
URL_CACHE_MAX_FILE_BYTES = (
    int(os.environ.get("FLOW2API_MCP_URL_CACHE_MAX_FILE_BYTES", "100")) * 1024 * 1024
)
DEBUG_LOGS = os.environ.get("FLOW2API_MCP_DEBUG", "0") != "0"

# User image import directory
# Priority: FLOW2API_MCP_IMAGE_DIR > FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR > FLOW2API_MCP_LOCAL_FILES_ROOT
_image_dir_env = (os.environ.get("FLOW2API_MCP_IMAGE_DIR") or "").strip()
_cherrystudio_dir_env = (os.environ.get("FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR") or "").strip()
_legacy_dir_env = (os.environ.get("FLOW2API_MCP_LOCAL_FILES_ROOT") or "").strip()
_resolved_dir = _image_dir_env or _cherrystudio_dir_env or _legacy_dir_env
USER_IMAGE_DIR: Path | None = (
    Path(_resolved_dir).expanduser() if _resolved_dir else None
)

MAX_HISTORY_RECENT_SIZE = int(os.environ.get("FLOW2API_MCP_HISTORY_RECENT_SIZE", "50"))
MAX_HISTORY_ARCHIVE_SIZE = int(os.environ.get("FLOW2API_MCP_HISTORY_ARCHIVE_SIZE", "2000"))

GENERATE_RETRY_COUNT = int(os.environ.get("FLOW2API_MCP_GENERATE_RETRY_COUNT", "0"))

DEFAULT_IMAGE_TEXT_LANGUAGE_PROMPT_SUFFIX = (
    "\n\n"
    "【默认规则】画面/字幕/标牌/海报/界面等任何可见文字默认使用简体中文；"
    "除非我在提示词里明确指定其他语言或多语言。"
)
IMAGE_PROMPT_SUFFIX = os.environ.get(
    "FLOW2API_MCP_PROMPT_SUFFIX",
    DEFAULT_IMAGE_TEXT_LANGUAGE_PROMPT_SUFFIX,
)

HTTP_TIMEOUT = 600.0
HTTP_CONNECT_TIMEOUT = 30.0
MAX_CONNECTIONS = 10
MAX_KEEPALIVE_CONNECTIONS = 5

DEFAULT_BASE_URL = "http://localhost:8000"

SUPPORTED_MODELS_FALLBACK: list[str] = [
    "gemini-3.0-pro-image-landscape",
    "gemini-3.0-pro-image-portrait",
    "gemini-2.5-flash-image-landscape",
    "gemini-2.5-flash-image-portrait",
    "imagen-4.0-generate-preview-landscape",
    "imagen-4.0-generate-preview-portrait",
]

MODEL_SELECTION_GUIDE_FALLBACK = (
    "## 选型指南\n"
    "- 质量优先：`gemini-3.0-pro-image-*`\n"
    "- 速度优先：`gemini-3.1-flash-image-*` 或 `gemini-2.5-flash-image-*`\n"
    "- 独特风格：`imagen-4.0-generate-preview-*`\n"
    "- 横竖屏：`-landscape`=横屏，`-portrait`=竖屏，`-square`=方图\n"
    "- 分辨率：无后缀=标准，`-2k`=2K，`-4k`=4K\n"
)


def _load_models_config(path: Path) -> tuple[list[str], str, str]:
    """Load models, default_model, and selection_guide from models.json."""
    fallback_default = SUPPORTED_MODELS_FALLBACK[0]
    if not path.exists():
        return list(SUPPORTED_MODELS_FALLBACK), fallback_default, MODEL_SELECTION_GUIDE_FALLBACK
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[MCP] 加载 models.json 失败: {exc}", file=sys.stderr)
        return list(SUPPORTED_MODELS_FALLBACK), fallback_default, MODEL_SELECTION_GUIDE_FALLBACK

    models_raw = data.get("models")
    models: list[str] = [str(x).strip() for x in (models_raw or []) if str(x).strip()]
    if not models:
        models = list(SUPPORTED_MODELS_FALLBACK)

    default_model = str(data.get("default_model") or models[0]).strip() or models[0]
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


def model_selection_guide() -> str:
    return MODEL_SELECTION_GUIDE


def get_base_url() -> str:
    return os.environ.get("FLOW2API_BASE_URL", DEFAULT_BASE_URL)


def get_api_key() -> str:
    return os.environ.get("FLOW2API_API_KEY", "")


def debug(msg: str) -> None:
    if DEBUG_LOGS:
        print(f"[MCP][debug] {msg}", file=sys.stderr)
