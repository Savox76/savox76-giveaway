import pytest
from savox_giveaway.config import AppSettings, ConfigStore
from savox_giveaway.events import EventBus
from savox_giveaway.twitch import TwitchService


class MemorySecrets:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name, "")

    def set(self, name, value):
        self.values[name] = value


def test_public_client_is_configured_without_secret(tmp_path):
    config = ConfigStore(tmp_path / "config.json")
    config.save(AppSettings(channel_login="savox76", twitch_client_id="public-client-id"))

    service = TwitchService(config, MemorySecrets(), EventBus())

    assert service.status.configured is True
    assert service.status.authenticated is False
    assert service.status.message == "Twitch-Anmeldung erforderlich"


def test_device_verification_url_receives_public_code():
    url = TwitchService._verification_url("https://www.twitch.tv/activate", "ABCDEFGH")

    assert url == "https://www.twitch.tv/activate?public=true&device-code=ABCDEFGH"


@pytest.mark.asyncio
async def test_device_login_needs_only_client_id(tmp_path, monkeypatch):
    config = ConfigStore(tmp_path / "config.json")
    config.save(AppSettings(channel_login="savox76", twitch_client_id="public-client-id"))
    service = TwitchService(config, MemorySecrets(), EventBus())

    class FakeResponse:
        is_error = False

        @staticmethod
        def json():
            return {
                "device_code": "device-code",
                "user_code": "ABCDEFGH",
                "verification_uri": "https://www.twitch.tv/activate",
                "expires_in": 1800,
                "interval": 5,
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    async def fake_poll(self, _device_code, _expires_in, _interval):
        return None

    monkeypatch.setattr("savox_giveaway.twitch.httpx.AsyncClient", lambda **_kwargs: FakeClient())
    monkeypatch.setattr(TwitchService, "_poll_device_authorization", fake_poll)

    url = await service.start_device_authorization()
    await service._device_task

    assert url == "https://www.twitch.tv/activate?public=true&device-code=ABCDEFGH"
    assert service.status.message.endswith("Code ABCDEFGH")
