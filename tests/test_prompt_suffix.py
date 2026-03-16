from __future__ import annotations

import asyncio
import importlib


def test_generate_uses_custom_prompt_suffix_from_env(monkeypatch):
    monkeypatch.setenv("FLOW2API_MCP_PROMPT_SUFFIX", "\n\n[custom suffix]")

    import mcp_server.config as config_module
    import mcp_server.tools as tools_module

    config_module = importlib.reload(config_module)
    tools_module = importlib.reload(tools_module)

    captured: dict[str, object] = {}

    async def fake_get_client():
        return object()

    async def fake_stream_chat_completions(client, *, base_url, api_key, model, messages):
        captured["messages"] = messages
        return 200, "", "https://example.com/result.png", ""

    monkeypatch.setattr(tools_module.http_client, "get_client", fake_get_client)
    monkeypatch.setattr(tools_module, "stream_chat_completions", fake_stream_chat_completions)
    monkeypatch.setattr(tools_module.history_manager, "add_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(tools_module.history_manager, "add_failure", lambda *args, **kwargs: None)

    result = asyncio.run(
        tools_module.handle_generate(
            {
                "model": config_module.DEFAULT_MODEL,
                "prompt": "base prompt",
            }
        )
    )

    assert result
    assert captured["messages"] == [
        {
            "role": "user",
            "content": "base prompt\n\n[custom suffix]",
        }
    ]


def test_generate_allows_disabling_prompt_suffix_with_empty_env(monkeypatch):
    monkeypatch.setenv("FLOW2API_MCP_PROMPT_SUFFIX", "")

    import mcp_server.config as config_module
    import mcp_server.tools as tools_module

    config_module = importlib.reload(config_module)
    tools_module = importlib.reload(tools_module)

    captured: dict[str, object] = {}

    async def fake_get_client():
        return object()

    async def fake_stream_chat_completions(client, *, base_url, api_key, model, messages):
        captured["messages"] = messages
        return 200, "", "https://example.com/result.png", ""

    monkeypatch.setattr(tools_module.http_client, "get_client", fake_get_client)
    monkeypatch.setattr(tools_module, "stream_chat_completions", fake_stream_chat_completions)
    monkeypatch.setattr(tools_module.history_manager, "add_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(tools_module.history_manager, "add_failure", lambda *args, **kwargs: None)

    result = asyncio.run(
        tools_module.handle_generate(
            {
                "model": config_module.DEFAULT_MODEL,
                "prompt": "base prompt",
            }
        )
    )

    assert result
    assert captured["messages"] == [
        {
            "role": "user",
            "content": "base prompt",
        }
    ]
