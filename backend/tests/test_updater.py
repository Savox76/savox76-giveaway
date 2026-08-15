from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from savox_giveaway.updater import (
    ARCHIVE_NAME,
    extract_update_archive,
    is_newer_version,
    release_asset_name,
    validate_payload,
)

from scripts.apply_update import install_update


def test_semantic_version_comparison() -> None:
    assert is_newer_version("v0.2.0", "0.1.9")
    assert not is_newer_version("v0.1.0", "0.1.0")
    assert not is_newer_version("unbekannt", "0.1.0")


def test_release_asset_is_universal() -> None:
    assert release_asset_name() == ARCHIVE_NAME == "Savox76Giveaway-python.zip"


def test_extract_rejects_path_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "nicht erlaubt")
    with pytest.raises(RuntimeError, match="ungültigen Dateipfad"):
        extract_update_archive(archive_path, tmp_path / "payload")
    assert not (tmp_path / "outside.txt").exists()


def test_payload_verifies_every_file(tmp_path: Path) -> None:
    payload = tmp_path / "payload"
    helper = payload / "scripts" / "apply_update.py"
    helper.parent.mkdir(parents=True)
    launcher = payload / "Savox76Giveaway.py"
    launcher.write_text("print('start')\n", encoding="utf-8")
    helper.write_text("print('update')\n", encoding="utf-8")
    files = {
        "Savox76Giveaway.py": hashlib.sha256(launcher.read_bytes()).hexdigest(),
        "scripts/apply_update.py": hashlib.sha256(helper.read_bytes()).hexdigest(),
    }
    (payload / ".savox-update.json").write_text(
        json.dumps({"format": 1, "version": "0.2.0", "entrypoint": "Savox76Giveaway.py", "files": files}),
        encoding="utf-8",
    )
    assert validate_payload(payload)["version"] == "0.2.0"
    launcher.write_text("manipuliert\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="beschädigt"):
        validate_payload(payload)


def test_installer_backs_up_and_preserves_local_files(tmp_path: Path) -> None:
    target = tmp_path / "app"
    payload = tmp_path / "payload"
    (target / "scripts").mkdir(parents=True)
    (payload / "scripts").mkdir(parents=True)
    (target / "Savox76Giveaway.py").write_text("alte version\n", encoding="utf-8")
    (target / "obsolete.txt").write_text("wird entfernt\n", encoding="utf-8")
    (target / "meine-einstellung.txt").write_text("bleibt erhalten\n", encoding="utf-8")
    old_hashes = {
        "Savox76Giveaway.py": hashlib.sha256((target / "Savox76Giveaway.py").read_bytes()).hexdigest(),
        "obsolete.txt": hashlib.sha256((target / "obsolete.txt").read_bytes()).hexdigest(),
    }
    (target / ".savox-update.json").write_text(
        json.dumps(
            {"format": 1, "version": "0.1.0", "entrypoint": "Savox76Giveaway.py", "files": old_hashes}
        ),
        encoding="utf-8",
    )

    (payload / "Savox76Giveaway.py").write_text("neue version\n", encoding="utf-8")
    (payload / "scripts" / "apply_update.py").write_text("# helper\n", encoding="utf-8")
    new_hashes = {
        name: hashlib.sha256((payload / name).read_bytes()).hexdigest()
        for name in ("Savox76Giveaway.py", "scripts/apply_update.py")
    }
    (payload / ".savox-update.json").write_text(
        json.dumps(
            {"format": 1, "version": "0.2.0", "entrypoint": "Savox76Giveaway.py", "files": new_hashes}
        ),
        encoding="utf-8",
    )

    backup = install_update(payload, target, "0.1.0", "0.2.0")

    assert (target / "Savox76Giveaway.py").read_text(encoding="utf-8") == "neue version\n"
    assert not (target / "obsolete.txt").exists()
    assert (target / "meine-einstellung.txt").read_text(encoding="utf-8") == "bleibt erhalten\n"
    assert (backup / "Savox76Giveaway.py").read_text(encoding="utf-8") == "alte version\n"
    assert (backup / "obsolete.txt").is_file()
