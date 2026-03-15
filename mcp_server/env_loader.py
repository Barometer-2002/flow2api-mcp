"""Minimal .env loader for local development and desktop clients."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _candidate_env_files() -> list[Path]:
    override = (os.environ.get("FLOW2API_MCP_ENV_FILE") or "").strip()
    if override:
        return [Path(override).expanduser()]

    candidates: list[Path] = []
    for path in (Path.cwd() / ".env", PROJECT_ROOT / ".env"):
        if path not in candidates:
            candidates.append(path)
    return candidates


def _parse_env_line(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[7:].lstrip()
    if "=" not in line:
        return None

    key, value = line.split("=", 1)
    key = key.strip()
    if not key:
        return None

    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def load_project_env() -> Path | None:
    """Load .env values without overwriting existing process environment."""
    for env_file in _candidate_env_files():
        if not env_file.is_file():
            continue
        for raw_line in env_file.read_text(encoding="utf-8-sig").splitlines():
            parsed = _parse_env_line(raw_line)
            if parsed is None:
                continue
            key, value = parsed
            os.environ.setdefault(key, value)
        return env_file
    return None
