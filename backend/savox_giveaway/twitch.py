from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx
import websockets

from .config import ConfigStore
from .events import EventBus
from .secrets import SecretStore

TWITCH_AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
TWITCH_API_URL = "https://api.twitch.tv/helix"
TWITCH_EVENTSUB_URL = "wss://eventsub.wss.twitch.tv/ws?keepalive_timeout_seconds=30"
TWITCH_SCOPES = ("user:read:chat", "user:write:chat")


@dataclass(slots=True)
class TwitchStatus:
    configured: bool = False
    authenticated: bool = False
    connected: bool = False
    login: str = ""
    channel: str = ""
    message: str = "Nicht eingerichtet"

    def as_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "authenticated": self.authenticated,
            "connected": self.connected,
            "login": self.login,
            "channel": self.channel,
            "message": self.message,
        }


@dataclass(slots=True)
class TwitchService:
    config: ConfigStore
    secrets_store: SecretStore
    events: EventBus
    status: TwitchStatus = field(default_factory=TwitchStatus)
    _oauth_state: str = ""
    _task: asyncio.Task[None] | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _seen_messages: deque[str] = field(default_factory=lambda: deque(maxlen=1000))
    _user_id: str = ""
    _broadcaster_id: str = ""

    def __post_init__(self) -> None:
        self.refresh_configuration_status()

    def refresh_configuration_status(self) -> None:
        settings = self.config.load()
        has_secret = bool(self.secrets_store.get("twitch_client_secret"))
        has_token = bool(self.secrets_store.get("twitch_access_token"))
        self.status.configured = bool(settings.twitch_client_id and has_secret and settings.channel_login)
        self.status.authenticated = has_token
        self.status.channel = settings.channel_login
        if not self.status.configured:
            self.status.message = "Twitch-App noch nicht eingerichtet"
        elif not self.status.authenticated:
            self.status.message = "Twitch-Anmeldung erforderlich"

    def authorization_url(self) -> str:
        settings = self.config.load()
        if not settings.twitch_client_id:
            raise RuntimeError("Twitch Client-ID fehlt.")
        if not self.secrets_store.get("twitch_client_secret"):
            raise RuntimeError("Twitch Client-Secret fehlt.")
        self._oauth_state = secrets.token_urlsafe(32)
        query = urlencode(
            {
                "response_type": "code",
                "client_id": settings.twitch_client_id,
                "redirect_uri": settings.twitch_redirect_uri,
                "scope": " ".join(TWITCH_SCOPES),
                "state": self._oauth_state,
                "force_verify": "true",
            }
        )
        return f"{TWITCH_AUTHORIZE_URL}?{query}"

    async def finish_authorization(self, code: str, state: str) -> None:
        if not self._oauth_state or not secrets.compare_digest(state, self._oauth_state):
            raise RuntimeError("Die Twitch-Anmeldung wurde wegen eines ungültigen Status abgebrochen.")
        self._oauth_state = ""
        settings = self.config.load()
        client_secret = self.secrets_store.get("twitch_client_secret")
        data = {
            "client_id": settings.twitch_client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.twitch_redirect_uri,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(TWITCH_TOKEN_URL, data=data)
            response.raise_for_status()
            payload = response.json()
        self.secrets_store.set("twitch_access_token", payload["access_token"])
        self.secrets_store.set("twitch_refresh_token", payload.get("refresh_token", ""))
        self.refresh_configuration_status()
        await self.restart()

    async def start(self) -> None:
        self.refresh_configuration_status()
        if not self.status.configured or not self.status.authenticated:
            await self._publish_status()
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="twitch-eventsub")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self.status.connected = False
        await self._publish_status()

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def _run(self) -> None:
        retry_seconds = 2
        while not self._stop.is_set():
            try:
                token_data = await self._validate_or_refresh_token()
                self._user_id = str(token_data["user_id"])
                self.status.login = str(token_data.get("login", ""))
                self._broadcaster_id = await self._resolve_broadcaster_id()
                await self._eventsub_loop()
                retry_seconds = 2
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status.connected = False
                self.status.message = f"Twitch getrennt: {str(exc)[:120]}"
                await self._publish_status()
                await asyncio.sleep(retry_seconds)
                retry_seconds = min(30, retry_seconds * 2)

    async def _validate_or_refresh_token(self) -> dict[str, Any]:
        token = self.secrets_store.get("twitch_access_token")
        if not token:
            raise RuntimeError("Kein Twitch-Zugriffstoken vorhanden")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(TWITCH_VALIDATE_URL, headers={"Authorization": f"OAuth {token}"})
        if response.status_code == 401:
            await self._refresh_token()
            token = self.secrets_store.get("twitch_access_token")
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(TWITCH_VALIDATE_URL, headers={"Authorization": f"OAuth {token}"})
        response.raise_for_status()
        payload = response.json()
        missing = set(TWITCH_SCOPES) - set(payload.get("scopes", []))
        if missing:
            raise RuntimeError(f"Fehlende Twitch-Rechte: {', '.join(sorted(missing))}")
        self.status.authenticated = True
        return payload

    async def _refresh_token(self) -> None:
        settings = self.config.load()
        refresh_token = self.secrets_store.get("twitch_refresh_token")
        if not refresh_token:
            self.status.authenticated = False
            raise RuntimeError("Twitch-Anmeldung ist abgelaufen")
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.twitch_client_id,
            "client_secret": self.secrets_store.get("twitch_client_secret"),
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(TWITCH_TOKEN_URL, data=data)
            response.raise_for_status()
            payload = response.json()
        self.secrets_store.set("twitch_access_token", payload["access_token"])
        self.secrets_store.set("twitch_refresh_token", payload.get("refresh_token", refresh_token))

    def _api_headers(self) -> dict[str, str]:
        settings = self.config.load()
        return {
            "Authorization": f"Bearer {self.secrets_store.get('twitch_access_token')}",
            "Client-Id": settings.twitch_client_id,
            "Content-Type": "application/json",
        }

    async def _resolve_broadcaster_id(self) -> str:
        channel = self.config.load().channel_login
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{TWITCH_API_URL}/users", params={"login": channel}, headers=self._api_headers()
            )
            response.raise_for_status()
            users = response.json().get("data", [])
        if not users:
            raise RuntimeError(f"Twitch-Kanal #{channel} wurde nicht gefunden")
        return str(users[0]["id"])

    async def _eventsub_loop(self) -> None:
        url = TWITCH_EVENTSUB_URL
        subscribe_on_welcome = True
        while not self._stop.is_set():
            reconnect_url = ""
            async with websockets.connect(url, open_timeout=20, close_timeout=5) as websocket:
                async for raw in websocket:
                    message = json.loads(raw)
                    metadata = message.get("metadata", {})
                    message_id = str(metadata.get("message_id", ""))
                    if message_id and message_id in self._seen_messages:
                        continue
                    if message_id:
                        self._seen_messages.append(message_id)
                    message_type = metadata.get("message_type")
                    if message_type == "session_welcome":
                        session_id = message["payload"]["session"]["id"]
                        if subscribe_on_welcome:
                            await self._subscribe_to_chat(session_id)
                        self.status.connected = True
                        self.status.message = "Twitch-Chat verbunden"
                        await self._publish_status()
                    elif message_type == "notification":
                        await self._handle_notification(message)
                    elif message_type == "session_reconnect":
                        reconnect_url = str(message["payload"]["session"]["reconnect_url"])
                        break
                    elif message_type == "revocation":
                        reason = message.get("payload", {}).get("subscription", {}).get("status", "unbekannt")
                        raise RuntimeError(f"EventSub widerrufen: {reason}")
            if reconnect_url:
                url = reconnect_url
                subscribe_on_welcome = False
            else:
                url = TWITCH_EVENTSUB_URL
                subscribe_on_welcome = True

    async def _subscribe_to_chat(self, session_id: str) -> None:
        body = {
            "type": "channel.chat.message",
            "version": "1",
            "condition": {"broadcaster_user_id": self._broadcaster_id, "user_id": self._user_id},
            "transport": {"method": "websocket", "session_id": session_id},
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{TWITCH_API_URL}/eventsub/subscriptions", headers=self._api_headers(), json=body
            )
            response.raise_for_status()

    async def _handle_notification(self, message: dict[str, Any]) -> None:
        subscription = message.get("payload", {}).get("subscription", {})
        if subscription.get("type") != "channel.chat.message":
            return
        event = message.get("payload", {}).get("event", {})
        sender = str(event.get("chatter_user_name") or event.get("chatter_user_login") or "")
        text = str(event.get("message", {}).get("text") or "")
        if sender and text:
            await self.events.publish(
                "chat.message",
                {"sender": sender, "message": text, "message_id": event.get("message_id", "")},
            )

    async def send_chat(self, message: str) -> None:
        if not self.status.connected:
            raise RuntimeError("Twitch-Chat ist nicht verbunden")
        body = {
            "broadcaster_id": self._broadcaster_id,
            "sender_id": self._user_id,
            "message": message[:500],
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{TWITCH_API_URL}/chat/messages", headers=self._api_headers(), json=body
            )
            if response.status_code == 401:
                await self._refresh_token()
                response = await client.post(
                    f"{TWITCH_API_URL}/chat/messages", headers=self._api_headers(), json=body
                )
            response.raise_for_status()
            data = response.json().get("data", [])
        if data and not data[0].get("is_sent", True):
            reason = data[0].get("drop_reason", {}).get("message", "Nachricht wurde abgelehnt")
            raise RuntimeError(reason)

    async def _publish_status(self) -> None:
        await self.events.publish("twitch.status", self.status.as_dict())
