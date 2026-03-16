"""CLI entry points for Flow2API MCP server."""

from __future__ import annotations

import argparse
import os
from typing import Sequence

from .console_encoding import force_utf8_console
from .env_loader import load_project_env
from .server import run_streamable_http


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Flow2API MCP server")
    parser.add_argument(
        "--host",
        default=os.environ.get("FLOW2API_MCP_SERVER_HOST", "127.0.0.1"),
        help="MCP HTTP 监听地址。",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("FLOW2API_MCP_SERVER_PORT", "8866")),
        help="MCP HTTP 监听端口。",
    )
    parser.add_argument(
        "--path",
        default=os.environ.get("FLOW2API_MCP_SERVER_PATH", "/mcp"),
        help="MCP HTTP 路径。",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    force_utf8_console()
    load_project_env()
    args = parse_args(argv)
    run_streamable_http(host=args.host, port=args.port, path=args.path)

    return 0
