"""Cross-session generation history management."""

from __future__ import annotations

import json
import sys
from collections import deque
from datetime import datetime
from typing import Any, Optional

from .config import (
    HISTORY_ARCHIVE_FILE,
    HISTORY_FILE,
    MAX_HISTORY_ARCHIVE_SIZE,
    MAX_HISTORY_RECENT_SIZE,
    debug,
)
from .utils import is_likely_image_url


class HistoryManager:
    """Manages recent + archive generation history with stable incremental IDs."""

    def __init__(self) -> None:
        self._recent: deque[dict[str, Any]] = deque(maxlen=MAX_HISTORY_RECENT_SIZE)
        self._archive: deque[dict[str, Any]] = deque(maxlen=MAX_HISTORY_ARCHIVE_SIZE)
        self._next_id: int = 1
        self._load_history()

    # ---- ID migration ----

    def _ensure_ids(self) -> None:
        max_id = 0
        for item in list(self._archive) + list(self._recent):
            try:
                v = int(item.get("id") or 0)
            except Exception:
                v = 0
            if v > max_id:
                max_id = v

        archive_list = list(self._archive)
        has_any_id = any(isinstance(x.get("id"), int) and x.get("id") for x in archive_list)

        if archive_list:
            if not has_any_id:
                next_id = 1
                for item in archive_list:
                    item["id"] = next_id
                    next_id += 1
                max_id = next_id - 1
            else:
                next_id = max_id + 1
                for item in archive_list:
                    if not isinstance(item.get("id"), int) or int(item.get("id") or 0) <= 0:
                        item["id"] = next_id
                        next_id += 1
                max_id = next_id - 1

            self._archive = deque(archive_list, maxlen=MAX_HISTORY_ARCHIVE_SIZE)
            self._recent = deque(archive_list[-MAX_HISTORY_RECENT_SIZE:], maxlen=MAX_HISTORY_RECENT_SIZE)

        self._next_id = max_id + 1 if max_id > 0 else 1

    # ---- persistence ----

    def _load_history(self) -> None:
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._recent = deque(data, maxlen=MAX_HISTORY_RECENT_SIZE)
                debug(f"history loaded: recent={len(self._recent)}")
            except Exception as exc:
                print(f"[MCP] 加载历史记录失败: {exc}", file=sys.stderr)
                self._recent = deque(maxlen=MAX_HISTORY_RECENT_SIZE)

        if HISTORY_ARCHIVE_FILE.exists():
            try:
                with open(HISTORY_ARCHIVE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._archive = deque(data, maxlen=MAX_HISTORY_ARCHIVE_SIZE)
                debug(f"history loaded: archive={len(self._archive)}")
            except Exception as exc:
                print(f"[MCP] 加载历史归档失败: {exc}", file=sys.stderr)
                self._archive = deque(maxlen=MAX_HISTORY_ARCHIVE_SIZE)
        else:
            if self._recent:
                self._archive = deque(list(self._recent), maxlen=MAX_HISTORY_ARCHIVE_SIZE)
                self._save_history()

        self._ensure_ids()

    def _save_history(self) -> None:
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(list(self._recent), f, ensure_ascii=False, indent=2)
            with open(HISTORY_ARCHIVE_FILE, "w", encoding="utf-8") as f:
                json.dump(list(self._archive), f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[MCP] 保存历史记录失败: {exc}", file=sys.stderr)

    # ---- mutations ----

    def add_success(self, model: str, prompt: str, urls: list[str]) -> None:
        item = {
            "id": self._next_id,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": model,
            "prompt": prompt,
            "urls": urls,
            "error": None,
        }
        self._next_id += 1
        self._recent.append(item)
        self._archive.append(item)
        self._save_history()

    def add_failure(self, model: str, prompt: str, error: str) -> None:
        item = {
            "id": self._next_id,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": model,
            "prompt": prompt,
            "urls": [],
            "error": error,
        }
        self._next_id += 1
        self._recent.append(item)
        self._archive.append(item)
        self._save_history()

    # ---- queries ----

    def get_recent(self, limit: int = 5) -> list[dict[str, Any]]:
        limit = min(int(limit), MAX_HISTORY_RECENT_SIZE)
        return list(self._recent)[-limit:][::-1]

    def get_archive(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = min(int(limit), MAX_HISTORY_ARCHIVE_SIZE)
        return list(self._archive)[-limit:][::-1]

    def get_by_id(self, item_id: int, scope: str = "archive") -> Optional[dict[str, Any]]:
        try:
            target = int(item_id)
        except Exception:
            return None
        if target <= 0:
            return None
        history_list = list(self._archive) if scope == "archive" else list(self._recent)
        for item in reversed(history_list):
            if int(item.get("id") or 0) == target:
                return item
        return None

    def is_empty(self, scope: str = "recent") -> bool:
        if scope == "archive":
            return len(self._archive) == 0
        return len(self._recent) == 0

    def sizes(self) -> dict[str, int]:
        return {"recent": len(self._recent), "archive": len(self._archive)}

    # ---- cleanup ----

    def prune_to(self, keep: int) -> dict[str, int]:
        keep = max(0, int(keep))
        before = self.sizes()
        if keep == 0:
            self._recent.clear()
            self._archive.clear()
        else:
            if len(self._recent) > keep:
                self._recent = deque(list(self._recent)[-keep:], maxlen=MAX_HISTORY_RECENT_SIZE)
            if len(self._archive) > keep:
                self._archive = deque(list(self._archive)[-keep:], maxlen=MAX_HISTORY_ARCHIVE_SIZE)
        self._save_history()
        after = self.sizes()
        return {
            "recent_removed": before["recent"] - after["recent"],
            "archive_removed": before["archive"] - after["archive"],
        }

    def clear_all(self) -> dict[str, int]:
        before = self.sizes()
        self._recent.clear()
        self._archive.clear()
        self._save_history()
        return {"recent_removed": before["recent"], "archive_removed": before["archive"]}

    def get_latest_success_image_item(self, scope: str = "archive") -> Optional[dict[str, Any]]:
        history_list = list(self._archive) if scope == "archive" else list(self._recent)
        for item in reversed(history_list):
            if item.get("error"):
                continue
            urls = list(item.get("urls", []) or [])
            if any(is_likely_image_url(u) for u in urls):
                return item
        return None


history_manager = HistoryManager()
