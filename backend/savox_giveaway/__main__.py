from __future__ import annotations

import threading
import webbrowser

import uvicorn

from .app import app
from .config import ConfigStore


def main() -> None:
    settings = ConfigStore().load()
    if settings.open_browser_on_start:
        threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:8765/control")).start()
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
