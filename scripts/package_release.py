from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
import zipfile
from pathlib import Path

ARCHIVE_NAME = "Savox76Giveaway-python.zip"
MANIFEST_NAME = ".savox-update.json"
ENTRYPOINT_NAME = "Savox76Giveaway.py"
FILES = (
    "Savox76Giveaway.py",
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "SECURITY.md",
    "scripts/apply_update.py",
)
DIRECTORIES = (
    "backend/savox_giveaway",
    "frontend/dist",
    "docs",
)


def collect_files(root: Path) -> list[Path]:
    selected: list[Path] = []
    for name in FILES:
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(f"Release-Datei fehlt: {name}")
        selected.append(path)
    for name in DIRECTORIES:
        directory = root / name
        if not directory.is_dir():
            raise FileNotFoundError(f"Release-Ordner fehlt: {name}")
        selected.extend(
            path
            for path in directory.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        )
    return sorted(set(selected), key=lambda path: path.relative_to(root).as_posix())


def build_release(root: Path, output: Path) -> tuple[Path, Path]:
    root = root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with (root / "pyproject.toml").open("rb") as stream:
        version = str(tomllib.load(stream)["project"]["version"])
    files = collect_files(root)
    hashes = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    manifest = {
        "format": 1,
        "version": version,
        "entrypoint": ENTRYPOINT_NAME,
        "files": hashes,
    }
    archive = output / ARCHIVE_NAME
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in files:
            bundle.write(path, path.relative_to(root).as_posix())
        bundle.writestr(
            MANIFEST_NAME,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return archive, checksum


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=Path.cwd(), type=Path)
    parser.add_argument("--output", default="release-artifacts", type=Path)
    args = parser.parse_args()
    build_release(args.root, args.output)


if __name__ == "__main__":
    main()
