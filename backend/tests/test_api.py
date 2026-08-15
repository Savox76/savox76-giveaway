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
    assert status.json()["version"] == "0.2.0"
    assert status.json()["mode"] == "python"
    assert status.json()["twitch"]["connected"] is False

    control = client.get("/control")
    overlay = client.get("/overlay")
    assert control.status_code == 200
    assert overlay.status_code == 200
    assert "Savox76 Giveaway System" in control.text
