"""Flow2API MCP Server — MCP registration and entry point.

This module wires up the MCP protocol handlers (tools, prompts) and provides
the ``main()`` / ``run()`` entry points.
"""

from __future__ import annotations

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import GetPromptResult, Prompt, PromptMessage, TextContent

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


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


async def main():
    """启动 MCP 服务器（stdio 传输）"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def run() -> None:
    """Console script entrypoint."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
