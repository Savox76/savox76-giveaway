from __future__ import annotations

import threading
import webbrowser

import uvicorn

from .app import app
from .config import ConfigStore


def main() -> None:
    settings = ConfigStore().load()
    base_url = f"http://127.0.0.1:{settings.server_port}"
    if settings.open_browser_on_start:
        threading.Timer(1.2, lambda: webbrowser.open(f"{base_url}/control")).start()
    uvicorn.run(app, host="127.0.0.1", port=settings.server_port, log_level="info")


if __name__ == "__main__":
    main()
