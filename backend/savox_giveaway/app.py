from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from scripts.error_report import ErrorReport, ErrorReportStore

from . import __version__
from .arena_state import ArenaStateStore
from .config import DEFAULT_SERVER_PORT, AppSettings, ConfigStore
from .events import EventBus
from .game import THEME_IDS, ArenaGame
from .secrets import SecretStore
from .stats import WinnerStatsStore
from .twitch import TwitchService
from .updater import GitHubUpdater, UpdateInfo, exit_after_delay, project_root, update_to_dict


def frontend_directory() -> Path:
    if bundle_root := getattr(sys, "_MEIPASS", None):
        return Path(bundle_root) / "frontend" / "dist"
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


class SettingsPayload(BaseModel):
    channel_login: str = Field(default="savox76", max_length=25)
    twitch_client_id: str = Field(default="", max_length=80)
    twitch_client_secret: str | None = Field(default=None, max_length=200)
    server_port: int = Field(default=DEFAULT_SERVER_PORT, ge=1024, le=65535)
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
    themeId: Literal["standard", "easter", "christmas", "halloween", "anniversary"] = "standard"
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


class ArenaJoinPayload(BaseModel):
    name: str = Field(min_length=1, max_length=25)


class ArenaChatSimulationPayload(BaseModel):
    sender: str = Field(min_length=1, max_length=25)
    message: str = Field(min_length=1, max_length=500)


class ArenaPresentationPayload(BaseModel):
    arenaTitle: str | None = Field(default=None, max_length=28)
    joinCommand: str | None = Field(default=None, max_length=20)
    shipScale: float | None = Field(default=None, ge=0.45, le=1)
    frigateFireRate: float | None = Field(default=None, ge=0.2, le=8)
    cruiserFireRate: float | None = Field(default=None, ge=0.2, le=8)
    soundOn: bool | None = None
    themeId: str | None = Field(default=None, max_length=30)


class FrontendErrorPayload(BaseModel):
    error_type: str = Field(default="FrontendError", max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    stack: str = Field(default="", max_length=20_000)
    source: str = Field(default="Browseroberfläche", max_length=200)
    route: str = Field(default="", max_length=100)
    viewport: str = Field(default="", max_length=40)
    user_agent: str = Field(default="", max_length=600)


class ApplicationState:
    def __init__(self, config: ConfigStore | None = None, secret_store: SecretStore | None = None) -> None:
        provided_config = config is not None
        self.config = config or ConfigStore()
        self.secrets = secret_store or SecretStore()
        self.events = EventBus()
        self.twitch = TwitchService(self.config, self.secrets, self.events)
        self.stats = WinnerStatsStore(self.config.path.with_name("winner-stats.json"))
        self.arena_store = ArenaStateStore(self.config.path.with_name("arena-state.json"))
        stored_arena = self.arena_store.load()
        try:
            stored_arena = (
                ArenaStatePayload.model_validate(stored_arena).model_dump() if stored_arena else None
            )
        except ValidationError:
            stored_arena = None
        self.arena = ArenaGame(
            self.arena_store,
            self.stats,
            self.events,
            self.twitch.send_chat,
            stored_arena,
        )
        self.twitch.chat_handler = self.arena.handle_chat
        self.overlay_connections: set[WebSocket] = set()
        self.latest_update: UpdateInfo | None = None
        self.update_task: asyncio.Task[None] | None = None
        root = project_root()
        report_directory = (
            self.config.path.parent / "error-reports"
            if provided_config
            else root / ".updates" / "error-reports"
        )
        self.error_reports = ErrorReportStore(report_directory, root, __version__)

    def updater(self) -> GitHubUpdater:
        return GitHubUpdater(current_version=__version__)

    def diagnostic_context(self) -> dict[str, Any]:
        arena = self.arena.state
        settings = self.config.load()
        return {
            "Arena-Phase": arena.get("phase", "unbekannt"),
            "Teilnehmerzahl": len(arena.get("combatants", [])),
            "Event-Theme": arena.get("themeId", "unbekannt"),
            "Twitch konfiguriert": self.twitch.status.configured,
            "Twitch verbunden": self.twitch.status.connected,
            "Stream live": self.twitch.status.live,
            "OBS-Verbindungen": len(self.overlay_connections),
            "Auto-Update": settings.auto_update,
            "Server-Port": settings.server_port,
        }

    def capture_error(
        self,
        exc: BaseException,
        component: str,
        context: dict[str, Any] | None = None,
    ) -> ErrorReport:
        diagnostics = self.diagnostic_context()
        diagnostics.update(context or {})
        return self.error_reports.capture_exception(exc, component, context=diagnostics)

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

def create_app(state: ApplicationState | None = None) -> FastAPI:
    app_state = state or ApplicationState()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        loop = asyncio.get_running_loop()
        previous_exception_handler = loop.get_exception_handler()

        def report_async_exception(current_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
            exc = context.get("exception")
            if not isinstance(exc, BaseException):
                exc = RuntimeError(str(context.get("message") or "Unbekannter Hintergrundfehler"))
            report = app_state.capture_error(
                exc,
                "Hintergrundaufgabe",
                {"Task": str(context.get("task") or context.get("future") or "unbekannt")},
            )
            current_loop.create_task(app_state.events.publish("error.report", report.status()))
            if previous_exception_handler:
                previous_exception_handler(current_loop, context)
            else:
                current_loop.default_exception_handler(context)

        loop.set_exception_handler(report_async_exception)
        await app_state.twitch.start()
        await app_state.arena.start()
        app_state.update_task = asyncio.create_task(app_state.update_watch(), name="github-update-watch")
        yield
        if app_state.update_task:
            app_state.update_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await app_state.update_task
        await app_state.arena.stop()
        await app_state.twitch.stop()
        loop.set_exception_handler(previous_exception_handler)

    app = FastAPI(title="Savox76 Giveaway System", version=__version__, lifespan=lifespan)
    app.state.savox = app_state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def report_unhandled_request_errors(request: Request, call_next: Any) -> Any:
        try:
            return await call_next(request)
        except Exception as exc:
            report = app_state.capture_error(
                exc,
                "Lokale API",
                {"Anfrage": f"{request.method} {request.url.path}"},
            )
            await app_state.events.publish("error.report", report.status())
            raise

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        return {
            "version": __version__,
            "twitch": app_state.twitch.status.as_dict(),
            "update": update_to_dict(app_state.latest_update),
            "error_report": app_state.error_reports.status(),
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
            auto_update=payload.auto_update,
            open_browser_on_start=payload.open_browser_on_start,
        )
        app_state.config.save(settings)
        if payload.twitch_client_secret is not None:
            app_state.secrets.set("twitch_client_secret", payload.twitch_client_secret.strip())
        app_state.twitch.refresh_configuration_status()
        await app_state.twitch.restart()
        return await get_settings()

    @app.get("/api/error-report")
    async def error_report_status() -> dict[str, Any]:
        return app_state.error_reports.status()

    @app.post("/api/error-report/frontend")
    async def report_frontend_error(payload: FrontendErrorPayload) -> dict[str, Any]:
        report = app_state.error_reports.capture_text(
            error_type=payload.error_type,
            message=payload.message,
            trace=payload.stack,
            component=payload.source,
            context={
                **app_state.diagnostic_context(),
                "Browser-Route": payload.route,
                "Fenstergröße": payload.viewport,
                "Browser": payload.user_agent,
            },
        )
        await app_state.events.publish("error.report", report.status())
        return report.status()

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

    @app.get("/api/arena/state")
    async def arena_state() -> dict[str, Any]:
        return app_state.arena.state

    @app.post("/api/arena/start")
    async def arena_start() -> dict[str, Any]:
        return await app_state.arena.start_giveaway()

    @app.post("/api/arena/test/{count}")
    async def arena_test(count: int) -> dict[str, Any]:
        try:
            return await app_state.arena.load_test_fleet(count)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/arena/join")
    async def arena_join(payload: ArenaJoinPayload) -> dict[str, Any]:
        try:
            return await app_state.arena.join(payload.name, announce=False)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/arena/participants/{participant_id}")
    async def arena_remove_participant(participant_id: str) -> dict[str, Any]:
        return await app_state.arena.remove_participant(participant_id)

    @app.post("/api/arena/battle")
    async def arena_battle() -> dict[str, Any]:
        try:
            return await app_state.arena.start_battle()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/arena/rematch")
    async def arena_rematch() -> dict[str, Any]:
        try:
            return await app_state.arena.start_rematch()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/arena/end")
    async def arena_end() -> dict[str, Any]:
        return await app_state.arena.end_giveaway()

    @app.post("/api/arena/chat")
    async def arena_chat(payload: ArenaChatSimulationPayload) -> dict[str, Any]:
        try:
            return await app_state.arena.simulate_chat(payload.sender, payload.message)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/arena/presentation")
    async def arena_presentation(payload: ArenaPresentationPayload) -> dict[str, Any]:
        values = payload.model_dump(exclude_none=True)
        if theme_id := values.get("themeId"):
            if theme_id not in THEME_IDS:
                raise HTTPException(status_code=400, detail="Unbekanntes Event-Theme")
        try:
            return await app_state.arena.update_presentation(values)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        await websocket.send_json({"type": "arena.restore", "payload": {"state": app_state.arena.state}})
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
        @app.get("/themes")
        @app.get("/overlay")
        @app.get("/status")
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
