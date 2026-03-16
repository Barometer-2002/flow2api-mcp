from __future__ import annotations

import asyncio
import importlib


def test_history_manager_treats_empty_files_as_empty_history(tmp_path, monkeypatch, capsys):
    import mcp_server.history as history_module

    history_module = importlib.reload(history_module)
    history_file = tmp_path / "history.json"
    archive_file = tmp_path / "history_archive.json"
    history_file.write_text("", encoding="utf-8")
    archive_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(history_module, "HISTORY_FILE", history_file)
    monkeypatch.setattr(history_module, "HISTORY_ARCHIVE_FILE", archive_file)

    manager = history_module.HistoryManager()
    captured = capsys.readouterr()

    assert manager.sizes() == {"recent": 0, "archive": 0}
    assert captured.err == ""


def test_handle_history_ignores_zero_history_id_placeholder(monkeypatch):
    import mcp_server.tools as tools_module

    tools_module = importlib.reload(tools_module)

    monkeypatch.setattr(tools_module.history_manager, "is_empty", lambda scope="recent": False)
    monkeypatch.setattr(tools_module.history_manager, "sizes", lambda: {"recent": 1, "archive": 1})
    monkeypatch.setattr(
        tools_module.history_manager,
        "get_archive",
        lambda limit=20: [
            {
                "id": 12,
                "time": "2026-03-16 12:00:00",
                "model": "gemini-3.1-flash-image-landscape",
                "prompt": "test prompt",
                "urls": ["http://127.0.0.1:8866/mcp-cache/example.jpg"],
                "error": None,
            }
        ],
    )
    monkeypatch.setattr(
        tools_module.history_manager,
        "get_recent",
        lambda limit=5: [],
    )
    monkeypatch.setattr(
        tools_module.history_manager,
        "get_by_id",
        lambda item_id, scope="archive": None,
    )

    result = asyncio.run(
        tools_module.handle_history(
            {
                "history_id": 0,
                "limit": 10,
                "scope": "archive",
            }
        )
    )

    assert result
    assert "# 生成历史（archive）" in result[0].text
    assert "未找到该 history_id: 0" not in result[0].text


def test_history_manager_creates_parent_dir_when_saving(tmp_path, monkeypatch):
    import mcp_server.history as history_module

    history_module = importlib.reload(history_module)
    history_file = tmp_path / "data" / "history.json"
    archive_file = tmp_path / "data" / "history_archive.json"

    monkeypatch.setattr(history_module, "HISTORY_FILE", history_file)
    monkeypatch.setattr(history_module, "HISTORY_ARCHIVE_FILE", archive_file)

    manager = history_module.HistoryManager()
    manager.add_success("gemini-3.1-flash-image-landscape", "test prompt", ["http://example.com/a.jpg"])

    assert history_file.exists()
    assert archive_file.exists()
