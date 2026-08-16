from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from . import __version__
from .arena_state import ArenaStateStore
from .config import DEFAULT_SERVER_PORT, AppSettings, ConfigStore
from .events import EventBus
from .secrets import SecretStore
from .stats import WinnerStatsStore
from .twitch import TwitchService
from .updater import GitHubUpdater, UpdateInfo, exit_after_delay, update_to_dict


def frontend_directory() -> Path:
    if bundle_root := getattr(sys, "_MEIPASS", None):
        return Path(bundle_root) / "frontend" / "dist"
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


class SettingsPayload(BaseModel):
    channel_login: str = Field(default="savox76", max_length=25)
    twitch_client_id: str = Field(default="", max_length=80)
    twitch_client_secret: str | None = Field(default=None, max_length=200)
    server_port: int = Field(default=DEFAULT_SERVER_PORT, ge=1024, le=65535)
    github_owner: str = Field(default="Savox76", max_length=100)
    github_repo: str = Field(default="savox76-giveaway", max_length=100)
    auto_update: bool = True
    open_browser_on_start: bool = True


class ChatPayload(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class WinnerRecordPayload(BaseModel):
    name: str = Field(min_length=1, max_length=25)
    record_id: str = Field(min_length=1, max_length=100)


class ParticipantRecordPayload(BaseModel):
    names: list[str] = Field(min_length=1, max_length=200)
    round_id: str = Field(min_length=1, max_length=100)


class ArenaCombatantPayload(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=25)
    shipClass: Literal["frigate", "cruiser"]
    hp: float = Field(ge=0, le=1000)
    maxHp: float = Field(gt=0, le=1000)
    alive: bool
    kills: int = Field(ge=0, le=1000)


class ArenaLogPayload(BaseModel):
    time: str = Field(min_length=1, max_length=8)
    message: str = Field(min_length=1, max_length=200)


class ArenaStatePayload(BaseModel):
    origin: str = Field(min_length=1, max_length=100)
    phase: Literal["idle", "registration", "countdown", "battle", "winner"]
    combatants: list[ArenaCombatantPayload] = Field(default_factory=list, max_length=200)
    battleId: int = Field(ge=0)
    round: int = Field(ge=1)
    countdown: int = Field(ge=0, le=3)
    winner: ArenaCombatantPayload | None = None
    winnerAllTimeWins: int = Field(default=0, ge=0)
    claimStatus: Literal["none", "pending", "claimed", "expired"]
    claimSeconds: int = Field(ge=0, le=60)
    logs: list[ArenaLogPayload] = Field(default_factory=list, max_length=7)
    arenaTitle: str = Field(min_length=1, max_length=28)
    joinCommand: str = Field(min_length=1, max_length=20)
    shipScale: float = Field(ge=0.45, le=1)
    frigateFireRate: float = Field(ge=0.2, le=8)
    cruiserFireRate: float = Field(ge=0.2, le=8)
    soundOn: bool
    updatedAt: int = Field(default=0, ge=0)
    activeRoundId: str | None = Field(default=None, max_length=100)
    battleStartedAt: int | None = Field(default=None, ge=0)
    testMode: bool = False


class ArenaSoundPayload(BaseModel):
    origin: str = Field(min_length=1, max_length=100)
    cue: Literal["toggle", "countdown", "battle", "destroyed", "winner", "claim"]


class ClientHelloPayload(BaseModel):
    origin: str = Field(min_length=1, max_length=100)
    role: Literal["control", "overlay"]


class ApplicationState:
    def __init__(self, config: ConfigStore | None = None, secret_store: SecretStore | None = None) -> None:
        self.config = config or ConfigStore()
        self.secrets = secret_store or SecretStore()
        self.events = EventBus()
        self.twitch = TwitchService(self.config, self.secrets, self.events)
        self.stats = WinnerStatsStore(self.config.path.with_name("winner-stats.json"))
        self.arena_store = ArenaStateStore(self.config.path.with_name("arena-state.json"))
        stored_arena = self.arena_store.load()
        try:
            self.arena_state = (
                ArenaStatePayload.model_validate(stored_arena).model_dump() if stored_arena else None
            )
        except ValidationError:
            self.arena_state = None
        self.last_arena_save = 0.0
        self.overlay_connections: set[WebSocket] = set()
        self.latest_update: UpdateInfo | None = None
        self.update_task: asyncio.Task[None] | None = None

    def updater(self) -> GitHubUpdater:
        settings = self.config.load()
        return GitHubUpdater(
            owner=settings.github_owner,
            repo=settings.github_repo,
            current_version=__version__,
        )

    async def check_update(self) -> UpdateInfo | None:
        self.latest_update = await self.updater().check()
        await self.events.publish("update.status", update_to_dict(self.latest_update))
        return self.latest_update

    async def update_watch(self) -> None:
        while True:
            try:
                update = await self.check_update()
                updater = self.updater()
                if update and self.config.load().auto_update:
                    await self.events.publish("update.installing", {"version": update.version})
                    staged = await updater.download_and_stage(update)
                    updater.launch_installer(staged)
                    asyncio.create_task(exit_after_delay())
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self.events.publish("update.error", {"message": str(exc)[:200]})
            await asyncio.sleep(6 * 60 * 60)

    async def update_arena_state(self, state: dict[str, Any]) -> None:
        previous = self.arena_state
        self.arena_state = state
        now = time.monotonic()
        important_change = (
            previous is None
            or previous.get("phase") != state.get("phase")
            or previous.get("claimStatus") != state.get("claimStatus")
            or len(previous.get("combatants", [])) != len(state.get("combatants", []))
        )
        if important_change or now - self.last_arena_save >= 0.6:
            await asyncio.to_thread(self.arena_store.save, state)
            self.last_arena_save = now


def create_app(state: ApplicationState | None = None) -> FastAPI:
    app_state = state or ApplicationState()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await app_state.twitch.start()
        app_state.update_task = asyncio.create_task(app_state.update_watch(), name="github-update-watch")
        yield
        if app_state.update_task:
            app_state.update_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await app_state.update_task
        if app_state.arena_state is not None:
            await asyncio.to_thread(app_state.arena_store.save, app_state.arena_state)
        await app_state.twitch.stop()

    app = FastAPI(title="Savox76 Giveaway System", version=__version__, lifespan=lifespan)
    app.state.savox = app_state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        return {
            "version": __version__,
            "twitch": app_state.twitch.status.as_dict(),
            "update": update_to_dict(app_state.latest_update),
            "mode": "python",
        }

    @app.get("/api/settings")
    async def get_settings() -> dict[str, Any]:
        settings = app_state.config.load()
        payload = asdict(settings)
        payload["twitch_client_secret_set"] = bool(app_state.secrets.get("twitch_client_secret"))
        return payload

    @app.put("/api/settings")
    async def save_settings(payload: SettingsPayload) -> dict[str, Any]:
        settings = AppSettings(
            channel_login=payload.channel_login,
            twitch_client_id=payload.twitch_client_id,
            server_port=payload.server_port,
            github_owner=payload.github_owner,
            github_repo=payload.github_repo,
            auto_update=payload.auto_update,
            open_browser_on_start=payload.open_browser_on_start,
        )
        app_state.config.save(settings)
        if payload.twitch_client_secret is not None:
            app_state.secrets.set("twitch_client_secret", payload.twitch_client_secret.strip())
        app_state.twitch.refresh_configuration_status()
        await app_state.twitch.restart()
        return await get_settings()

    @app.get("/api/twitch/login", response_model=None)
    async def twitch_login() -> RedirectResponse | HTMLResponse:
        try:
            url = await app_state.twitch.start_device_authorization()
        except Exception as exc:
            return HTMLResponse(
                _callback_page("Twitch-Anmeldung konnte nicht starten", str(exc)),
                status_code=400,
            )
        return RedirectResponse(url)

    @app.get("/api/twitch/callback")
    async def twitch_callback() -> HTMLResponse:
        return HTMLResponse(
            _callback_page(
                "Neue Twitch-Anmeldung aktiv",
                "Bitte im Kontrollfenster auf Mit Twitch verbinden klicken. "
                "Eine Redirect-URL wird nicht mehr benötigt.",
            )
        )

    @app.post("/api/twitch/reconnect")
    async def twitch_reconnect() -> dict[str, Any]:
        await app_state.twitch.restart()
        return app_state.twitch.status.as_dict()

    @app.post("/api/twitch/chat")
    async def send_chat(payload: ChatPayload) -> dict[str, bool]:
        try:
            await app_state.twitch.send_chat(payload.message)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"sent": True}

    @app.post("/api/stats/winner")
    async def record_winner(payload: WinnerRecordPayload) -> dict[str, Any]:
        try:
            return app_state.stats.record(payload.name, payload.record_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/stats/winner")
    async def winner_lookup(name: str) -> dict[str, Any]:
        return app_state.stats.lookup(name)

    @app.post("/api/stats/participants")
    async def record_participants(payload: ParticipantRecordPayload) -> list[dict[str, Any]]:
        try:
            return app_state.stats.record_participants(payload.names, payload.round_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/stats/winners")
    async def winner_leaders() -> list[dict[str, Any]]:
        return app_state.stats.leaders()

    @app.get("/api/update/check")
    async def check_update() -> dict[str, Any]:
        try:
            return update_to_dict(await app_state.check_update())
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"GitHub nicht erreichbar: {exc}") from exc

    @app.post("/api/update/install")
    async def install_update() -> dict[str, Any]:
        update = app_state.latest_update or await app_state.check_update()
        if update is None:
            return {"started": False, "message": "Keine neue Version verfügbar"}
        updater = app_state.updater()
        try:
            staged = await updater.download_and_stage(update)
            updater.launch_installer(staged)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        asyncio.create_task(exit_after_delay())
        return {"started": True, "version": update.version}

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket) -> None:
        await app_state.events.connect(websocket)
        await websocket.send_json({"type": "twitch.status", "payload": app_state.twitch.status.as_dict()})
        await websocket.send_json(
            {"type": "update.status", "payload": update_to_dict(app_state.latest_update)}
        )
        await websocket.send_json(
            {
                "type": "overlay.status",
                "payload": {
                    "connected": bool(app_state.overlay_connections),
                    "count": len(app_state.overlay_connections),
                },
            }
        )
        await websocket.send_json({"type": "arena.restore", "payload": {"state": app_state.arena_state}})
        try:
            while True:
                raw = await websocket.receive_text()
                if raw in {"ready", "ping"} or len(raw) > 200_000:
                    continue
                try:
                    message = json.loads(raw)
                    event_type = message.get("type")
                    payload = message.get("payload")
                    if event_type == "client.hello":
                        hello = ClientHelloPayload.model_validate(payload)
                        if hello.role == "overlay":
                            app_state.overlay_connections.add(websocket)
                            await app_state.events.publish(
                                "overlay.status",
                                {
                                    "connected": True,
                                    "count": len(app_state.overlay_connections),
                                },
                            )
                    elif event_type == "arena.state":
                        state_payload = ArenaStatePayload.model_validate(payload).model_dump()
                        await app_state.update_arena_state(state_payload)
                        await app_state.events.publish("arena.state", state_payload)
                    elif event_type == "arena.sound":
                        sound_payload = ArenaSoundPayload.model_validate(payload).model_dump()
                        await app_state.events.publish("arena.sound", sound_payload)
                except (AttributeError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
                    continue
        except WebSocketDisconnect:
            pass
        finally:
            was_overlay = websocket in app_state.overlay_connections
            app_state.overlay_connections.discard(websocket)
            await app_state.events.disconnect(websocket)
            if was_overlay:
                await app_state.events.publish(
                    "overlay.status",
                    {
                        "connected": bool(app_state.overlay_connections),
                        "count": len(app_state.overlay_connections),
                    },
                )

    frontend = frontend_directory()
    if frontend.exists():
        assets = frontend / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        async def root() -> RedirectResponse:
            return RedirectResponse("/control")

        @app.get("/control")
        @app.get("/overlay")
        async def surface() -> FileResponse:
            return FileResponse(frontend / "index.html")

        @app.get("/realistic-space-panorama.webp")
        async def panorama() -> FileResponse:
            return FileResponse(frontend / "realistic-space-panorama.webp")

        @app.get("/favicon.svg", include_in_schema=False)
        @app.get("/favicon.ico", include_in_schema=False)
        async def favicon() -> FileResponse:
            return FileResponse(frontend / "favicon.svg", media_type="image/svg+xml")
    else:

        @app.get("/")
        async def source_help() -> dict[str, str]:
            return {"message": "Frontend fehlt. Zuerst `npm run build` im Ordner frontend ausführen."}

    return app


def _callback_page(title: str, message: str) -> str:
    safe_title = title.replace("<", "&lt;").replace(">", "&gt;")
    safe_message = message.replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!doctype html><html lang=\"de\"><meta charset=\"utf-8\"><title>{safe_title}</title>
    <body style=\"background:#030812;color:#d7f7ff;font:16px system-ui;padding:40px\"><h1>{safe_title}</h1>
    <p>{safe_message}</p><script>setTimeout(() => window.close(), 1800)</script></body></html>"""


app = create_app()
