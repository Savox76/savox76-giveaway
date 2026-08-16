from fastapi.testclient import TestClient
from savox_giveaway.app import ApplicationState, create_app
from savox_giveaway.config import ConfigStore
from savox_giveaway.twitch import TwitchService


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
    assert status.json()["version"] == "0.2.10"
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


def test_twitch_login_uses_device_authorization(tmp_path, monkeypatch):
    state = ApplicationState(ConfigStore(tmp_path / "config.json"), MemorySecrets())
    client = TestClient(create_app(state))

    async def fake_device_authorization(self):
        return "https://www.twitch.tv/activate?public=true&device-code=ABCDEFGH"

    monkeypatch.setattr(TwitchService, "start_device_authorization", fake_device_authorization)
    response = client.get("/api/twitch/login", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].endswith("device-code=ABCDEFGH")


def test_winner_stats_endpoint_is_idempotent(tmp_path):
    state = ApplicationState(ConfigStore(tmp_path / "config.json"), MemorySecrets())
    client = TestClient(create_app(state))

    first = client.post("/api/stats/winner", json={"name": "Pilot", "record_id": "round-1"})
    duplicate = client.post("/api/stats/winner", json={"name": "Pilot", "record_id": "round-1"})

    assert first.json()["wins"] == 1
    assert duplicate.json()["wins"] == 1
    assert client.get("/api/stats/winners").json()[0]["name"] == "Pilot"
    participants = client.post(
        "/api/stats/participants",
        json={"names": ["Pilot", "Wingman"], "round_id": "round-1"},
    )
    assert participants.status_code == 200
    assert client.get("/api/stats/winner", params={"name": "pilot"}).json()["participations"] == 1


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
        "updatedAt": 1_786_819_200_000,
        "activeRoundId": None,
        "battleStartedAt": None,
        "testMode": False,
    }

    with client.websocket_connect("/ws/events") as control:
        control.receive_json()
        control.receive_json()
        control.receive_json()
        assert control.receive_json() == {"type": "arena.restore", "payload": {"state": None}}
        control.send_json({"type": "arena.state", "payload": arena_state})
        forwarded = control.receive_json()
        assert forwarded == {"type": "arena.state", "payload": arena_state}

    with client.websocket_connect("/ws/events") as overlay:
        overlay.receive_json()
        overlay.receive_json()
        overlay.receive_json()
        assert overlay.receive_json() == {
            "type": "arena.restore",
            "payload": {"state": arena_state},
        }

    restored = ApplicationState(ConfigStore(tmp_path / "config.json"), MemorySecrets())
    assert restored.arena_state == arena_state


def test_overlay_connection_status_is_broadcast(tmp_path):
    state = ApplicationState(ConfigStore(tmp_path / "config.json"), MemorySecrets())
    client = TestClient(create_app(state))

    with client.websocket_connect("/ws/events") as control:
        for _ in range(4):
            control.receive_json()
        control.send_json({"type": "client.hello", "payload": {"origin": "control", "role": "control"}})
        with client.websocket_connect("/ws/events") as overlay:
            for _ in range(4):
                overlay.receive_json()
            overlay.send_json({"type": "client.hello", "payload": {"origin": "overlay", "role": "overlay"}})
            connected = control.receive_json()
            assert connected == {"type": "overlay.status", "payload": {"connected": True, "count": 1}}
        disconnected = control.receive_json()
        assert disconnected == {
            "type": "overlay.status",
            "payload": {"connected": False, "count": 0},
        }
