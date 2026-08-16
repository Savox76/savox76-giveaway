from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any


class WinnerStatsStore:
    """Persistente, idempotente Alltime-Siegerstatistik."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    def record(self, name: str, record_id: str) -> dict[str, Any]:
        clean_name = name.strip().removeprefix("@")[:25]
        clean_record_id = record_id.strip()[:100]
        if not clean_name or not clean_record_id:
            raise ValueError("Name und Runden-ID dürfen nicht leer sein")

        with self._lock:
            data = self._load()
            key = clean_name.casefold()
            pilot = data["pilots"].get(
                key,
                {"name": clean_name, "wins": 0, "participations": 0, "last_win": ""},
            )
            pilot.setdefault("participations", 0)
            if clean_record_id not in data["records"]:
                pilot["wins"] = int(pilot.get("wins", 0)) + 1
                pilot["last_win"] = datetime.now(UTC).isoformat()
                data["records"].append(clean_record_id)
                data["records"] = data["records"][-5000:]
            pilot["name"] = clean_name
            data["pilots"][key] = pilot
            self._save(data)
            return dict(pilot)

    def record_participants(self, names: list[str], round_id: str) -> list[dict[str, Any]]:
        clean_round_id = round_id.strip()[:100]
        clean_names: list[str] = []
        seen_names: set[str] = set()
        for name in names:
            clean_name = name.strip().removeprefix("@")[:25]
            if clean_name and clean_name.casefold() not in seen_names:
                clean_names.append(clean_name)
                seen_names.add(clean_name.casefold())
        if not clean_round_id or not clean_names:
            raise ValueError("Teilnehmer und Runden-ID dürfen nicht leer sein")

        with self._lock:
            data = self._load()
            participation_records = data["participation_records"]
            recorded = set(participation_records)
            for clean_name in clean_names:
                key = clean_name.casefold()
                token = f"{clean_round_id}:{key}"
                pilot = data["pilots"].get(
                    key,
                    {"name": clean_name, "wins": 0, "participations": 0, "last_win": ""},
                )
                if token not in recorded:
                    pilot["participations"] = int(pilot.get("participations", 0)) + 1
                    recorded.add(token)
                    participation_records.append(token)
                pilot["name"] = clean_name
                data["pilots"][key] = pilot
            data["participation_records"] = participation_records[-20_000:]
            self._save(data)
            return [dict(data["pilots"][name.casefold()]) for name in clean_names]

    def lookup(self, name: str) -> dict[str, Any]:
        clean_name = name.strip().removeprefix("@")[:25]
        with self._lock:
            pilot = self._load()["pilots"].get(clean_name.casefold())
        if pilot is None:
            return {"name": clean_name, "wins": 0, "participations": 0, "last_win": ""}
        result = dict(pilot)
        result.setdefault("participations", 0)
        return result

    def leaders(self) -> list[dict[str, Any]]:
        with self._lock:
            pilots = [dict(entry) for entry in self._load()["pilots"].values()]
        return sorted(pilots, key=lambda entry: (-int(entry.get("wins", 0)), entry["name"].casefold()))

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 2, "pilots": {}, "records": [], "participation_records": []}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {"version": 2, "pilots": {}, "records": [], "participation_records": []}
        if not isinstance(raw, dict) or not isinstance(raw.get("pilots"), dict):
            return {"version": 2, "pilots": {}, "records": [], "participation_records": []}
        records = raw.get("records", [])
        raw["records"] = records if isinstance(records, list) else []
        participation_records = raw.get("participation_records", [])
        raw["participation_records"] = (
            participation_records if isinstance(participation_records, list) else []
        )
        for pilot in raw["pilots"].values():
            if isinstance(pilot, dict):
                pilot.setdefault("participations", 0)
        raw["version"] = 2
        return raw

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix="winner-stats-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
