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
    assert status.json()["version"] == "0.2.7"
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


def test_winner_stats_endpoint_is_idempotent(tmp_path):
    state = ApplicationState(ConfigStore(tmp_path / "config.json"), MemorySecrets())
    client = TestClient(create_app(state))

    first = client.post("/api/stats/winner", json={"name": "Pilot", "record_id": "round-1"})
    duplicate = client.post("/api/stats/winner", json={"name": "Pilot", "record_id": "round-1"})

    assert first.json()["wins"] == 1
    assert duplicate.json()["wins"] == 1
    assert client.get("/api/stats/winners").json()[0]["name"] == "Pilot"


def test_arena_state_is_forwarded_to_overlay_clients(tmp_path):
    state = ApplicationState(ConfigStore(tmp_path / "config.json"), MemorySecrets())
    client = TestClient(create_app(state))
    arena_state = {
        "origin": "control-test",
        "phase": "registration",
        "combatants": [
            {
                "id": "pilot-1",
                "name": "Pilot",
                "shipClass": "frigate",
                "hp": 100,
                "maxHp": 100,
                "alive": True,
                "kills": 0,
            }
        ],
        "battleId": 4,
        "round": 2,
        "countdown": 3,
        "winner": None,
        "winnerAllTimeWins": 0,
        "claimStatus": "none",
        "claimSeconds": 60,
        "logs": [{"time": "12:34", "message": "Test geladen"}],
        "arenaTitle": "VOID ARENA",
        "joinCommand": "!join",
        "shipScale": 0.65,
        "frigateFireRate": 1.55,
        "cruiserFireRate": 2.35,
        "soundOn": True,
    }

    with client.websocket_connect("/ws/events") as control:
        control.receive_json()
        control.receive_json()
        control.send_json({"type": "arena.state", "payload": arena_state})
        forwarded = control.receive_json()
        assert forwarded == {"type": "arena.state", "payload": arena_state}

    with client.websocket_connect("/ws/events") as overlay:
        overlay.receive_json()
        overlay.receive_json()
        assert overlay.receive_json() == {"type": "arena.state", "payload": arena_state}
