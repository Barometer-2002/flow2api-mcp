"""Helpers for keeping console text encoding stable across platforms."""

from __future__ import annotations

import sys


def _reconfigure_stream(stream) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")


def force_utf8_console() -> None:
    """Force UTF-8 text streams so console logs do not mojibake."""
    _reconfigure_stream(sys.stdout)
    _reconfigure_stream(sys.stderr)
