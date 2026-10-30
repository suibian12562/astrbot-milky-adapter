"""AstrBot platform registration and lifecycle."""
from __future__ import annotations

import asyncio
import math

import aiohttp
from collections import OrderedDict

from astrbot.api import logger, message_components as C
from astrbot.api.platform import (
    AstrBotMessage, AstrMessageEvent, Group, MessageMember, MessageType,
    Platform, PlatformMetadata, register_platform_adapter,
)

from .converter import MessageConverter
from .milky_client import MilkyClient

DEFAULT_CONFIG = {
    "type": "milky", "id": "milky", "enable": False,
    "base_url": "http://127.0.0.1:3000", "event_url": "",
    "access_token": "", "request_timeout": 30,
    "reconnect_interval": 3, "max_upload_mb": 20,
    "ignore_self": True,
}


class MilkyMessageEvent(AstrMessageEvent):
    def __init__(self, message, adapter):
        super().__init__(message.message_str, message, adapter.meta(), message.session_id)
        self.adapter = adapter
        self.bot = adapter.client

    async def send(self, message):
        envelope = self.message_obj.raw_message
        raw = envelope["data"]
        if envelope.get("event_type") == "message_receive":
            scene, peer = raw["message_scene"], raw["peer_id"]
        elif raw.get("message_scene") == "group" or raw.get("group_id") is not None:
            scene, peer = "group", raw.get("group_id", raw.get("peer_id"))
        elif raw.get("user_id") is not None and envelope.get("event_type", "").startswith("friend_"):
            scene, peer = "friend", raw["user_id"]
        else:
            raise ValueError("This Milky notification has no replyable conversation")
        await self.adapter.converter.send(scene, peer, message.chain)
        await super().send(message)

    async def get_group(self, group_id=None, **kwargs):
        current = getattr(self.message_obj, "group", None)
        resolved = group_id or (current.group_id if current else None)
        if not resolved:
            return None
        group = current if current and current.group_id == str(resolved) else Group(group_id=str(resolved))
        try:
            info = await self.bot.call_api("get_group_info", group_id=int(resolved))
            details = info["group"]
            group.group_name = details.get("group_name")
            group.member_count = details.get("member_count")
        except (KeyError, TypeError, ValueError, RuntimeError, aiohttp.ClientError, asyncio.TimeoutError):
            logger.warning("Milky group information unavailable")
        try:
            data = await self.bot.call_api("get_group_member_list", group_id=int(resolved))
            members = data["members"]
            group.members = [MessageMember(str(m["user_id"]), m.get("card") or m.get("nickname")) for m in members]
            group.group_owner = next((str(m["user_id"]) for m in members if m.get("role") == "owner"), None)
            group.group_admins = [str(m["user_id"]) for m in members if m.get("role") == "admin"]
        except (KeyError, TypeError, ValueError, RuntimeError, aiohttp.ClientError, asyncio.TimeoutError):
            logger.warning("Milky group members unavailable")
        return group

    async def send_streaming(self, generator, use_fallback=False):
        from astrbot.api.event import MessageChain
        parts = []
        async for chain in generator:
            parts.extend(chain.chain)
        if parts:
            await self.send(MessageChain(parts))


@register_platform_adapter(
    "milky", "Milky QQ protocol adapter (HTTP + forward WebSocket)",
    default_config_tmpl=DEFAULT_CONFIG,
    adapter_display_name="Milky", support_streaming_message=False,
)
class MilkyAdapter(Platform):
    def __init__(self, platform_config: dict, platform_settings: dict, event_queue: asyncio.Queue):
        config = {**DEFAULT_CONFIG, **platform_config}
        super().__init__(config, event_queue)
        self.settings = platform_settings
        self.client = MilkyClient(config["base_url"], config["access_token"], config["event_url"], config["request_timeout"])
        self.reconnect_interval = float(config["reconnect_interval"])
        upload_mb = float(config["max_upload_mb"])
        if not math.isfinite(self.reconnect_interval) or self.reconnect_interval <= 0:
            raise ValueError("reconnect_interval must be positive and finite")
        if not math.isfinite(upload_mb) or upload_mb <= 0:
            raise ValueError("max_upload_mb must be positive and finite")
        self.converter = MessageConverter(self.client, int(upload_mb * 1024 * 1024))
        self.metadata = PlatformMetadata(
            name="milky", description="Milky QQ protocol adapter", id=config["id"],
            adapter_display_name="Milky", support_streaming_message=False,
        )
        self._stop = asyncio.Event()
        self._seen = OrderedDict()
        self._task = None

    def meta(self):
        return self.metadata

    def get_client(self):
        return self.client

    def create_event(self, message):
        return MilkyMessageEvent(message, self)

    async def convert_message(self, event):
        if event.get("event_type") != "message_receive":
            return None
        data = event["data"]
        scene = data["message_scene"]
        if scene not in {"friend", "group", "temp"}:
            return None
        if self.config["ignore_self"] and str(data["sender_id"]) == str(event["self_id"]):
            return None
        peer = int(data["peer_id"])
        message = AstrBotMessage()
        message.self_id = str(event["self_id"])
        message.message_id = f"{scene}:{peer}:{int(data['message_seq'])}"
        message.type = MessageType.GROUP_MESSAGE if scene == "group" else MessageType.FRIEND_MESSAGE
        message.session_id = str(peer) if scene != "temp" else f"temp_{peer}_{data['sender_id']}"
        if scene == "group":
            group = data.get("group") or {}
            message.group = Group(group_id=str(peer), group_name=group.get("group_name"), member_count=group.get("member_count"))
        member = (data.get("group_member") if scene == "group" else data.get("friend")) or {}
        message.sender = MessageMember(str(data["sender_id"]), member.get("card") or member.get("nickname") or str(data["sender_id"]))
        message.message = await self.converter.incoming(data["segments"], scene, peer)
        message.message_str = "".join(p.text for p in message.message if isinstance(p, C.Plain))
        message.timestamp = int(data["time"])
        message.raw_message = event
        return message

    async def handle_event(self, event):
        event_type = event.get("event_type")
        if event_type == "message_receive":
            data = event["data"]
            key = (event.get("self_id"), data.get("message_scene"), data.get("peer_id"), data.get("message_seq"))
            if key in self._seen:
                return
            message = await self.convert_message(event)
            if message is not None:
                self.commit_event(self.create_event(message))
                self._remember(key)
            return
        if not isinstance(event_type, str) or not isinstance(event.get("data"), dict):
            return
        # Milky has many notification/request event types. Preserve their complete
        # envelope as an OTHER_MESSAGE so plugins can inspect and act on all events.
        # Notifications have no unique event ID; do not deduplicate by timestamp,
        # which would discard legitimate repeated actions within the same second.
        message = self._convert_other_event(event)
        if event_type in {"friend_file_upload", "group_file_upload"}:
            data = event["data"]
            scene = "group" if event_type == "group_file_upload" else "friend"
            peer = data["group_id"] if scene == "group" else data["user_id"]
            if not (self.config["ignore_self"] and data.get("is_self", False)):
                message.message = await self.converter.incoming(
                    [{"type": "file", "data": {**data, "is_self_send": data.get("is_self", False)}}], scene, peer
                )
            else:
                return
        self.commit_event(self.create_event(message))

    def _remember(self, key):
        self._seen[key] = None
        if len(self._seen) > 2048:
            self._seen.popitem(last=False)

    def _convert_other_event(self, event):
        data = event["data"]
        message = AstrBotMessage()
        message.self_id = str(event.get("self_id", ""))
        message.message_id = f"event:{event['event_type']}:{event.get('time', 0)}"
        other_type = getattr(MessageType, "OTHER_MESSAGE", MessageType.FRIEND_MESSAGE)
        message.type = other_type
        scene = data.get("message_scene")
        peer = data.get("peer_id", data.get("group_id", data.get("user_id", "")))
        message.session_id = str(peer) if peer != "" else "system"
        sender = data.get("sender_id", data.get("initiator_id", data.get("user_id", "")))
        message.sender = MessageMember(str(sender), str(sender))
        message.message_str = f"[Milky event: {event['event_type']}]"
        message.message = [C.Plain(message.message_str)]
        message.timestamp = int(event.get("time", 0))
        message.raw_message = event
        if scene == "group" or data.get("group_id") is not None:
            group_id = data.get("peer_id", data.get("group_id"))
            if group_id is not None:
                message.group = Group(group_id=str(group_id))
        return message

    def _connected(self):
        self.clear_errors()
        # Avoid a hard dependency on status support in older AstrBot releases.
        try:
            from astrbot.core.platform.platform import PlatformStatus
            self.status = PlatformStatus.RUNNING
        except ImportError:
            pass
        logger.info("Milky event connection established")

    async def run(self):
        self._task = asyncio.current_task()
        delay = self.reconnect_interval
        try:
            while not self._stop.is_set():
                try:
                    login = await self.client.call_api("get_login_info")
                    self.self_id = str(login["uin"])
                    async for event in self.client.events(self._connected):
                        delay = self.reconnect_interval
                        if self._stop.is_set():
                            break
                        try:
                            await self.handle_event(event)
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            logger.warning("Milky event rejected (%s)", type(exc).__name__)
                    if not self._stop.is_set():
                        raise ConnectionError("Event stream closed")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if self._stop.is_set():
                        break
                    error = f"Milky disconnected ({type(exc).__name__}); retry in {delay:g}s"
                    # Keep persistent failure history bounded.
                    self.clear_errors()
                    self.record_error(error)
                    logger.warning(error)
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=delay)
                    except asyncio.TimeoutError:
                        pass
                    delay = min(delay * 2, max(60, self.reconnect_interval))
        finally:
            await self.client.close()
            self._task = None
            try:
                from astrbot.core.platform.platform import PlatformStatus
                self.status = PlatformStatus.STOPPED
            except ImportError:
                pass

    async def terminate(self):
        self._stop.set()
        if self._task is not None and self._task is not asyncio.current_task():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.client.close()

    async def send_by_session(self, session, message_chain):
        if session.message_type == MessageType.GROUP_MESSAGE:
            # AstrBot's unique-session mode uses sender_group IDs.
            scene, peer = "group", session.session_id.rsplit("_", 1)[-1]
        elif session.message_type == MessageType.FRIEND_MESSAGE:
            scene, peer = "friend", session.session_id
        else:
            raise ValueError("Unsupported Milky session type")
        if str(peer).startswith("temp_"):
            raise ValueError("Temporary sessions do not support sending")
        await self.converter.send(scene, int(peer), message_chain.chain)
        await super().send_by_session(session, message_chain)
