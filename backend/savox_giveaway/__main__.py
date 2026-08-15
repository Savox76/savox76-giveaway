from __future__ import annotations

import threading
import webbrowser

import uvicorn

from .app import app
from .config import ConfigStore


def main() -> None:
    settings = ConfigStore().load()
    base_url = f"http://127.0.0.1:{settings.server_port}"
    print("Savox76 Giveaway System")
    print(f"Steuerung: {base_url}/control")
    print(f"OBS-Overlay: {base_url}/overlay")
    print("Zum Beenden Strg+C drücken.\n", flush=True)
    if settings.open_browser_on_start:
        threading.Timer(1.2, lambda: webbrowser.open(f"{base_url}/control")).start()
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
