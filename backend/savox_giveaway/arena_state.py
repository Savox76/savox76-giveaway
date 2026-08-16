from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any


class ArenaStateStore:
    """Speichert den letzten gültigen Giveaway-Zustand atomar."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    def load(self) -> dict[str, Any] | None:
        with self._lock:
            if not self.path.exists():
                return None
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                return None
            return raw if isinstance(raw, dict) else None

    def save(self, state: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix="arena-state-", suffix=".json", dir=self.path.parent)
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump(state, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
