from __future__ import annotations

import importlib
from pathlib import Path


def test_config_runtime_files_live_under_repo_data_dir():
    import mcp_server.config as config_module

    config_module = importlib.reload(config_module)
    repo_root = Path(config_module.__file__).resolve().parent.parent
    data_dir = repo_root / "data"

    assert config_module.DATA_DIR == data_dir
    assert config_module.URL_CACHE_DIR == data_dir / "url_cache"
    assert config_module.URL_CACHE_INDEX_FILE == data_dir / "url_cache.json"
    assert config_module.HISTORY_FILE == data_dir / "history.json"
    assert config_module.HISTORY_ARCHIVE_FILE == data_dir / "history_archive.json"
