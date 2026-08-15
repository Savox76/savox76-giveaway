from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from packaging.version import InvalidVersion, Version


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


def platform_slug() -> tuple[str, str]:
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x86_64"
    return system, architecture


def release_asset_name() -> str:
    system, architecture = platform_slug()
    return f"Savox76Giveaway-{system}-{architecture}.zip"


def is_newer_version(candidate: str, current: str) -> bool:
    try:
        return Version(candidate.removeprefix("v")) > Version(current.removeprefix("v"))
    except InvalidVersion:
        return False


class GitHubUpdater:
    def __init__(self, owner: str, repo: str, current_version: str, token: str = "") -> None:
        self.owner = owner
        self.repo = repo
        self.current_version = current_version
        self.token = token

    @property
    def frozen(self) -> bool:
        return bool(getattr(sys, "frozen", False))

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

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
        archive_name = release_asset_name()
        archive = assets.get(archive_name)
        checksum = assets.get(f"{archive_name}.sha256")
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
        if not self.frozen:
            raise RuntimeError("Selbstaktualisierung ist nur in der installierten Programmversion verfügbar.")
        stage = Path(tempfile.mkdtemp(prefix="savox76-update-"))
        archive_path = stage / update.asset.name
        checksum_path = stage / update.checksum_asset.name
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            await self._download(client, update.asset.url, archive_path)
            await self._download(client, update.checksum_asset.url, checksum_path)
        expected = checksum_path.read_text(encoding="utf-8").strip().split()[0].lower()
        digest = hashlib.sha256()
        with archive_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if expected != actual:
            shutil.rmtree(stage, ignore_errors=True)
            raise RuntimeError("Das Update wurde wegen einer ungültigen Prüfsumme abgebrochen.")
        extract_dir = stage / "payload"
        with zipfile.ZipFile(archive_path) as archive:
            destination = extract_dir.resolve()
            for member in archive.infolist():
                if not (destination / member.filename).resolve().is_relative_to(destination):
                    raise RuntimeError("Das Updatepaket enthält einen ungültigen Dateipfad.")
            archive.extractall(extract_dir)
        expected_name = "Savox76Giveaway.exe" if sys.platform == "win32" else "Savox76Giveaway"
        candidates = list(extract_dir.rglob(expected_name))
        if len(candidates) != 1:
            shutil.rmtree(stage, ignore_errors=True)
            raise RuntimeError("Das Updatepaket enthält keine eindeutige Programmdatei.")
        return candidates[0]

    async def _download(self, client: httpx.AsyncClient, url: str, target: Path) -> None:
        async with client.stream("GET", url, headers=self._headers()) as response:
            response.raise_for_status()
            with target.open("wb") as stream:
                async for chunk in response.aiter_bytes():
                    stream.write(chunk)

    def launch_installer(self, staged_binary: Path) -> None:
        target = Path(sys.executable).resolve()
        backup = target.with_suffix(target.suffix + ".previous")
        if sys.platform == "win32":
            helper = staged_binary.parent.parent / "install-update.cmd"
            helper.write_text(
                "@echo off\r\n"
                "timeout /t 2 /nobreak >nul\r\n"
                f'copy /Y "{target}" "{backup}" >nul\r\n'
                f'copy /Y "{staged_binary}" "{target}" >nul\r\n'
                f'start "" "{target}"\r\n',
                encoding="utf-8",
            )
            subprocess.Popen(["cmd", "/c", str(helper)], creationflags=subprocess.DETACHED_PROCESS)
        else:
            helper = staged_binary.parent.parent / "install-update.sh"
            helper.write_text(
                "#!/bin/sh\n"
                "sleep 2\n"
                f'cp "{target}" "{backup}"\n'
                f'cp "{staged_binary}" "{target}"\n'
                f'chmod +x "{target}"\n'
                f'nohup "{target}" >/dev/null 2>&1 &\n',
                encoding="utf-8",
            )
            helper.chmod(helper.stat().st_mode | stat.S_IXUSR)
            subprocess.Popen([str(helper)], start_new_session=True)


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
