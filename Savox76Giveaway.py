from __future__ import annotations

import os
import subprocess
import sys
import tomllib
import venv
from pathlib import Path

MINIMUM_PYTHON = (3, 11)
ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        return str(tomllib.load(stream)["project"]["version"])


def environment_is_current(python: Path, version: str) -> bool:
    marker = VENV / ".savox-installed-version"
    if not python.is_file() or not marker.is_file():
        return False
    if marker.read_text(encoding="utf-8").strip() != version:
        return False
    check = subprocess.run(
        [str(python), "-c", "import fastapi, httpx, savox_giveaway, uvicorn"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return check.returncode == 0


def prepare_environment() -> Path:
    if sys.version_info < MINIMUM_PYTHON:
        required = ".".join(map(str, MINIMUM_PYTHON))
        raise RuntimeError(f"Python {required} oder neuer wird benötigt.")
    python = venv_python()
    version = project_version()
    if not python.is_file():
        print("Erstelle die lokale Python-Umgebung …", flush=True)
        venv.EnvBuilder(with_pip=True).create(VENV)
    if not environment_is_current(python, version):
        print(f"Richte Savox76 Giveaway v{version} ein …", flush=True)
        subprocess.check_call(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--upgrade",
                "-e",
                str(ROOT),
            ],
            cwd=ROOT,
        )
        (VENV / ".savox-installed-version").write_text(version + "\n", encoding="utf-8")
    return python


def main() -> None:
    python = prepare_environment()
    os.execv(str(python), [str(python), "-m", "savox_giveaway"])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nSavox76 Giveaway konnte nicht gestartet werden:\n{exc}", file=sys.stderr)
        if sys.platform == "win32" and sys.stdin.isatty():
            input("\nEnter drücken, um das Fenster zu schließen …")
        raise SystemExit(1) from exc
