from __future__ import annotations

import asyncio
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from typing import Literal

import uvicorn

from scripts.error_report import ErrorReportStore, open_issue_report

from . import __version__
from .app import app
from .config import AppSettings, ConfigStore
from .updater import GitHubUpdater, project_root

StartupStatus = Literal["current", "updating", "manual", "unverified"]


async def check_startup_update(settings: AppSettings) -> StartupStatus:
    print(f"Prüfe GitHub-Version für v{__version__} …", flush=True)
    updater = GitHubUpdater(current_version=__version__)
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
            raise SystemExit(98) from exc
        raise


def report_server_failure(exc: BaseException, component: str) -> None:
    root = project_root()
    store = ErrorReportStore(root / ".updates" / "error-reports", root, __version__)
    report = store.capture_exception(
        exc,
        component,
        context={"Startphase": "Lokaler Python-Server", "Server-Port": ConfigStore().load().server_port},
    )
    print(
        f"Vorausgefüllter GitHub-Fehlerbericht: {report.issue_url}\n"
        f"Lokale Diagnose: {root / '.updates' / 'error-reports' / report.report_file}",
        flush=True,
    )
    open_issue_report(report)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code and exc.code != 98:
            report_server_failure(exc, "Serverstart")
        raise
    except Exception as exc:
        report_server_failure(exc, "Serverprozess")
        raise
