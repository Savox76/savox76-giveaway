from __future__ import annotations

import asyncio
import contextlib
import copy
import secrets
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from .arena_state import ArenaStateStore
from .events import EventBus
from .stats import WinnerStatsStore

THEME_IDS = {"standard", "easter", "christmas", "halloween", "anniversary"}
CLASS_STATS = {
    "frigate": {"hp": 100.0, "damage": (8.0, 12.0), "dodge": 0.34},
    "cruiser": {"hp": 180.0, "damage": (25.0, 32.0), "dodge": 0.06},
}
DEFAULT_FIRE_RATES = {"frigate": 1.55, "cruiser": 2.35}


class ArenaGame:
    """Authoritative Giveaway-Engine, die unabhängig von Browser und OBS läuft."""

    def __init__(
        self,
        store: ArenaStateStore,
        stats: WinnerStatsStore,
        events: EventBus,
        send_chat: Callable[[str], Awaitable[None]],
        initial_state: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.stats = stats
        self.events = events
        self.send_chat = send_chat
        self._random = secrets.SystemRandom()
        self._phase_task: asyncio.Task[None] | None = None
        self._chat_cooldowns: dict[str, float] = {}
        self._last_save = 0.0
        self._state = self._normalize_state(initial_state)

    @property
    def state(self) -> dict[str, Any]:
        return copy.deepcopy(self._state)

    async def start(self) -> None:
        phase = self._state["phase"]
        elapsed = max(0, int((self._now_ms() - int(self._state.get("updatedAt", 0))) / 1000))
        if phase == "countdown":
            remaining = max(0, int(self._state.get("countdown", 3)) - elapsed)
            self._phase_task = asyncio.create_task(
                self._countdown_and_battle(remaining, announce=False), name="arena-countdown"
            )
        elif phase == "battle":
            self._phase_task = asyncio.create_task(self._combat_loop(), name="arena-combat")
        elif phase == "winner" and self._state.get("claimStatus") == "pending":
            self._state["claimSeconds"] = max(0, int(self._state.get("claimSeconds", 60)) - elapsed)
            self._phase_task = asyncio.create_task(self._claim_loop(), name="arena-claim")
        await self._publish_state(force_save=True)

    async def stop(self) -> None:
        await self._cancel_phase_task()
        await asyncio.to_thread(self.store.save, self.state)

    async def start_giveaway(self) -> dict[str, Any]:
        await self._cancel_phase_task()
        presentation = self._presentation()
        current_round = max(1, int(self._state.get("round", 1)))
        current_battle = max(0, int(self._state.get("battleId", 0)))
        self._state = self._default_state()
        self._state.update(presentation)
        self._state.update(round=current_round, battleId=current_battle)
        self._state["phase"] = "registration"
        self._add_log("Giveaway gestartet – Anmeldung offen")
        await self._publish_state(force_save=True)
        await self._announce(
            f"Giveaway gestartet! Schreibe {self._state['joinCommand']}, um teilzunehmen."
        )
        return self.state

    async def load_test_fleet(self, count: int) -> dict[str, Any]:
        if count not in {12, 24, 48}:
            raise ValueError("Testflotte muss 12, 24 oder 48 Piloten enthalten")
        await self._cancel_phase_task()
        names = [
            "Voidrider",
            "NovaFox",
            "IronWolf",
            "Starling",
            "Orbital",
            "Nebula",
            "Valkyrie",
            "PixelPilot",
            "DarkMatter",
            "AstroByte",
            "Moonshot",
            "Raven",
        ]
        names.extend(f"TestPilot_{index:02d}" for index in range(13, count + 1))
        self._state["combatants"] = self._balance_fleet(names[:count])
        self._state.update(
            phase="registration",
            winner=None,
            winnerAllTimeWins=0,
            claimStatus="none",
            claimSeconds=60,
            activeRoundId=None,
            battleStartedAt=None,
            testMode=True,
        )
        self._add_log(f"Test-Giveaway mit {count} Piloten geladen")
        await self._publish_state(force_save=True)
        await self._local_chat(f"Test-Giveaway gestartet: {count} Teilnehmer sind angemeldet.")
        return self.state

    async def join(self, raw_name: str, announce: bool = True) -> dict[str, Any]:
        clean = self._clean_name(raw_name)
        if not clean:
            raise ValueError("Teilnehmername fehlt")
        if self._state["phase"] != "registration":
            if announce:
                await self._announce(f"@{clean}, die Anmeldung ist bereits geschlossen.")
            return self.state
        names = [entry["name"] for entry in self._state["combatants"]]
        if any(name.casefold() == clean.casefold() for name in names):
            if announce:
                await self._announce(f"@{clean}, du bist bereits für dieses Giveaway angemeldet.")
            return self.state
        self._state["combatants"] = self._balance_fleet([*names, clean])
        self._add_log(f"{clean} tritt dem Giveaway bei")
        await self._publish_state(force_save=True)
        if announce:
            await self._announce(f"@{clean}, du nimmst am Giveaway teil. Viel Glück!")
        return self.state

    async def remove_participant(self, participant_id: str) -> dict[str, Any]:
        if self._state["phase"] != "registration":
            return self.state
        names = [
            entry["name"]
            for entry in self._state["combatants"]
            if entry["id"] != participant_id
        ]
        self._state["combatants"] = self._balance_fleet(names)
        await self._publish_state(force_save=True)
        return self.state

    async def leave(self, raw_name: str, announce: bool = True) -> dict[str, Any]:
        clean = self._clean_name(raw_name)
        if self._state["phase"] != "registration":
            return self.state
        before = len(self._state["combatants"])
        names = [
            entry["name"]
            for entry in self._state["combatants"]
            if entry["name"].casefold() != clean.casefold()
        ]
        if len(names) == before:
            await self._reply(f"@{clean}, du bist aktuell nicht angemeldet.", not announce)
            return self.state
        self._state["combatants"] = self._balance_fleet(names)
        self._add_log(f"{clean} verlässt das Giveaway")
        await self._publish_state(force_save=True)
        await self._reply(f"@{clean}, deine Anmeldung wurde zurückgenommen.", not announce)
        return self.state

    async def start_battle(self) -> dict[str, Any]:
        if self._state["phase"] != "registration" or len(self._state["combatants"]) < 2:
            raise ValueError("Für den Kampf werden mindestens zwei angemeldete Piloten benötigt")
        await self._prepare_round(rematch=False)
        return self.state

    async def start_rematch(self) -> dict[str, Any]:
        if self._state["phase"] != "winner" or self._state["claimStatus"] != "expired":
            raise ValueError("Ein Rematch ist erst nach abgelaufener Claim-Zeit möglich")
        if len(self._state["combatants"]) < 2:
            raise ValueError("Für ein Rematch werden mindestens zwei Piloten benötigt")
        await self._cancel_phase_task()
        self._state["round"] = int(self._state["round"]) + 1
        await self._prepare_round(rematch=True)
        return self.state

    async def end_giveaway(self) -> dict[str, Any]:
        await self._cancel_phase_task()
        presentation = self._presentation()
        next_round = int(self._state.get("round", 1)) + 1
        next_battle = int(self._state.get("battleId", 0)) + 1
        self._state = self._default_state()
        self._state.update(presentation, round=next_round, battleId=next_battle)
        self._add_log("Giveaway beendet")
        await self._publish_state(force_save=True)
        await self._announce("Derzeit ist kein Giveaway aktiv.")
        return self.state

    async def update_presentation(self, values: dict[str, Any]) -> dict[str, Any]:
        if "arenaTitle" in values:
            self._state["arenaTitle"] = str(values["arenaTitle"]).strip()[:28] or "VOID ARENA"
        if "joinCommand" in values:
            bare = "".join(char for char in str(values["joinCommand"]) if char.isalnum() or char == "_")
            self._state["joinCommand"] = f"!{bare.lstrip('!')[:18].lower() or 'join'}"
        if "shipScale" in values:
            self._state["shipScale"] = min(1.0, max(0.45, float(values["shipScale"])))
        if "soundOn" in values:
            self._state["soundOn"] = bool(values["soundOn"])
        if "themeId" in values:
            theme_id = str(values["themeId"]).lower()
            if theme_id not in THEME_IDS:
                raise ValueError("Unbekanntes Event-Theme")
            self._state["themeId"] = theme_id
        if self._state["phase"] not in {"countdown", "battle"}:
            if "frigateFireRate" in values:
                self._state["frigateFireRate"] = self._fire_rate(values["frigateFireRate"], "frigate")
            if "cruiserFireRate" in values:
                self._state["cruiserFireRate"] = self._fire_rate(values["cruiserFireRate"], "cruiser")
        await self._publish_state(force_save=True)
        return self.state

    async def simulate_chat(self, sender: str, message: str) -> dict[str, Any]:
        clean_sender = self._clean_name(sender)
        clean_message = message.strip()[:500]
        if not clean_sender or not clean_message:
            raise ValueError("Absender und Nachricht dürfen nicht leer sein")
        await self.events.publish("chat.message", {"sender": clean_sender, "message": clean_message})
        await self.handle_chat(clean_sender, clean_message, simulated=True)
        return self.state

    async def handle_chat(self, sender: str, message: str, simulated: bool = False) -> None:
        clean_sender = self._clean_name(sender)
        text = message.strip()
        if not clean_sender or not text:
            return
        if (
            self._state["phase"] == "winner"
            and self._state["claimStatus"] == "pending"
            and self._state.get("winner")
            and clean_sender.casefold() == self._state["winner"]["name"].casefold()
        ):
            self._state["claimStatus"] = "claimed"
            self._add_log(f"{clean_sender} hat den Gewinn geclaimt")
            await self._publish_state(force_save=True)
            await self._sound("claim")
            await self._reply(f"@{clean_sender} hat den Gewinn erfolgreich geclaimt!", simulated)

        parts = text.split(maxsplit=1)
        command = parts[0].casefold()
        argument = parts[1] if len(parts) > 1 else ""
        if command == self._state["joinCommand"].casefold():
            await self.join(clean_sender, announce=not simulated)
            if simulated:
                await self._local_chat(f"@{clean_sender}, du nimmst am Giveaway teil. Viel Glück!")
            return
        if command == "!leave":
            await self.leave(clean_sender, announce=not simulated)
            return
        if command not in {"!wins", "!top3", "!giveaway"}:
            return
        cooldown_key = f"{command}:{clean_sender.casefold()}" if command == "!wins" else command
        now = time.monotonic()
        if now - self._chat_cooldowns.get(cooldown_key, 0) < 5:
            return
        self._chat_cooldowns[cooldown_key] = now
        if len(self._chat_cooldowns) > 500:
            self._chat_cooldowns.clear()
        if command == "!wins":
            target = self._clean_name(argument or clean_sender)
            pilot = await asyncio.to_thread(self.stats.lookup, target)
            wins = int(pilot["wins"])
            participations = int(pilot["participations"])
            await self._reply(
                f"@{clean_sender}: {pilot['name'] or target} hat {wins} "
                f"{'Sieg' if wins == 1 else 'Siege'} aus {participations} "
                f"{'Teilnahme' if participations == 1 else 'Teilnahmen'}.",
                simulated,
            )
        elif command == "!top3":
            leaders = [entry for entry in await asyncio.to_thread(self.stats.leaders) if entry["wins"] > 0][
                :3
            ]
            text = (
                f"Alltime Top {len(leaders)}: "
                + " · ".join(
                    f"{index}. {pilot['name']} ({pilot['wins']})"
                    for index, pilot in enumerate(leaders, 1)
                )
                if leaders
                else "Noch wurden keine Alltime-Siege aufgezeichnet."
            )
            await self._reply(text, simulated)
        else:
            await self._reply(self._giveaway_status(), simulated)

    async def _prepare_round(self, rematch: bool) -> None:
        names = [entry["name"] for entry in self._state["combatants"]]
        round_id = f"round-{self._now_ms()}-{secrets.token_hex(4)}"
        self._state["combatants"] = self._balance_fleet(names)
        self._state.update(
            phase="countdown",
            countdown=3,
            winner=None,
            winnerAllTimeWins=0,
            claimStatus="none",
            claimSeconds=60,
            activeRoundId=round_id,
            battleStartedAt=None,
        )
        self._add_log("Neue Runde mit gleicher Teilnehmerliste" if rematch else "Anmeldung geschlossen")
        if not self._state["testMode"]:
            await asyncio.to_thread(self.stats.record_participants, names, round_id)
        await self._publish_state(force_save=True)
        await self._reply(
            "Der Gewinn wurde nicht geclaimt. Neue Runde mit denselben Teilnehmern – "
            "keine Neuanmeldung nötig!"
            if rematch
            else "Die Anmeldung ist geschlossen. Das Gefecht startet jetzt!",
            bool(self._state["testMode"]),
        )
        self._phase_task = asyncio.create_task(
            self._countdown_and_battle(3, announce=True), name="arena-countdown"
        )

    async def _countdown_and_battle(self, initial: int, announce: bool) -> None:
        try:
            for remaining in range(max(0, initial), 0, -1):
                if self._state["phase"] != "countdown":
                    return
                self._state["countdown"] = remaining
                await self._publish_state()
                if announce:
                    await self._sound("countdown")
                await asyncio.sleep(0.9)
            self._state.update(
                phase="battle",
                countdown=0,
                battleId=int(self._state["battleId"]) + 1,
                battleStartedAt=self._now_ms(),
            )
            self._add_log("Kampf freigegeben")
            await self._publish_state(force_save=True)
            await self._sound("battle")
            await self._combat_loop()
        finally:
            if self._phase_task is asyncio.current_task():
                self._phase_task = None

    async def _combat_loop(self) -> None:
        next_shot: dict[str, float] = {}
        now = time.monotonic()
        for entry in self._state["combatants"]:
            rate = self._rate_for(entry)
            next_shot[entry["id"]] = now + self._random.uniform(0.15, max(0.2, rate))
        try:
            while self._state["phase"] == "battle":
                alive = [entry for entry in self._state["combatants"] if entry["alive"]]
                if len(alive) <= 1:
                    if alive:
                        await self._finish_battle(alive[0])
                    return
                now = time.monotonic()
                changed = False
                destroyed = False
                for attacker in list(alive):
                    if not attacker["alive"] or now < next_shot.get(attacker["id"], now):
                        continue
                    rate = self._rate_for(attacker)
                    next_shot[attacker["id"]] = now + rate * self._random.uniform(0.85, 1.15)
                    targets = [entry for entry in alive if entry["alive"] and entry["id"] != attacker["id"]]
                    if not targets:
                        break
                    target = self._random.choice(targets)
                    if self._random.random() > 1 - CLASS_STATS[target["shipClass"]]["dodge"]:
                        continue
                    low, high = CLASS_STATS[attacker["shipClass"]]["damage"]
                    target["hp"] = max(0.0, float(target["hp"]) - self._random.uniform(low, high))
                    changed = True
                    if target["hp"] <= 0 and target["alive"]:
                        target["alive"] = False
                        attacker["kills"] = int(attacker["kills"]) + 1
                        self._add_log(f"{attacker['name']} zerstört {target['name']}")
                        destroyed = True
                if changed:
                    await self._publish_state()
                if destroyed:
                    await self._sound("destroyed")
                await asyncio.sleep(0.05)
        finally:
            if self._phase_task is asyncio.current_task() and self._state["phase"] != "winner":
                self._phase_task = None

    async def _finish_battle(self, winner: dict[str, Any]) -> None:
        started_at = self._state.get("battleStartedAt") or self._now_ms()
        duration = max(0.0, (self._now_ms() - int(started_at)) / 1000)
        round_id = self._state.get("activeRoundId") or f"round-{self._now_ms()}"
        alltime_wins = 0
        if not self._state["testMode"]:
            pilot = await asyncio.to_thread(self.stats.record, winner["name"], round_id)
            alltime_wins = int(pilot["wins"])
        self._state.update(
            phase="winner",
            winner=copy.deepcopy(winner),
            winnerAllTimeWins=alltime_wins,
            claimStatus="pending",
            claimSeconds=60,
            battleStartedAt=None,
        )
        self._add_log(f"{winner['name']} gewinnt Runde {self._state['round']}")
        await self._publish_state(force_save=True)
        await self.events.publish(
            "arena.battle_complete",
            {
                "id": round_id,
                "winnerName": winner["name"],
                "winnerClass": winner["shipClass"],
                "durationSeconds": duration,
                "participants": len(self._state["combatants"]),
                "completedAt": datetime.now().astimezone().isoformat(),
                "frigateFireRate": self._state["frigateFireRate"],
                "cruiserFireRate": self._state["cruiserFireRate"],
            },
        )
        await self._sound("winner")
        await self._reply(
            f"@{winner['name']} gewinnt! Poste innerhalb von 60 Sekunden etwas im Chat, "
            "um den Gewinn zu claimen.",
            bool(self._state["testMode"]),
        )
        await self._claim_loop()

    async def _claim_loop(self) -> None:
        while self._state["phase"] == "winner" and self._state["claimStatus"] == "pending":
            if int(self._state["claimSeconds"]) <= 0:
                winner_name = self._state.get("winner", {}).get("name", "Gewinner")
                self._state["claimStatus"] = "expired"
                self._add_log(f"{winner_name} hat den Gewinn nicht geclaimt")
                await self._publish_state(force_save=True)
                await self._reply(
                    f"@{winner_name} hat nicht rechtzeitig geantwortet. Eine neue Runde kann "
                    "ohne Neuanmeldung gestartet werden.",
                    bool(self._state["testMode"]),
                )
                return
            await asyncio.sleep(1)
            if self._state["claimStatus"] == "pending":
                self._state["claimSeconds"] = max(0, int(self._state["claimSeconds"]) - 1)
                await self._publish_state()

    async def _publish_state(self, force_save: bool = False) -> None:
        self._state["origin"] = "python-server"
        self._state["updatedAt"] = self._now_ms()
        snapshot = self.state
        now = time.monotonic()
        if force_save or now - self._last_save >= 0.6:
            await asyncio.to_thread(self.store.save, snapshot)
            self._last_save = now
        await self.events.publish("arena.state", snapshot)

    async def _sound(self, cue: str) -> None:
        await self.events.publish("arena.sound", {"origin": "python-server", "cue": cue})

    async def _reply(self, message: str, simulated: bool) -> None:
        if simulated or self._state["testMode"]:
            await self._local_chat(message)
        else:
            await self._announce(message)

    async def _announce(self, message: str) -> None:
        await self._local_chat(message)
        with contextlib.suppress(Exception):
            await self.send_chat(message)

    async def _local_chat(self, message: str) -> None:
        await self.events.publish("chat.outgoing", {"message": message})

    async def _cancel_phase_task(self) -> None:
        task = self._phase_task
        if task and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._phase_task is task:
            self._phase_task = None

    def _giveaway_status(self) -> str:
        phase = self._state["phase"]
        combatants = self._state["combatants"]
        if phase == "idle":
            return "Derzeit ist kein Giveaway aktiv."
        if phase == "registration":
            return (
                f"Giveaway offen: {len(combatants)} Piloten angemeldet. "
                f"Mit {self._state['joinCommand']} teilnehmen."
            )
        if phase == "countdown":
            return f"Die Anmeldung ist geschlossen. Das Gefecht startet in {self._state['countdown']}."
        if phase == "battle":
            alive = sum(1 for entry in combatants if entry["alive"])
            return f"Das Gefecht läuft: {alive} von {len(combatants)} Piloten verbleiben."
        winner = self._state.get("winner", {}).get("name", "unbekannt")
        if self._state["claimStatus"] == "pending":
            return f"Gewinner ist @{winner}. Der Claim läuft noch {self._state['claimSeconds']} Sekunden."
        if self._state["claimStatus"] == "claimed":
            return f"@{winner} hat den Gewinn bestätigt."
        return "Der Gewinn wurde nicht rechtzeitig geclaimt. Ein Rematch ist möglich."

    def _balance_fleet(self, names: list[str]) -> list[dict[str, Any]]:
        shuffled = list(names)
        self._random.shuffle(shuffled)
        cruiser_names = {name.casefold() for name in shuffled[: len(names) // 4]}
        fleet = []
        for index, name in enumerate(names):
            ship_class = "cruiser" if name.casefold() in cruiser_names else "frigate"
            max_hp = CLASS_STATS[ship_class]["hp"]
            safe_id = "".join(char if char.isalnum() else "-" for char in name.casefold())
            fleet.append(
                {
                    "id": f"{safe_id}-{index}",
                    "name": name,
                    "shipClass": ship_class,
                    "hp": max_hp,
                    "maxHp": max_hp,
                    "alive": True,
                    "kills": 0,
                }
            )
        return fleet

    def _rate_for(self, entry: dict[str, Any]) -> float:
        key = "frigateFireRate" if entry["shipClass"] == "frigate" else "cruiserFireRate"
        return float(self._state[key])

    @staticmethod
    def _clean_name(value: str) -> str:
        return value.strip().removeprefix("@")[:25]

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _add_log_to(state: dict[str, Any], message: str) -> None:
        entry = {"time": datetime.now().strftime("%H:%M"), "message": message}
        state["logs"] = [entry, *state.get("logs", [])][:7]

    def _add_log(self, message: str) -> None:
        self._add_log_to(self._state, message)

    @staticmethod
    def _fire_rate(value: Any, ship_class: str) -> float:
        try:
            return min(8.0, max(0.2, float(value)))
        except (TypeError, ValueError):
            return DEFAULT_FIRE_RATES[ship_class]

    def _presentation(self) -> dict[str, Any]:
        return {
            key: copy.deepcopy(self._state[key])
            for key in (
                "arenaTitle",
                "joinCommand",
                "shipScale",
                "frigateFireRate",
                "cruiserFireRate",
                "soundOn",
                "themeId",
            )
        }

    @classmethod
    def _default_state(cls) -> dict[str, Any]:
        return {
            "origin": "python-server",
            "phase": "idle",
            "combatants": [],
            "battleId": 0,
            "round": 1,
            "countdown": 3,
            "winner": None,
            "winnerAllTimeWins": 0,
            "claimStatus": "none",
            "claimSeconds": 60,
            "logs": [{"time": "SYS", "message": "Derzeit kein Giveaway aktiv"}],
            "arenaTitle": "VOID ARENA",
            "joinCommand": "!join",
            "shipScale": 0.65,
            "frigateFireRate": DEFAULT_FIRE_RATES["frigate"],
            "cruiserFireRate": DEFAULT_FIRE_RATES["cruiser"],
            "soundOn": True,
            "themeId": "standard",
            "updatedAt": cls._now_ms(),
            "activeRoundId": None,
            "battleStartedAt": None,
            "testMode": False,
        }

    @classmethod
    def _normalize_state(cls, state: dict[str, Any] | None) -> dict[str, Any]:
        result = cls._default_state()
        if isinstance(state, dict):
            result.update(copy.deepcopy(state))
        if result.get("themeId") not in THEME_IDS:
            result["themeId"] = "standard"
        return result
