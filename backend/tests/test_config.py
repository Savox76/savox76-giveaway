import json

from savox_giveaway.config import AppSettings, ConfigStore


def test_config_roundtrip_and_normalization(tmp_path):
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    saved = store.save(
        AppSettings(
            channel_login="#Savox76",
            twitch_client_id=" client-id ",
            github_owner="Savox76",
            github_repo="savox76-giveaway",
        )
    )
    assert saved.channel_login == "savox76"
    assert store.load().twitch_client_id == "client-id"
    assert json.loads(path.read_text(encoding="utf-8"))["auto_update"] is True


def test_invalid_redirect_uri_is_replaced():
    settings = AppSettings(twitch_redirect_uri="https://example.invalid/callback").normalized()
    assert settings.twitch_redirect_uri == "http://127.0.0.1:8765/api/twitch/callback"


def test_unknown_config_fields_are_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"channel_login":"Test","unexpected":"ignored"}', encoding="utf-8")
    assert ConfigStore(path).load().channel_login == "test"
