from __future__ import annotations

import importlib
import os


def test_load_project_env_reads_dotenv_from_current_workdir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FLOW2API_BASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        "FLOW2API_BASE_URL=http://dotenv.example:18000\n",
        encoding="utf-8",
    )

    import mcp_server.env_loader as env_loader

    env_loader = importlib.reload(env_loader)
    loaded = env_loader.load_project_env()

    assert loaded == tmp_path / ".env"
    assert os.environ["FLOW2API_BASE_URL"] == "http://dotenv.example:18000"


def test_load_project_env_keeps_existing_environment_value(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FLOW2API_BASE_URL", "http://process.example:28000")
    (tmp_path / ".env").write_text(
        "FLOW2API_BASE_URL=http://dotenv.example:18000\n",
        encoding="utf-8",
    )

    import mcp_server.env_loader as env_loader

    env_loader = importlib.reload(env_loader)
    env_loader.load_project_env()

    assert os.environ["FLOW2API_BASE_URL"] == "http://process.example:28000"


def test_config_uses_dotenv_values(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FLOW2API_BASE_URL", raising=False)
    monkeypatch.delenv("FLOW2API_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "FLOW2API_BASE_URL=http://dotenv.example:18000\n"
        "FLOW2API_API_KEY=dotenv-key\n",
        encoding="utf-8",
    )

    import mcp_server.env_loader as env_loader
    import mcp_server.config as config_module

    env_loader = importlib.reload(env_loader)
    config_module = importlib.reload(config_module)

    assert config_module.get_base_url() == "http://dotenv.example:18000"
    assert config_module.get_api_key() == "dotenv-key"
