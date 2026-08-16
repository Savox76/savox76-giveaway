from __future__ import annotations

import asyncio
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from typing import Literal

import uvicorn

from . import __version__
from .app import app
from .config import AppSettings, ConfigStore
from .updater import GitHubUpdater

StartupStatus = Literal["current", "updating", "manual", "unverified"]


async def check_startup_update(settings: AppSettings) -> StartupStatus:
    print(f"Prüfe GitHub-Version für v{__version__} …", flush=True)
    updater = GitHubUpdater(
        owner=settings.github_owner,
        repo=settings.github_repo,
        current_version=__version__,
    )
    try:
        update = await updater.check()
    except Exception as exc:
        print(
            f"Updateprüfung momentan nicht möglich: {str(exc)[:160]}\n"
            "Der Server startet, aber das Control-Fenster wird aus Sicherheitsgründen nicht "
            "automatisch geöffnet.",
            flush=True,
        )
        return "unverified"
    if update is None:
        print(f"Version v{__version__} ist aktuell.", flush=True)
        return "current"
    if not settings.auto_update:
        print(
            f"Version v{update.version} ist verfügbar, automatische Updates sind jedoch deaktiviert.",
            flush=True,
        )
        return "manual"
    try:
        print(f"Installiere zuerst Update v{update.version} …", flush=True)
        staged = await updater.download_and_stage(update)
        updater.launch_installer(staged)
    except Exception as exc:
        print(
            f"Update konnte nicht vorbereitet werden: {str(exc)[:160]}\n"
            "Der Server startet ohne automatisches Browserfenster.",
            flush=True,
        )
        return "unverified"
    print(
        "Update ist geprüft und vorbereitet. Das Tool startet danach automatisch in der neuen "
        "Version.",
        flush=True,
    )
    return "updating"


def open_control_when_ready(base_url: str, timeout_seconds: float = 45) -> None:
    status_url = f"{base_url}/api/status"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(status_url, timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(f"{base_url}/control")
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    print(
        "Der Server wurde nicht rechtzeitig bereit. Das Control-Fenster wurde nicht automatisch "
        "geöffnet.",
        flush=True,
    )


def main() -> None:
    settings = ConfigStore().load()
    startup_status = asyncio.run(check_startup_update(settings))
    if startup_status == "updating":
        return
    base_url = f"http://127.0.0.1:{settings.server_port}"
    print("Savox76 Giveaway System")
    print(f"Steuerung: {base_url}/control")
    print(f"Theme-Steuerung: {base_url}/themes")
    print(f"OBS-Overlay: {base_url}/overlay")
    print("Zum Beenden Strg+C drücken.\n", flush=True)
    if settings.open_browser_on_start and startup_status in {"current", "manual"}:
        threading.Thread(
            target=open_control_when_ready,
            args=(base_url,),
            name="control-browser-start",
            daemon=True,
        ).start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=settings.server_port, log_level="info")
    except SystemExit as exc:
        if exc.code:
            print(
                f"\nDer Server konnte Port {settings.server_port} nicht öffnen. "
                "Möglicherweise wird dieser Port bereits verwendet.",
                flush=True,
            )
        raise


if __name__ == "__main__":
    main()
