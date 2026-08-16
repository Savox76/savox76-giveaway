from types import SimpleNamespace

import pytest
from savox_giveaway import __main__ as entrypoint
from savox_giveaway.config import AppSettings


@pytest.mark.asyncio
async def test_current_version_allows_browser_start(monkeypatch):
    class CurrentUpdater:
        def __init__(self, **_kwargs):
            pass

        async def check(self):
            return None

    monkeypatch.setattr(entrypoint, "GitHubUpdater", CurrentUpdater)

    assert await entrypoint.check_startup_update(AppSettings()) == "current"


@pytest.mark.asyncio
async def test_available_update_is_installed_before_server_start(monkeypatch, tmp_path):
    calls = []

    class PendingUpdater:
        def __init__(self, **_kwargs):
            pass

        async def check(self):
            return SimpleNamespace(version="9.9.9")

        async def download_and_stage(self, update):
            calls.append(("download", update.version))
            return tmp_path / "payload"

        def launch_installer(self, staged):
            calls.append(("install", staged))

    monkeypatch.setattr(entrypoint, "GitHubUpdater", PendingUpdater)

    assert await entrypoint.check_startup_update(AppSettings(auto_update=True)) == "updating"
    assert calls == [("download", "9.9.9"), ("install", tmp_path / "payload")]


@pytest.mark.asyncio
async def test_failed_version_check_suppresses_automatic_browser(monkeypatch):
    class FailingUpdater:
        def __init__(self, **_kwargs):
            pass

        async def check(self):
            raise RuntimeError("GitHub offline")

    monkeypatch.setattr(entrypoint, "GitHubUpdater", FailingUpdater)

    assert await entrypoint.check_startup_update(AppSettings()) == "unverified"
