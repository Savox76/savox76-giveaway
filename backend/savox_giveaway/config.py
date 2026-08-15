from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from threading import RLock

from platformdirs import user_config_dir

APP_NAME = "Savox76Giveaway"
APP_AUTHOR = "Savox76"
DEFAULT_SERVER_PORT = 8766


@dataclass(slots=True)
class AppSettings:
    channel_login: str = "savox76"
    twitch_client_id: str = ""
    server_port: int = DEFAULT_SERVER_PORT
    twitch_redirect_uri: str = f"http://127.0.0.1:{DEFAULT_SERVER_PORT}/api/twitch/callback"
    github_owner: str = "Savox76"
    github_repo: str = "savox76-giveaway"
    auto_update: bool = True
    open_browser_on_start: bool = True

    def normalized(self) -> AppSettings:
        try:
            self.server_port = int(self.server_port)
        except (TypeError, ValueError):
            self.server_port = DEFAULT_SERVER_PORT
        if not 1024 <= self.server_port <= 65535:
            self.server_port = DEFAULT_SERVER_PORT
        self.channel_login = self.channel_login.strip().removeprefix("#").lower()[:25]
        self.twitch_client_id = self.twitch_client_id.strip()[:80]
        self.github_owner = self.github_owner.strip()[:100] or "Savox76"
        self.github_repo = self.github_repo.strip()[:100] or "savox76-giveaway"
        self.twitch_redirect_uri = f"http://127.0.0.1:{self.server_port}/api/twitch/callback"
        return self


def default_config_path() -> Path:
    override = os.environ.get("SAVOX76_CONFIG_DIR")
    base = Path(override) if override else Path(user_config_dir(APP_NAME, APP_AUTHOR))
    return base / "config.json"


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()
        self._lock = RLock()

    def load(self) -> AppSettings:
        with self._lock:
            if not self.path.exists():
                return AppSettings()
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                return AppSettings()
            allowed = {field.name for field in fields(AppSettings)}
            clean = {key: value for key, value in raw.items() if key in allowed}
            try:
                return AppSettings(**clean).normalized()
            except (TypeError, ValueError):
                return AppSettings()

    def save(self, settings: AppSettings) -> AppSettings:
        settings.normalized()
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix="config-", suffix=".json", dir=self.path.parent)
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump(asdict(settings), stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return settings
