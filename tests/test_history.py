from __future__ import annotations

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
