"""Milky HTTP API and forward WebSocket transport."""
from __future__ import annotations

import asyncio
import json
import math
from urllib.parse import urlsplit, urlunsplit

import aiohttp

if __package__:
    from .milky_api import MilkyAPIMixin
else:
    from milky_api import MilkyAPIMixin


class MilkyError(RuntimeError):
    def __init__(self, api: str, retcode: int | str):
        self.api = api
        self.retcode = retcode
        # Do not echo response bodies, URLs or credentials into logs.
        super().__init__(f"Milky API {api} failed (code={retcode})")


def endpoints(base_url: str, event_url: str = "") -> tuple[str, str]:
    base = urlsplit(base_url.strip())
    if base.scheme not in {"http", "https"} or not base.hostname:
        raise ValueError("base_url must be an HTTP(S) URL")
    if base.username or base.password or base.query or base.fragment:
        raise ValueError("base_url must not contain credentials, query or fragment")
    path = base.path.rstrip("/")
    if path.endswith("/api"):
        path = path[:-4]
    api = urlunsplit((base.scheme, base.netloc, path + "/api", "", ""))
    ws = event_url.strip() or urlunsplit(
        ("wss" if base.scheme == "https" else "ws", base.netloc, path + "/event", "", "")
    )
    parsed = urlsplit(ws)
    if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
        raise ValueError("event_url must be a WS(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("event_url must not contain credentials, query or fragment; use access_token")
    return api, ws


class MilkyClient(MilkyAPIMixin):
    def __init__(self, base_url: str, access_token: str = "", event_url: str = "",
                 timeout: float = 30, max_message_size: int = 16 * 1024 * 1024):
        self.api_url, self.event_url = endpoints(base_url, event_url)
        self.timeout = float(timeout)
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("request_timeout must be positive and finite")
        self.headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
        self.max_message_size = max_message_size
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._closed = False

    async def start(self):
        if self._closed:
            raise RuntimeError("Milky client has been closed")
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout), trust_env=False
            )

    async def call_api(self, api: str, **params) -> dict:
        if not api or not all(c.isalnum() or c == "_" for c in api):
            raise ValueError("Invalid Milky API name")
        await self.start()
        assert self._session is not None
        async with self._session.post(
            f"{self.api_url}/{api}", json=params, headers=self.headers,
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                raise MilkyError(api, response.status)
            try:
                payload = await response.json()
            except (ValueError, aiohttp.ContentTypeError) as exc:
                raise MilkyError(api, "invalid_json") from exc
        if not isinstance(payload, dict):
            raise MilkyError(api, "invalid_envelope")
        if payload.get("status") != "ok" or payload.get("retcode") != 0:
            code = payload.get("retcode")
            raise MilkyError(api, code if isinstance(code, int) else "invalid_retcode")
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise MilkyError(api, "invalid_data")
        return data

    async def events(self, connected=None):
        await self.start()
        assert self._session is not None
        ws = await self._session.ws_connect(
            self.event_url, headers=self.headers, heartbeat=30,
            max_msg_size=self.max_message_size,
        )
        self._ws = ws
        try:
            if connected:
                connected()
            async for message in ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    try:
                        event = json.loads(message.data)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(event, dict):
                        yield event
                elif message.type == aiohttp.WSMsgType.ERROR:
                    raise ConnectionError("Milky event connection failed")
        finally:
            try:
                await self._close_websocket(ws)
            finally:
                self._ws = None

    async def _close_websocket(self, ws):
        try:
            await asyncio.wait_for(ws.close(), timeout=min(self.timeout, 2.0))
        except asyncio.TimeoutError:
            # Closing the owning session aborts a stalled handshake via public APIs.
            if self._session is not None:
                await self._session.close()
                self._session = None
        except asyncio.CancelledError:
            if self._session is not None:
                await self._session.close()
                self._session = None
            raise

    async def close(self):
        self._closed = True
        try:
            if self._ws is not None:
                await self._close_websocket(self._ws)
        finally:
            if self._session is not None:
                await self._session.close()
