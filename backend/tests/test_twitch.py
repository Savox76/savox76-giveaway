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


def test_status_contains_live_state(tmp_path):
    service = TwitchService(ConfigStore(tmp_path / "config.json"), MemorySecrets(), EventBus())

    assert service.status.as_dict()["live"] is False


@pytest.mark.asyncio
async def test_live_status_uses_twitch_streams_endpoint(tmp_path, monkeypatch):
    config = ConfigStore(tmp_path / "config.json")
    config.save(AppSettings(channel_login="savox76", twitch_client_id="public-client-id"))
    secrets = MemorySecrets()
    secrets.set("twitch_access_token", "access-token")
    service = TwitchService(config, secrets, EventBus())
    service._broadcaster_id = "12345"

    class FakeResponse:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"data": [{"id": "live-stream"}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, url, **kwargs):
            assert url.endswith("/streams")
            assert kwargs["params"] == {"user_id": "12345", "first": 1}
            return FakeResponse()

    monkeypatch.setattr("savox_giveaway.twitch.httpx.AsyncClient", lambda **_kwargs: FakeClient())

    await service._refresh_live_status()

    assert service.status.live is True


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


@pytest.mark.asyncio
async def test_twitch_chat_is_forwarded_to_the_python_game_handler(tmp_path):
    received = []

    async def handle_chat(sender, message):
        received.append((sender, message))

    service = TwitchService(
        ConfigStore(tmp_path / "config.json"),
        MemorySecrets(),
        EventBus(),
        chat_handler=handle_chat,
    )
    await service._handle_notification(
        {
            "payload": {
                "subscription": {"type": "channel.chat.message"},
                "event": {
                    "chatter_user_name": "Pilot",
                    "message": {"text": "!join"},
                    "message_id": "message-1",
                },
            }
        }
    )

    assert received == [("Pilot", "!join")]
