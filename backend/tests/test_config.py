import json

from savox_giveaway.config import AppSettings, ConfigStore


def test_config_roundtrip_and_normalization(tmp_path):
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    saved = store.save(
        AppSettings(
            channel_login="#Savox76",
            twitch_client_id=" client-id ",
        )
    )
    assert saved.channel_login == "savox76"
    assert store.load().twitch_client_id == "client-id"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["auto_update"] is True
    assert stored["server_port"] == 8766
    assert "github_owner" not in stored
    assert "github_repo" not in stored


def test_redirect_uri_is_derived_from_server_port():
    settings = AppSettings(
        server_port=9010,
        twitch_redirect_uri="https://example.invalid/callback",
    ).normalized()
    assert settings.twitch_redirect_uri == "http://127.0.0.1:9010/api/twitch/callback"


def test_invalid_server_port_uses_default():
    settings = AppSettings(server_port=80).normalized()
    assert settings.server_port == 8766
    assert settings.twitch_redirect_uri == "http://127.0.0.1:8766/api/twitch/callback"


def test_unknown_config_fields_are_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"channel_login":"Test","unexpected":"ignored"}', encoding="utf-8")
    assert ConfigStore(path).load().channel_login == "test"


def test_old_editable_update_source_is_removed_when_config_is_saved(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"channel_login":"Test","github_owner":"Other","github_repo":"fork"}',
        encoding="utf-8",
    )

    store = ConfigStore(path)
    store.save(store.load())
    stored = json.loads(path.read_text(encoding="utf-8"))

    assert "github_owner" not in stored
    assert "github_repo" not in stored


def test_legacy_config_moves_to_new_default_port(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"channel_login":"Savox76","twitch_redirect_uri":"http://127.0.0.1:8765/api/twitch/callback"}',
        encoding="utf-8",
    )

    settings = ConfigStore(path).load()

    assert settings.server_port == 8766
    assert settings.twitch_redirect_uri == "http://127.0.0.1:8766/api/twitch/callback"
