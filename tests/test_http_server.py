from __future__ import annotations

import importlib
import json

from starlette.testclient import TestClient


def _read_first_sse_message(body: str) -> dict[str, object]:
    for chunk in body.strip().split("\n\n"):
        data_lines = [line[5:].lstrip() for line in chunk.splitlines() if line.startswith("data:")]
        if data_lines:
            return json.loads("\n".join(data_lines))
    raise AssertionError(f"no SSE message found in response body: {body!r}")


def test_streamable_http_app_supports_initialize_and_tools_list():
    import mcp_server.server as server_module

    server_module = importlib.reload(server_module)
    app = server_module.create_streamable_http_app(path="/mcp")
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }

    with TestClient(app) as client:
        initialize_response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "pytest",
                        "version": "1.0.0",
                    },
                },
            },
        )

        assert initialize_response.status_code == 200
        session_id = initialize_response.headers["mcp-session-id"]
        initialize_payload = _read_first_sse_message(initialize_response.text)
        assert initialize_payload["id"] == 0

        protocol_version = initialize_payload["result"]["protocolVersion"]

        initialized_response = client.post(
            "/mcp",
            headers={
                **headers,
                "mcp-session-id": session_id,
                "mcp-protocol-version": protocol_version,
            },
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )

        assert initialized_response.status_code == 202

        tools_response = client.post(
            "/mcp",
            headers={
                **headers,
                "mcp-session-id": session_id,
                "mcp-protocol-version": protocol_version,
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
        )

        assert tools_response.status_code == 200
        tools_payload = _read_first_sse_message(tools_response.text)
        tool_names = {tool["name"] for tool in tools_payload["result"]["tools"]}
        assert {"generate", "history", "cache"} <= tool_names


def test_streamable_http_app_serves_cached_files():
    import mcp_server.server as server_module

    server_module = importlib.reload(server_module)
    filename = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg"
    file_path = server_module.URL_CACHE_DIR / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"test-image")

    try:
        app = server_module.create_streamable_http_app(path="/mcp")
        with TestClient(app) as client:
            response = client.get(f"/mcp-cache/{filename}")

        assert response.status_code == 200
        assert response.content == b"test-image"
    finally:
        if file_path.exists():
            file_path.unlink()


def test_cli_dispatches_streamable_http_transport_by_default(monkeypatch):
    import mcp_server.cli as cli_module

    cli_module = importlib.reload(cli_module)
    calls: dict[str, object] = {}

    monkeypatch.setattr(cli_module, "force_utf8_console", lambda: calls.setdefault("utf8", True))
    monkeypatch.setattr(cli_module, "load_project_env", lambda: calls.setdefault("env", True))
    monkeypatch.setattr(cli_module, "_sync_models", lambda: calls.setdefault("sync", True))
    monkeypatch.setattr(
        cli_module,
        "run_streamable_http",
        lambda **kwargs: calls.update(kwargs),
    )

    result = cli_module.main(
        [
            "--host",
            "0.0.0.0",
            "--port",
            "8866",
            "--path",
            "/mcp",
        ]
    )

    assert result == 0
    assert calls["host"] == "0.0.0.0"
    assert calls["port"] == 8866
    assert calls["path"] == "/mcp"
