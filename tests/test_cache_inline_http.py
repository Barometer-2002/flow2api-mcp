from __future__ import annotations

import importlib


def test_cache_http_uses_external_prefix(monkeypatch):
    monkeypatch.setenv("FLOW2API_MCP_URL_CACHE", "1")
    monkeypatch.setenv("FLOW2API_MCP_EXTERNAL_URL_PREFIX", "http://127.0.0.1:8866")

    import mcp_server.cache as cache_module

    cache_module = importlib.reload(cache_module)

    assert cache_module.ensure_cache_http_server() == "http://127.0.0.1:8866"


def test_cache_http_falls_back_to_server_host_and_port(monkeypatch):
    monkeypatch.setenv("FLOW2API_MCP_URL_CACHE", "1")
    monkeypatch.delenv("FLOW2API_MCP_EXTERNAL_URL_PREFIX", raising=False)
    monkeypatch.setenv("FLOW2API_MCP_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("FLOW2API_MCP_SERVER_PORT", "9000")

    import mcp_server.cache as cache_module

    cache_module = importlib.reload(cache_module)

    assert cache_module.ensure_cache_http_server() == "http://127.0.0.1:9000"
