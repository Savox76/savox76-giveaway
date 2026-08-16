import asyncio

import pytest
from savox_giveaway.arena_state import ArenaStateStore
from savox_giveaway.events import EventBus
from savox_giveaway.game import CLASS_STATS, ArenaGame
from savox_giveaway.stats import WinnerStatsStore


@pytest.mark.asyncio
async def test_gameplay_and_claim_continue_without_a_browser(tmp_path, monkeypatch):
    sent_messages = []

    async def send_chat(message):
        sent_messages.append(message)

    game = ArenaGame(
        ArenaStateStore(tmp_path / "arena.json"),
        WinnerStatsStore(tmp_path / "stats.json"),
        EventBus(),
        send_chat,
    )
    monkeypatch.setitem(CLASS_STATS["frigate"], "damage", (200.0, 200.0))
    monkeypatch.setitem(CLASS_STATS["frigate"], "dodge", 0.0)

    await game.start_giveaway()
    await game.handle_chat("PilotOne", "!join")
    await game.handle_chat("PilotTwo", "!join")
    await game.update_presentation({"frigateFireRate": 0.2})
    await game.start_battle()

    async def wait_for_winner():
        while game.state["phase"] != "winner":
            await asyncio.sleep(0.05)

    await asyncio.wait_for(wait_for_winner(), timeout=5)
    winner = game.state["winner"]["name"]
    assert game.state["claimStatus"] == "pending"

    await game.handle_chat(winner, "Ich bin da!")

    assert game.state["claimStatus"] == "claimed"
    assert any("Anmeldung ist geschlossen" in message for message in sent_messages)
    assert any("erfolgreich geclaimt" in message for message in sent_messages)
    await game.stop()


@pytest.mark.asyncio
async def test_chat_join_works_without_connected_control_page(tmp_path):
    async def send_chat(_message):
        return None

    game = ArenaGame(
        ArenaStateStore(tmp_path / "arena.json"),
        WinnerStatsStore(tmp_path / "stats.json"),
        EventBus(),
        send_chat,
    )

    await game.start_giveaway()
    await game.handle_chat("BackgroundPilot", "!join")

    assert [pilot["name"] for pilot in game.state["combatants"]] == ["BackgroundPilot"]
