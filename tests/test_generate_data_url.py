from __future__ import annotations

import asyncio
import importlib


def test_generate_handles_data_url_results_without_image_url_reference(monkeypatch):
    import mcp_server.config as config_module
    import mcp_server.tools as tools_module

    config_module = importlib.reload(config_module)
    tools_module = importlib.reload(tools_module)

    data_url = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0c8AAAAASUVORK5CYII="
    )

    async def fake_get_client():
        return object()

    async def fake_stream_chat_completions(client, *, base_url, api_key, model, messages):
        return 200, "", data_url, ""

    monkeypatch.setattr(tools_module.http_client, "get_client", fake_get_client)
    monkeypatch.setattr(tools_module, "stream_chat_completions", fake_stream_chat_completions)
    monkeypatch.setattr(tools_module.history_manager, "add_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(tools_module.history_manager, "add_failure", lambda *args, **kwargs: None)
    monkeypatch.setattr(tools_module, "store_local_media", lambda raw, mime, ext: "cached.png")
    monkeypatch.setattr(tools_module, "ensure_cache_http_server", lambda: "http://127.0.0.1:8866")

    result = asyncio.run(
        tools_module.handle_generate(
            {
                "model": config_module.DEFAULT_MODEL,
                "prompt": "base prompt",
            }
        )
    )

    assert result
    assert "http://127.0.0.1:8866/mcp-cache/cached.png" in result[0].text
