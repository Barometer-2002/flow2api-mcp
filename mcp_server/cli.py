"""CLI entry points for Flow2API MCP server."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Sequence

from .console_encoding import force_utf8_console
from .env_loader import load_project_env
from .server import run_streamable_http


def _sync_models() -> None:
    """启动时自动从上游同步图片模型列表到 models.json。"""
    base_url = os.environ.get("FLOW2API_BASE_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("FLOW2API_API_KEY", "")
    models_path = Path(__file__).parent / "models.json"

    try:
        req = urllib.request.Request(
            f"{base_url}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        all_models = [m["id"] for m in data.get("data", [])]
        image_models = [m for m in all_models if "image" in m or "imagen" in m]

        if not image_models:
            print("[MCP] 模型同步: 未找到图片模型，跳过", file=sys.stderr)
            return

        if models_path.exists():
            with open(models_path, encoding="utf-8") as f:
                mcp_data = json.load(f)
        else:
            mcp_data = {}

        old_models = mcp_data.get("models", [])
        mcp_data["models"] = image_models

        if mcp_data.get("default_model") not in image_models:
            mcp_data["default_model"] = image_models[0]

        with open(models_path, "w", encoding="utf-8") as f:
            json.dump(mcp_data, f, indent=2, ensure_ascii=False)

        added = set(image_models) - set(old_models)
        removed = set(old_models) - set(image_models)
        parts = [f"{len(image_models)} 个"]
        if added:
            parts.append(f"新增 {len(added)}")
        if removed:
            parts.append(f"移除 {len(removed)}")
        print(f"[MCP] 图片模型同步完成: {', '.join(parts)}", file=sys.stderr)
    except Exception as exc:
        print(f"[MCP] 模型同步失败（不影响启动）: {exc}", file=sys.stderr)


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
    _sync_models()
    run_streamable_http(host=args.host, port=args.port, path=args.path)

    return 0
