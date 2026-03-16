"""HTTP client and Flow2API streaming chat completions parser."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

import httpx

from .config import (
    HTTP_CONNECT_TIMEOUT,
    HTTP_TIMEOUT,
    MAX_CONNECTIONS,
    MAX_KEEPALIVE_CONNECTIONS,
    debug,
)


class HttpClient:
    """Lazy-initialized async HTTP client singleton."""

    def __init__(self) -> None:
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


async def stream_chat_completions(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
) -> tuple[int, str, str, str]:
    """Call ``/v1/chat/completions`` with ``stream=True`` and parse the SSE response.

    Returns ``(status_code, reasoning_text, content_text, error_text)``.
    """
    reasoning_text = ""
    content_text = ""
    counters: dict[str, int] = {
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

    # ---- inner helpers ----

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
                            counters["content_image_url_parts"] += 1
                            _append_url_line(url_val)

    def _add_debug_sample(choice0: dict, delta: dict, message: dict) -> None:
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
            ]
        except Exception:
            debug_sample = ["sample_failed"]

    def _append_images_field(value: Any, *, key: str) -> None:
        if value is None:
            return
        if isinstance(value, str) and value.strip():
            counters[key] += 1
            _append_url_line(value)
            return
        if isinstance(value, dict):
            url_val = value.get("url")
            if isinstance(url_val, str) and url_val.strip():
                counters[key] += 1
                _append_url_line(url_val)
                return
            image_url = value.get("image_url")
            if isinstance(image_url, dict):
                url_val2 = image_url.get("url")
                if isinstance(url_val2, str) and url_val2.strip():
                    counters[key] += 1
                    _append_url_line(url_val2)
                    return
            if isinstance(image_url, str) and image_url.strip():
                counters[key] += 1
                _append_url_line(image_url)
            return
        if isinstance(value, list):
            for img in value:
                if isinstance(img, dict):
                    url_val = img.get("url")
                    if isinstance(url_val, str) and url_val.strip():
                        counters[key] += 1
                        _append_url_line(url_val)
                        continue
                    image_url = img.get("image_url")
                    if isinstance(image_url, dict):
                        url_val2 = image_url.get("url")
                        if isinstance(url_val2, str) and url_val2.strip():
                            counters[key] += 1
                            _append_url_line(url_val2)
                            continue
                    if isinstance(image_url, str) and image_url.strip():
                        counters[key] += 1
                        _append_url_line(image_url)
                elif isinstance(img, str) and img.strip():
                    counters[key] += 1
                    _append_url_line(img)

    # ---- main request ----

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
                counters["events"] += 1
                if raw_chars < RAW_CAPTURE_LIMIT:
                    raw_lines.append(line)
                    raw_chars += len(line) + 1

                sse_payload: Optional[str] = None
                if line.startswith("data:"):
                    sse_payload = line[5:].lstrip()
                    if sse_payload == "[DONE]":
                        continue
                elif line.startswith("{"):
                    sse_payload = line

                if sse_payload is None:
                    continue

                try:
                    data = json.loads(sse_payload)
                except Exception:
                    continue
                counters["json"] += 1
                if not first_json_payload:
                    first_json_payload = sse_payload

                if isinstance(data, dict) and data.get("error"):
                    err = data.get("error") or {}
                    err_msg = str(err.get("message") or err)[:2000]
                    return 500, "", "", err_msg

                if not isinstance(data, dict):
                    continue

                choices = data.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                counters["choices"] += 1
                choice0 = choices[0] if isinstance(choices[0], dict) else {}

                delta = choice0.get("delta") if isinstance(choice0.get("delta"), dict) else {}
                message = choice0.get("message") if isinstance(choice0.get("message"), dict) else {}
                _add_debug_sample(choice0, delta, message)

                # reasoning
                reasoning_delta = delta.get("reasoning_content") or delta.get("reasoning") or ""
                if isinstance(reasoning_delta, str) and reasoning_delta:
                    reasoning_text += reasoning_delta
                reasoning_msg = message.get("reasoning_content") or message.get("reasoning") or ""
                if isinstance(reasoning_msg, str) and reasoning_msg:
                    reasoning_text += reasoning_msg

                # content
                if delta.get("content") is not None:
                    counters["delta_content"] += 1
                _append_content_value(delta.get("content"))
                if message.get("content") is not None:
                    counters["message_content"] += 1
                _append_content_value(message.get("content"))

                # images outside content
                _append_images_field(delta.get("images"), key="delta_images")
                _append_images_field(message.get("images"), key="message_images")
                _append_images_field(delta.get("image"), key="delta_images")
                _append_images_field(message.get("image"), key="message_images")

    except Exception as exc:
        return 0, "", "", str(exc)[:2000]

    # ---- post-processing ----

    err_text = ""
    if not content_text.strip():
        if raw_lines:
            try:
                debug_path = Path(__file__).resolve().parent / "upstream_debug_last.txt"
                debug_path.write_text("\n".join(raw_lines), encoding="utf-8", errors="ignore")
            except Exception:
                pass

        parts = ", ".join(f"{k}={v}" for k, v in counters.items() if v)
        sample = "; ".join(debug_sample) if debug_sample else ""
        payload_prefix = ""
        if first_json_payload:
            s = first_json_payload
            s = re.sub(r"(data:image/[a-zA-Z0-9.+-]+;base64,)[A-Za-z0-9+/=]+", r"\1<base64>", s)
            s = re.sub(r"(\"b64_json\"\\s*:\\s*\")([^\"]+)(\")", r"\1<base64>\3", s)
            s = re.sub(r"(\"url\"\\s*:\\s*\")([^\"]{120,})(\")", r"\1<omitted>\3", s)
            payload_prefix = s[:400].replace("\n", " ")

        detail_parts = [p for p in [parts, sample, f"payload_prefix={payload_prefix}" if payload_prefix else ""] if p]
        if detail_parts:
            debug("empty content extracted; " + " | ".join(detail_parts))

        err_text = "empty content extracted"

    return 200, reasoning_text, content_text, err_text
