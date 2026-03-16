from __future__ import annotations

import asyncio
import importlib


def test_cache_does_not_treat_string_false_as_confirmed_history_delete(monkeypatch):
    import mcp_server.tools as tools_module

    tools_module = importlib.reload(tools_module)

    monkeypatch.setattr(tools_module.url_cache, "size", lambda: 3)
    monkeypatch.setattr(tools_module.history_manager, "sizes", lambda: {"recent": 2, "archive": 5})

    result = asyncio.run(
        tools_module.handle_cache(
            {
                "action": "clear",
                "include_history": "false",
                "confirm": "false",
            }
        )
    )

    assert result
    assert "history_recent_removed: 0" in result[0].text
    assert "history_archive_removed: 0" in result[0].text
