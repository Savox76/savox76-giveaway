from pathlib import Path

import pytest

import Savox76Giveaway as launcher


def test_installation_validation_accepts_complete_layout(tmp_path: Path) -> None:
    for name in launcher.REQUIRED_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test\n", encoding="utf-8")

    launcher.validate_installation(tmp_path)


def test_installation_validation_explains_incomplete_zip(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="ZIP zuerst vollständig"):
        launcher.validate_installation(tmp_path)


def test_server_exit_code_is_returned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class Result:
        returncode = 17

    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher.subprocess, "run", lambda *args, **kwargs: Result())

    assert launcher.run_server(tmp_path / "python") == 17
