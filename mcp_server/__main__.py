"""Module entrypoint for ``python -m mcp_server``."""

from __future__ import annotations

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
