from __future__ import annotations

import keyring
from keyring.errors import KeyringError

SERVICE = "Savox76Giveaway"
KNOWN_KEYS = {"twitch_client_secret", "twitch_access_token", "twitch_refresh_token", "github_token"}


class SecretStore:
    def get(self, name: str) -> str:
        self._validate(name)
        try:
            return keyring.get_password(SERVICE, name) or ""
        except KeyringError:
            return ""

    def set(self, name: str, value: str) -> None:
        self._validate(name)
        try:
            if value:
                keyring.set_password(SERVICE, name, value)
            else:
                keyring.delete_password(SERVICE, name)
        except KeyringError as exc:
            raise RuntimeError(
                "Der sichere Schlüsselspeicher des Betriebssystems ist nicht verfügbar."
            ) from exc

    @staticmethod
    def _validate(name: str) -> None:
        if name not in KNOWN_KEYS:
            raise ValueError(f"Unbekannter Schlüssel: {name}")
