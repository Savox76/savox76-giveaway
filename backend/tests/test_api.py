from fastapi.testclient import TestClient
from savox_giveaway.app import ApplicationState, create_app
from savox_giveaway.config import ConfigStore


class MemorySecrets:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name, "")

    def set(self, name, value):
        self.values[name] = value


def test_local_surfaces_and_status(tmp_path):
    state = ApplicationState(ConfigStore(tmp_path / "config.json"), MemorySecrets())
    client = TestClient(create_app(state))

    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["version"] == "0.2.4"
    assert status.json()["mode"] == "python"
    assert status.json()["twitch"]["connected"] is False

    control = client.get("/control")
    overlay = client.get("/overlay")
    favicon_svg = client.get("/favicon.svg")
    favicon_ico = client.get("/favicon.ico")
    assert control.status_code == 200
    assert overlay.status_code == 200
    assert favicon_svg.status_code == 200
    assert favicon_ico.status_code == 200
    assert favicon_svg.headers["content-type"].startswith("image/svg+xml")
    assert favicon_ico.headers["content-type"].startswith("image/svg+xml")
    assert "Savox76 Giveaway System" in control.text


def test_server_port_can_be_saved(tmp_path):
    state = ApplicationState(ConfigStore(tmp_path / "config.json"), MemorySecrets())
    client = TestClient(create_app(state))

    response = client.put("/api/settings", json={"server_port": 9010})

    assert response.status_code == 200
    assert response.json()["server_port"] == 9010
    assert response.json()["twitch_redirect_uri"] == "http://127.0.0.1:9010/api/twitch/callback"
