from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

MANIFEST_NAME = ".savox-update.json"
ENTRYPOINT_NAME = "Savox76Giveaway.py"
BLOCKED_PARTS = {".git", ".updates", ".venv", "__pycache__"}


def safe_path(root: Path, value: str) -> Path:
    pure = PurePosixPath(value.replace("\\", "/"))
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise RuntimeError(f"Ungültiger Updatepfad: {value}")
    if any(part in BLOCKED_PARTS for part in pure.parts):
        raise RuntimeError(f"Geschützter Updatepfad: {value}")
    result = (root / Path(*pure.parts)).resolve()
    if not result.is_relative_to(root.resolve()):
        raise RuntimeError(f"Updatepfad außerhalb des Programmordners: {value}")
    return result


def load_manifest(root: Path, required: bool = True) -> dict[str, object]:
    path = root / MANIFEST_NAME
    if not path.exists() and not required:
        return {"files": {}}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("Update-Manifest kann nicht gelesen werden.") from exc
    if manifest.get("format") != 1 or not isinstance(manifest.get("files"), dict):
        raise RuntimeError("Update-Manifest besitzt ein unbekanntes Format.")
    return manifest


def verify_payload(payload: Path, manifest: dict[str, object]) -> dict[str, str]:
    raw_files = manifest["files"]
    if not isinstance(raw_files, dict) or not raw_files:
        raise RuntimeError("Das Update enthält keine Dateien.")
    files: dict[str, str] = {}
    for name, expected in raw_files.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise RuntimeError("Ungültiger Eintrag im Update-Manifest.")
        source = safe_path(payload, name)
        if not source.is_file():
            raise RuntimeError(f"Update-Datei fehlt: {name}")
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != expected.lower():
            raise RuntimeError(f"Update-Datei ist beschädigt: {name}")
        files[name] = expected.lower()
    if ENTRYPOINT_NAME not in files:
        raise RuntimeError("Der Python-Starter fehlt im Update.")
    return files


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_for_process(pid: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while process_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.25)
    if process_exists(pid):
        raise RuntimeError("Das laufende Programm wurde nicht rechtzeitig beendet.")


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.savox-new")
    shutil.copy2(source, temporary)
    for attempt in range(20):
        try:
            os.replace(temporary, target)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.25)


def backup_files(target: Path, backup: Path, names: set[str]) -> set[str]:
    existing: set[str] = set()
    for name in sorted(names):
        source = target / MANIFEST_NAME if name == MANIFEST_NAME else safe_path(target, name)
        if source.is_file():
            destination = backup / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            existing.add(name)
    return existing


def restore_backup(target: Path, backup: Path, affected: set[str], existing: set[str]) -> None:
    for name in sorted(affected):
        destination = target / MANIFEST_NAME if name == MANIFEST_NAME else safe_path(target, name)
        if name in existing:
            source = backup / name
            if source.is_file():
                atomic_copy(source, destination)
        elif destination.is_file():
            destination.unlink()


def remove_empty_parents(path: Path, stop: Path) -> None:
    parent = path.parent
    while parent != stop and parent.is_relative_to(stop):
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def prune_backups(backups_root: Path, keep: int = 3) -> None:
    backups = sorted((path for path in backups_root.iterdir() if path.is_dir()), reverse=True)
    for obsolete in backups[keep:]:
        shutil.rmtree(obsolete, ignore_errors=True)


def install_update(
    payload: Path,
    target: Path,
    current_version: str,
    new_version: str,
) -> Path:
    payload = payload.resolve()
    target = target.resolve()
    manifest = load_manifest(payload)
    if str(manifest.get("version", "")) != new_version:
        raise RuntimeError("Die erwartete Updateversion stimmt nicht mit dem Paket überein.")
    new_files = verify_payload(payload, manifest)
    old_manifest = load_manifest(target, required=False)
    old_files_raw = old_manifest.get("files", {})
    old_files = set(old_files_raw) if isinstance(old_files_raw, dict) else set()
    affected = old_files | set(new_files) | {MANIFEST_NAME}

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backups_root = target / ".updates" / "backups"
    backup = backups_root / f"{timestamp}-v{current_version}"
    backup.mkdir(parents=True, exist_ok=False)
    existing = backup_files(target, backup, affected)

    try:
        for name in sorted(new_files):
            atomic_copy(safe_path(payload, name), safe_path(target, name))
        for name in sorted(old_files - set(new_files)):
            obsolete = safe_path(target, name)
            if obsolete.is_file():
                obsolete.unlink()
                remove_empty_parents(obsolete, target)
        atomic_copy(payload / MANIFEST_NAME, target / MANIFEST_NAME)
        status = {
            "from": current_version,
            "to": new_version,
            "installed_at": datetime.now(UTC).isoformat(),
            "backup": str(backup),
        }
        status_path = target / ".updates" / "last-update.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        restore_backup(target, backup, affected, existing)
        raise
    prune_backups(backups_root)
    return backup


def restart(python: Path, target: Path) -> None:
    command = [str(python), str(target / ENTRYPOINT_NAME)]
    options: dict[str, object] = {"cwd": str(target), "close_fds": True}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NEW_CONSOLE
    else:
        options["start_new_session"] = True
        options["stdout"] = subprocess.DEVNULL
        options["stderr"] = subprocess.DEVNULL
    subprocess.Popen(command, **options)


def write_log(target: Path, message: str) -> None:
    log = target / ".updates" / "update.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(f"{datetime.now(UTC).isoformat()} {message}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--current-version", required=True)
    parser.add_argument("--new-version", required=True)
    args = parser.parse_args()

    try:
        wait_for_process(args.pid)
        backup = install_update(
            args.payload,
            args.target,
            args.current_version,
            args.new_version,
        )
        write_log(args.target, f"Update v{args.current_version} -> v{args.new_version}; Sicherung: {backup}")
        restart(args.python, args.target)
        shutil.rmtree(args.payload.parent, ignore_errors=True)
    except Exception as exc:
        write_log(args.target, f"Update fehlgeschlagen: {exc}")
        raise


if __name__ == "__main__":
    main()
