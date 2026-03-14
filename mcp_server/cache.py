"""URL cache, local media storage, and built-in cache HTTP server."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import http.server
import json
import mimetypes
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .config import (
    CACHE_HTTP_PORT,
    URL_CACHE_DIR,
    URL_CACHE_ENABLED,
    URL_CACHE_INDEX_FILE,
    URL_CACHE_MAX_ENTRIES,
    URL_CACHE_MAX_FILE_BYTES,
    USER_IMAGE_DIR,
    debug,
)
from .utils import (
    auth_headers_for_url,
    guess_mime_and_ext,
    guess_mime_from_ext,
    is_likely_image_url,
    is_under_root,
    local_file_uri_to_path,
    normalize_cache_key,
)


# ---------------------------------------------------------------------------
# UrlCache
# ---------------------------------------------------------------------------


class UrlCache:
    """On-disk cache mapping upstream URLs to downloaded files."""

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
        items = sorted(self._index.items(), key=lambda kv: float(kv[1].get("time", 0.0) or 0.0))
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

    # ---- public API ----

    def get_data_uri(self, url: str) -> Optional[str]:
        self._load()
        meta = self._index.get(normalize_cache_key(url))
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

    def has(self, url: str) -> bool:
        self._load()
        meta = self._index.get(normalize_cache_key(url))
        if not meta:
            return False
        path = meta.get("path")
        if not path or not meta.get("mime"):
            return False
        p = Path(path)
        return p.exists() and p.is_file()

    def put(self, url: str, raw: bytes, mime: str, ext: str) -> bool:
        self._load()
        if not raw or len(raw) > URL_CACHE_MAX_FILE_BYTES:
            return False
        URL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_key = normalize_cache_key(url)
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
        items = sorted(self._index.items(), key=lambda kv: float(kv[1].get("time", 0.0) or 0.0))
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


# ---------------------------------------------------------------------------
# Local media storage
# ---------------------------------------------------------------------------


def store_local_media(raw: bytes, *, mime: str, ext: str) -> Optional[str]:
    """Save raw bytes to ``url_cache/`` and return the filename (or ``None``)."""
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


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------


async def download_url_as_base64(url: str) -> Optional[str]:
    """Download *url* and return a ``data:`` URI, with caching."""
    from .client import http_client  # late import to avoid circular dependency

    try:
        # Check local cache file first
        try:
            import urllib.parse

            parsed = urllib.parse.urlparse(url)
            path = parsed.path or ""
            if "/mcp-cache/" in path:
                filename = path.split("/mcp-cache/", 1)[1].split("?", 1)[0]
                filename = os.path.basename(filename)
                if filename:
                    file_path = URL_CACHE_DIR / filename
                    if file_path.exists():
                        content = file_path.read_bytes()
                        mime, _ext = guess_mime_and_ext(filename, "")
                        data = base64.b64encode(content).decode()
                        return f"data:{mime};base64,{data}"
        except Exception:
            pass

        if URL_CACHE_ENABLED:
            cached = url_cache.get_data_uri(url)
            if cached:
                debug(f"url_cache hit: {url}")
                return cached

        client = await http_client.get_client()
        debug(f"download: {url}")
        resp = await client.get(url, timeout=30, headers=auth_headers_for_url(url))
        debug(f"download status: {resp.status_code}")

        if resp.status_code != 200:
            print(f"[MCP] 下载失败 HTTP {resp.status_code}: {url}", file=sys.stderr)
            return None

        ct = resp.headers.get("content-type", "")
        mime, ext = guess_mime_and_ext(url, ct)
        if URL_CACHE_ENABLED:
            url_cache.put(url, resp.content, mime=mime, ext=ext)

        data = base64.b64encode(resp.content).decode()
        return f"data:{mime};base64,{data}"
    except Exception as exc:
        print(f"[MCP] 下载异常: {exc}", file=sys.stderr)
        return None


_cache_semaphore = asyncio.Semaphore(3)


async def cache_url_media(url: str) -> bool:
    """Download and cache a single URL."""
    if not URL_CACHE_ENABLED or url_cache.has(url):
        return url_cache.has(url)
    try:
        from .client import http_client

        client = await http_client.get_client()
        resp = await client.get(url, timeout=60, headers=auth_headers_for_url(url))
        if resp.status_code != 200:
            return False
        ct = resp.headers.get("content-type", "")
        mime, ext = guess_mime_and_ext(url, ct)
        if len(resp.content) > URL_CACHE_MAX_FILE_BYTES:
            debug(f"skip cache (too large): {len(resp.content)} bytes url={url}")
            return False
        return url_cache.put(url, resp.content, mime=mime, ext=ext)
    except Exception:
        return False


async def cache_urls(urls: list[str]) -> int:
    """Download and cache multiple URLs concurrently."""
    if not (URL_CACHE_ENABLED and urls):
        return 0

    async def _one(url: str) -> bool:
        async with _cache_semaphore:
            try:
                return await asyncio.wait_for(cache_url_media(url), timeout=90)
            except Exception:
                return False

    results = await asyncio.gather(*[_one(u) for u in urls], return_exceptions=True)
    return sum(1 for r in results if r is True)


# ---------------------------------------------------------------------------
# Local file import (Cherry Studio uploads)
# ---------------------------------------------------------------------------


async def import_local_file(value: str) -> tuple[Optional[str], Optional[str]]:
    """Import a local image file and return ``(data_uri, local_url)``."""
    s = str(value or "").strip()
    if s.lower().startswith(("http://", "https://")):
        raise ValueError("仅支持本地文件路径或 file:/// URI；不要传 http(s) 链接。")

    p = local_file_uri_to_path(value)
    if not p:
        return None, None

    if USER_IMAGE_DIR is None:
        raise ValueError("未启用用户图生图：请设置环境变量 FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR")
    if not is_under_root(p, USER_IMAGE_DIR):
        raise ValueError(f"本地文件不在允许目录下: {p}（允许目录: {USER_IMAGE_DIR}）")
    if not p.exists() or not p.is_file():
        raise ValueError("本地文件不存在或不可读")

    ext = p.suffix.lower().lstrip(".")
    mime = guess_mime_from_ext(ext)
    if not mime:
        raise ValueError("仅支持图片文件: png/jpg/jpeg/webp/gif/bmp/tif/tiff")

    raw = p.read_bytes()
    filename = store_local_media(raw, mime=mime, ext=ext)
    if not filename:
        raise ValueError("保存本地文件失败")

    base = ensure_cache_http_server()
    if base:
        local_url = f"{base}/mcp-cache/{filename}"
    else:
        local_url = f"http://127.0.0.1:{CACHE_HTTP_PORT}/mcp-cache/{filename}"

    data = base64.b64encode(raw).decode()
    data_uri = f"data:{mime};base64,{data}"
    return data_uri, local_url


def pick_user_image_paths(count: int = 1) -> list[Path]:
    """Return the *count* most-recently-modified images in the user upload directory."""
    if USER_IMAGE_DIR is None:
        raise ValueError("未启用用户图生图：请设置环境变量 FLOW2API_MCP_IMAGE_DIR")

    root = USER_IMAGE_DIR
    if not root.exists() or not root.is_dir():
        raise ValueError(f"用户图片目录不存在或不可读: {root}")

    allowed_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
    candidates: list[tuple[float, Path]] = []
    for p in root.iterdir():
        if not p.is_file() or p.suffix.lower() not in allowed_exts:
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
    return [p for _, p in candidates[:max(1, count)]]


# ---------------------------------------------------------------------------
# Cache HTTP server
# ---------------------------------------------------------------------------

_cache_httpd: Optional[http.server.ThreadingHTTPServer] = None
_cache_httpd_thread: Optional[threading.Thread] = None
_cache_http_base_url: Optional[str] = None


def ensure_cache_http_server() -> Optional[str]:
    """Start the built-in HTTP server for cache files (idempotent). Returns base URL."""
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
                filename = self.path[len("/mcp-cache/"):].split("?", 1)[0]
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
            return  # suppress access logs

    bind_host = os.environ.get("FLOW2API_MCP_HOST", "127.0.0.1")
    requested_port = max(0, min(int(CACHE_HTTP_PORT), 65535))
    try:
        httpd = http.server.ThreadingHTTPServer((bind_host, requested_port), CacheHandler)
    except OSError as exc:
        if requested_port > 0:
            print(f"[MCP] 端口 {requested_port} 被占用，回退随机端口: {exc}", file=sys.stderr)
            httpd = http.server.ThreadingHTTPServer((bind_host, 0), CacheHandler)
        else:
            print(f"[MCP] 缓存HTTP服务启动失败: {exc}", file=sys.stderr)
            return None

    port = httpd.server_address[1]

    external_prefix = os.environ.get("FLOW2API_MCP_EXTERNAL_URL_PREFIX", "").strip()
    if external_prefix:
        base_url = external_prefix.rstrip("/")
    else:
        base_url = f"http://127.0.0.1:{port}"

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    _cache_httpd = httpd
    _cache_httpd_thread = thread
    _cache_http_base_url = base_url

    print(f"[MCP] 缓存HTTP服务已启动: {base_url}/mcp-cache/...", file=sys.stderr)
    return base_url


# ---------------------------------------------------------------------------
# Cache URL helpers
# ---------------------------------------------------------------------------


def get_cached_local_url(url: str) -> Optional[str]:
    """Return the local ``/mcp-cache/`` URL for a cached upstream URL."""
    if not URL_CACHE_ENABLED or not url_cache.has(url):
        return None
    url_cache._load()
    meta = url_cache._index.get(normalize_cache_key(url)) or {}
    filename = meta.get("filename")
    if not filename and meta.get("path"):
        filename = Path(str(meta["path"])).name
    if not filename:
        return None
    base = ensure_cache_http_server()
    if not base:
        return None
    return f"{base}/mcp-cache/{filename}"


def is_local_cache_url(url: str) -> bool:
    """Check if *url* points to our local cache HTTP server."""
    s = str(url or "").strip()
    if not s:
        return False
    try:
        import urllib.parse

        parsed = urllib.parse.urlparse(s)
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        return host in ("127.0.0.1", "localhost") and path.startswith("/mcp-cache/")
    except Exception:
        return False


def replace_urls_with_cached(text: str, urls: list[str]) -> str:
    """Replace upstream URLs in *text* with local cache URLs where available."""
    if not text or not URL_CACHE_ENABLED:
        return text
    out = text
    for url in urls:
        if url not in out:
            continue
        local_url = get_cached_local_url(url)
        if local_url:
            out = out.replace(url, local_url)
    return out
