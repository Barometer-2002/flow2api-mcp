"""Flow2API MCP Server HTTP app and entry points."""

from __future__ import annotations

import os
import re

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import GetPromptResult, Prompt, PromptMessage, TextContent
from starlette.applications import Starlette
from starlette.responses import FileResponse, Response
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from .cache import URL_CACHE_DIR
from .tools import (
    PROMPTS,
    apply_prompt_template,
    get_tools,
    handle_cache,
    handle_generate,
    handle_history,
)

# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------

server = Server("flow2api-mcp")


@server.list_tools()
async def list_tools():
    """列出可用的工具"""
    return get_tools()


@server.call_tool()
async def call_tool(name: str, args: dict):
    """处理工具调用"""
    handlers = {
        "generate": handle_generate,
        "history": handle_history,
        "cache": handle_cache,
    }
    handler = handlers.get(name)
    if handler is None:
        return [TextContent(type="text", text=f"未知工具: {name}")]
    return await handler(args)


@server.list_prompts()
async def list_prompts():
    return [
        Prompt(
            name=name,
            title=data.get("title"),
            description=data.get("description"),
            arguments=data.get("arguments") or [],
        )
        for name, data in PROMPTS.items()
    ]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str] | None):
    data = PROMPTS.get(name)
    if not data:
        return GetPromptResult(
            description=f"Unknown prompt: {name}",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(type="text", text=f"Unknown prompt: {name}"),
                )
            ],
        )
    template = str(data.get("template") or "")
    text = apply_prompt_template(template, arguments)
    return GetPromptResult(
        description=str(data.get("description") or ""),
        messages=[PromptMessage(role="user", content=TextContent(type="text", text=text))],
    )


class _StreamableHTTPASGIApp:
    """Thin ASGI wrapper for the MCP streamable HTTP session manager."""

    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self.session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.session_manager.handle_request(scope, receive, send)


def create_streamable_http_app(path: str = "/mcp", cache_path: str = "/mcp-cache") -> Starlette:
    """Create a native Streamable HTTP MCP app with same-process cache file serving."""
    normalized_path = path if path.startswith("/") else f"/{path}"
    normalized_cache_path = cache_path if cache_path.startswith("/") else f"/{cache_path}"
    session_manager = StreamableHTTPSessionManager(app=server, stateless=False)
    mcp_app = _StreamableHTTPASGIApp(session_manager)
    cache_prefix = normalized_cache_path.rstrip("/")
    filename_pattern = re.compile(r"^[a-f0-9]{32}\.[a-z0-9]+$")

    async def serve_cache_file(request) -> Response:
        filename = str(request.path_params.get("filename") or "")
        if not filename_pattern.fullmatch(filename):
            return Response(status_code=400)
        file_path = URL_CACHE_DIR / filename
        if not file_path.exists() or not file_path.is_file():
            return Response(status_code=404)
        return FileResponse(
            file_path,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    return Starlette(
        routes=[
            Route(normalized_path, endpoint=mcp_app),
            Route(f"{cache_prefix}/{{filename}}", endpoint=serve_cache_file, methods=["GET"]),
        ],
        lifespan=lambda _app: session_manager.run(),
    )


def run_streamable_http(*, host: str = "127.0.0.1", port: int = 8866, path: str = "/mcp") -> None:
    """Run the MCP server as a native Streamable HTTP service."""
    import uvicorn

    os.environ["FLOW2API_MCP_SERVER_HOST"] = host
    os.environ["FLOW2API_MCP_SERVER_PORT"] = str(port)
    external_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    os.environ.setdefault("FLOW2API_MCP_EXTERNAL_URL_PREFIX", f"http://{external_host}:{port}")
    app = create_streamable_http_app(path=path)
    uvicorn.run(app, host=host, port=port, log_level="info")


def run() -> None:
    """Compatibility wrapper for external callers."""
    run_streamable_http()


if __name__ == "__main__":
    run()
