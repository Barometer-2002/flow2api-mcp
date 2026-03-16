"""Pure utility functions for URL parsing, MIME detection, and media helpers."""

from __future__ import annotations

import base64
import re
import urllib.parse
from pathlib import Path
from typing import Optional

from .config import get_api_key, get_base_url


def normalize_cache_key(url: str) -> str:
    """Strip query string and fragment for cache key normalization."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return url
    if not (parsed.query or parsed.fragment):
        return url
    normalized = parsed._replace(query="", fragment="")
    return urllib.parse.urlunparse(normalized)


def auth_headers_for_url(url: str) -> dict[str, str]:
    """Return auth headers for Flow2API ``/tmp/...`` URLs on the same host."""
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


def is_under_root(path: Path, root: Path) -> bool:
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


def local_file_uri_to_path(value: str) -> Optional[Path]:
    """Convert a local file path or ``file:///`` URI to a :class:`Path`."""
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


# ---- MIME helpers ----

_EXT_TO_MIME: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
}

_MIME_TO_EXT: dict[str, str] = {
    "image/png": "png",
    "image/jpg": "jpg",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/tif": "tiff",
    "image/tiff": "tiff",
}


def guess_mime_from_ext(ext: str) -> Optional[str]:
    return _EXT_TO_MIME.get((ext or "").lower().lstrip("."))


def guess_mime_and_ext(url: str, content_type: str) -> tuple[str, str]:
    ct = (content_type or "").lower()
    low = url.lower()
    if "png" in ct or low.endswith(".png"):
        return "image/png", "png"
    if "webp" in ct or low.endswith(".webp"):
        return "image/webp", "webp"
    if "gif" in ct or low.endswith(".gif"):
        return "image/gif", "gif"
    return "image/jpeg", "jpg"


def ext_from_mime(mime: str) -> str:
    return _MIME_TO_EXT.get((mime or "").lower().strip(), "jpg")


# ---- URL detection / extraction ----


def is_likely_image_url(url: str) -> bool:
    lower = url.lower().split("?", 1)[0]
    return lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))


def extract_urls(text: str) -> list[str]:
    """Extract image URLs from text content."""
    urls: list[str] = []

    # Standard image URLs
    pattern1 = (
        r"https?://[^\s\)\"'\]\[<>]+\.(?:png|jpg|jpeg|gif|webp)"
        r"(?:\?[^\s\)\"'\]\[<>]*)?"
    )
    urls.extend(re.findall(pattern1, text, re.I))

    # Flow2API /tmp/ URLs
    pattern2 = r"https?://[^\s\)\"'\]\[<>]+/tmp/[a-f0-9]{32}\.(?:jpg|png)"
    urls.extend(re.findall(pattern2, text, re.I))

    # Markdown image links
    pattern3 = r"!\[[^\]]*\]\((https?://[^\)]+)\)"
    for match in re.findall(pattern3, text, re.I):
        urls.append(match)

    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u))]  # type: ignore[func-returns-value]


# ---- data: URI helpers ----


def extract_data_image_urls(text: str) -> list[str]:
    if not text:
        return []
    pattern = re.compile(r"(data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+)")
    seen: set[str] = set()
    out: list[str] = []
    for m in pattern.findall(text):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def parse_data_image_url(data_url: str) -> Optional[tuple[str, bytes]]:
    s = str(data_url or "").strip()
    if not s.startswith("data:image/"):
        return None
    try:
        header, b64 = s.split(",", 1)
    except ValueError:
        return None
    if ";base64" not in header.lower():
        return None
    try:
        mime = header.lower().split(":", 1)[1].split(";", 1)[0].strip()
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


def replace_data_urls_with_local(text: str, mapping: dict[str, str]) -> str:
    if not text or not mapping:
        return text
    out = text
    for k, v in mapping.items():
        if k in out:
            out = out.replace(k, v)
    return out


def wrap_bare_cache_images(text: str) -> str:
    """Wrap bare ``/mcp-cache`` image URLs as Markdown images."""
    if not text:
        return text
    pattern = re.compile(
        r"(?<!\]\()(?P<url>https?://(?:127\.0\.0\.1|localhost):\d+/mcp-cache/"
        r"[^\s\)\"'\]\[<>]+\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s\)\"'\]\[<>]*)?)",
        re.I,
    )

    def _one(match: re.Match[str]) -> str:
        return f"![Generated Image]({match.group('url')})"

    return pattern.sub(_one, text)
