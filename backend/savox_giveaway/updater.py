from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from packaging.version import InvalidVersion, Version

from scripts.error_report import GITHUB_OWNER, GITHUB_REPOSITORY

ARCHIVE_NAME = "Savox76Giveaway-python.zip"
MANIFEST_NAME = ".savox-update.json"
ENTRYPOINT_NAME = "Savox76Giveaway.py"
BLOCKED_PATH_PARTS = {".git", ".updates", ".venv", "__pycache__"}


@dataclass(slots=True, frozen=True)
class ReleaseAsset:
    name: str
    url: str
    size: int


@dataclass(slots=True, frozen=True)
class UpdateInfo:
    version: str
    name: str
    notes: str
    page_url: str
    asset: ReleaseAsset
    checksum_asset: ReleaseAsset


def release_asset_name() -> str:
    """Return the single, operating-system-independent release archive."""
    return ARCHIVE_NAME


def project_root() -> Path:
    override = os.environ.get("SAVOX76_APP_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def is_newer_version(candidate: str, current: str) -> bool:
    try:
        return Version(candidate.removeprefix("v")) > Version(current.removeprefix("v"))
    except InvalidVersion:
        return False


def _safe_relative_path(value: str) -> Path:
    normalized = value.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise RuntimeError("Das Updatepaket enthält einen ungültigen Dateipfad.")
    if any(part in BLOCKED_PATH_PARTS for part in pure.parts):
        raise RuntimeError("Das Updatepaket versucht einen geschützten Ordner zu verändern.")
    return Path(*pure.parts)


def extract_update_archive(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            relative = _safe_relative_path(member.filename.rstrip("/"))
            target = (root / relative).resolve()
            if not target.is_relative_to(root):
                raise RuntimeError("Das Updatepaket enthält einen ungültigen Dateipfad.")
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise RuntimeError("Symbolische Verknüpfungen sind in Updates nicht erlaubt.")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def validate_payload(payload_root: Path) -> dict[str, Any]:
    manifest_path = payload_root / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("Das Updatepaket enthält kein gültiges Manifest.") from exc
    if manifest.get("format") != 1 or manifest.get("entrypoint") != ENTRYPOINT_NAME:
        raise RuntimeError("Das Updatepaket besitzt ein unbekanntes Format.")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("Das Updatepaket enthält keine Programmdateien.")
    for name, expected in files.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise RuntimeError("Das Update-Manifest ist ungültig.")
        relative = _safe_relative_path(name)
        source = payload_root / relative
        if not source.is_file():
            raise RuntimeError(f"Die Update-Datei {name} fehlt.")
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != expected.lower():
            raise RuntimeError(f"Die Update-Datei {name} ist beschädigt.")
    if ENTRYPOINT_NAME not in files or "scripts/apply_update.py" not in files:
        raise RuntimeError("Das Updatepaket ist nicht startfähig.")
    return manifest


class GitHubUpdater:
    def __init__(self, current_version: str) -> None:
        self.owner = GITHUB_OWNER
        self.repo = GITHUB_REPOSITORY
        self.current_version = current_version

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def check(self) -> UpdateInfo | None:
        url = f"https://api.github.com/repos/{self.owner}/{self.repo}/releases/latest"
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(url, headers=self._headers())
            if response.status_code == 404:
                return None
            response.raise_for_status()
            release = response.json()
        version = str(release.get("tag_name", "")).removeprefix("v")
        if not is_newer_version(version, self.current_version):
            return None
        assets = {
            asset["name"]: ReleaseAsset(
                name=asset["name"],
                url=asset["browser_download_url"],
                size=int(asset.get("size", 0)),
            )
            for asset in release.get("assets", [])
            if asset.get("name") and asset.get("browser_download_url")
        }
        archive = assets.get(ARCHIVE_NAME)
        checksum = assets.get(f"{ARCHIVE_NAME}.sha256")
        if archive is None or checksum is None:
            return None
        return UpdateInfo(
            version=version,
            name=str(release.get("name") or release.get("tag_name") or version),
            notes=str(release.get("body") or ""),
            page_url=str(release.get("html_url") or ""),
            asset=archive,
            checksum_asset=checksum,
        )

    async def download_and_stage(self, update: UpdateInfo) -> Path:
        stage = Path(tempfile.mkdtemp(prefix="savox76-update-"))
        archive_path = stage / update.asset.name
        checksum_path = stage / update.checksum_asset.name
        try:
            async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
                await self._download(client, update.asset.url, archive_path)
                await self._download(client, update.checksum_asset.url, checksum_path)
            expected = checksum_path.read_text(encoding="utf-8").strip().split()[0].lower()
            if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
                raise RuntimeError("Die Prüfsumme des Updates ist ungültig.")
            actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            if expected != actual:
                raise RuntimeError("Das Update wurde wegen einer ungültigen Prüfsumme abgebrochen.")
            extract_dir = stage / "payload"
            extract_update_archive(archive_path, extract_dir)
            manifest = validate_payload(extract_dir)
            if str(manifest.get("version", "")) != update.version:
                raise RuntimeError("Release-Version und Updatepaket stimmen nicht überein.")
            return extract_dir
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise

    async def _download(self, client: httpx.AsyncClient, url: str, target: Path) -> None:
        async with client.stream("GET", url, headers=self._headers()) as response:
            response.raise_for_status()
            with target.open("wb") as stream:
                async for chunk in response.aiter_bytes():
                    stream.write(chunk)

    def launch_installer(self, staged_root: Path) -> None:
        manifest = validate_payload(staged_root)
        target = project_root()
        if not (target / ENTRYPOINT_NAME).is_file():
            raise RuntimeError("Der Python-Programmordner konnte nicht ermittelt werden.")
        helper = staged_root / "scripts" / "apply_update.py"
        base_python = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
        command = [
            str(base_python),
            str(helper),
            "--payload",
            str(staged_root),
            "--target",
            str(target),
            "--pid",
            str(os.getpid()),
            "--python",
            str(base_python),
            "--current-version",
            self.current_version,
            "--new-version",
            str(manifest["version"]),
        ]
        options: dict[str, Any] = {
            "cwd": str(target),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            options["start_new_session"] = True
        subprocess.Popen(command, **options)


async def exit_after_delay(delay: float = 0.8) -> None:
    await asyncio.sleep(delay)
    os._exit(0)


def update_to_dict(update: UpdateInfo | None) -> dict[str, Any]:
    if update is None:
        return {"available": False}
    return {
        "available": True,
        "version": update.version,
        "name": update.name,
        "notes": update.notes,
        "page_url": update.page_url,
        "asset_name": update.asset.name,
        "size": update.asset.size,
    }
