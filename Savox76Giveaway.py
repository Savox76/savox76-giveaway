from __future__ import annotations

import subprocess
import sys
import tomllib
import traceback
import venv
from datetime import UTC, datetime
from pathlib import Path

MINIMUM_PYTHON = (3, 11)
ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
LOG_FILE = ROOT / "Savox76Giveaway.log"
REQUIRED_FILES = (
    "pyproject.toml",
    "backend/savox_giveaway/__main__.py",
    "frontend/dist/index.html",
    "scripts/apply_update.py",
)


def write_log(message: str) -> None:
    try:
        with LOG_FILE.open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now(UTC).isoformat()} {message.rstrip()}\n")
    except OSError:
        pass


def validate_installation(root: Path = ROOT) -> None:
    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(
            "Programmdateien fehlen. Bitte das heruntergeladene ZIP zuerst vollständig in einen "
            f"eigenen Ordner entpacken und dort Savox76Giveaway.py starten. Fehlend: {names}"
        )


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
    validate_installation()
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


def run_server(python: Path) -> int:
    print("Starte den lokalen Giveaway-Server …", flush=True)
    print("Dieses Terminal bitte geöffnet lassen, solange das Tool benutzt wird.\n", flush=True)
    try:
        result = subprocess.run(
            [str(python), "-m", "savox_giveaway"],
            cwd=ROOT,
            check=False,
        )
    except KeyboardInterrupt:
        print("\nSavox76 Giveaway wurde beendet.", flush=True)
        return 0
    return result.returncode


def pause_after_error() -> None:
    if sys.platform != "win32":
        return
    try:
        input("\nDas Terminal bleibt zur Fehleranzeige geöffnet. Enter drücken zum Schließen …")
    except (EOFError, KeyboardInterrupt):
        pass


def main() -> int:
    python = prepare_environment()
    exit_code = run_server(python)
    if exit_code:
        raise RuntimeError(
            f"Der lokale Server wurde mit Fehlercode {exit_code} beendet. "
            f"Weitere Hinweise stehen in {LOG_FILE.name}."
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        details = traceback.format_exc()
        write_log(details)
        print(f"\nSavox76 Giveaway konnte nicht gestartet werden:\n{exc}", file=sys.stderr)
        print(f"Fehlerprotokoll: {LOG_FILE}", file=sys.stderr)
        pause_after_error()
        raise SystemExit(1) from exc
