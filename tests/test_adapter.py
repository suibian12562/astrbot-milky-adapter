"""Contract tests using minimal AstrBot doubles, not a full AstrBot runtime."""
import asyncio
import importlib
import logging
import sys
import tempfile
import types
import unittest
from enum import Enum
from pathlib import Path
from unittest.mock import patch


class Component:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class Plain(Component):
    def __init__(self, text):
        self.text = text


class At(Component):
    pass


class AtAll(At):
    def __init__(self):
        self.qq = "all"


class File(Component):
    async def get_file(self, allow_return_url=False):
        return self.url


class MessageType(Enum):
    FRIEND_MESSAGE = "FriendMessage"
    GROUP_MESSAGE = "GroupMessage"
    OTHER_MESSAGE = "OtherMessage"


class Platform:
    def __init__(self, config, event_queue):
        self.config, self._event_queue = config, event_queue
        self.errors = []
        self.client_self_id = "stable-platform-task-id"

    def commit_event(self, event):
        self._event_queue.put_nowait(event)

    def clear_errors(self):
        self.errors.clear()

    def record_error(self, message):
        self.errors.append(message)

    async def send_by_session(self, session, chain):
        pass


class Event:
    def __init__(self, message_str, message, meta, session):
        self.message_obj = message

    async def send(self, message):
        pass


class FakeClient:
    def __init__(self):
        self.calls = []
        self.error = None

    async def call_api(self, api, **params):
        self.calls.append((api, params))
        if self.error:
            raise self.error
        return {"url": "https://example.com/media", "download_url": "https://example.com/file"}


def load_adapter():
    components = types.ModuleType("astrbot.api.message_components")
    components.Plain, components.At, components.AtAll, components.File = Plain, At, AtAll, File
    for name in ["Image", "Record", "Video", "Face", "Reply", "Forward", "Node", "Nodes"]:
        setattr(components, name, type(name, (Component,), {}))
    api = types.ModuleType("astrbot.api")
    api.logger, api.message_components = logging.getLogger("test"), components
    platform = types.ModuleType("astrbot.api.platform")
    for name, value in {"AstrBotMessage": Component, "AstrMessageEvent": Event,
                        "Group": Component, "MessageMember": lambda user_id, nickname: Component(user_id=user_id, nickname=nickname),
                        "MessageType": MessageType, "Platform": Platform, "PlatformMetadata": Component,
                        "register_platform_adapter": lambda *a, **k: lambda cls: cls}.items():
        setattr(platform, name, value)
    package = types.ModuleType("milky_under_test")
    package.__path__ = [str(Path(__file__).resolve().parents[1])]
    modules = {"astrbot": types.ModuleType("astrbot"), "astrbot.api": api,
               "astrbot.api.message_components": components, "astrbot.api.platform": platform,
               "milky_under_test": package}
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        adapter = importlib.import_module("milky_under_test.adapter")
    finally:
        for name, old in previous.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
    return adapter, components


adapter, C = load_adapter()
converter_module = sys.modules["milky_under_test.converter"]


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.queue = asyncio.Queue()
        self.adapter = adapter.MilkyAdapter({}, {}, self.queue)
        self.client = FakeClient()
        self.adapter.converter.client = self.client
        self.converter = self.adapter.converter

    def event(self, scene="group", peer=100, seq=1):
        return {"self_id": 9, "time": 10, "event_type": "message_receive", "data": {
            "message_scene": scene, "peer_id": peer, "message_seq": seq,
            "sender_id": 2, "time": 10, "segments": [
                {"type": "mention", "data": {"user_id": 9, "name": "bot"}},
                {"type": "text", "data": {"text": "hello"}}],
            "group": {"group_name": "test"}, "group_member": {"card": "Alice"}}}

    async def test_message_mapping_and_scoped_deduplication(self):
        await self.adapter.handle_event(self.event())
        await self.adapter.handle_event(self.event())
        await self.adapter.handle_event(self.event(peer=101))
        self.assertEqual(self.queue.qsize(), 2)
        message = self.queue.get_nowait().message_obj
        self.assertEqual(message.group.group_id, "100")
        self.assertEqual(message.sender.nickname, "Alice")
        self.assertEqual(message.message_id, "group:100:1")
        self.assertEqual(message.message_str, "hello")
        self.assertIsInstance(message.message[0], C.At)

    async def test_private_and_temp_sessions_are_separate(self):
        friend = await self.adapter.convert_message(self.event("friend", peer=2))
        temp = await self.adapter.convert_message(self.event("temp", peer=2))
        self.assertEqual(friend.session_id, "2")
        self.assertTrue(temp.session_id.startswith("temp_"))
        with self.assertRaises(ValueError):
            await self.converter.send("temp", 2, [C.Plain("hello")])

    async def test_self_and_nonmessage_ignored(self):
        event = self.event()
        event["data"]["sender_id"] = 9
        self.assertIsNone(await self.adapter.convert_message(event))
        await self.adapter.handle_event({"event_type": "heartbeat"})
        self.assertTrue(self.queue.empty())

    async def test_notifications_preserve_raw_and_do_not_drop_repeated_actions(self):
        event = {"event_type": "group_member_increase", "self_id": 9, "time": 10,
                 "data": {"group_id": 100, "user_id": 2, "operator_id": None}}
        await self.adapter.handle_event(event)
        await self.adapter.handle_event(event)
        self.assertEqual(self.queue.qsize(), 2)
        message = self.queue.get_nowait().message_obj
        self.assertEqual(message.type, MessageType.OTHER_MESSAGE)
        self.assertIs(message.raw_message, event)
        self.assertEqual(message.group.group_id, "100")

    async def test_friend_file_event_uses_download_api(self):
        await self.adapter.handle_event({"event_type": "friend_file_upload", "self_id": 9, "time": 10,
                                        "data": {"user_id": 2, "file_id": "f", "file_name": "a", "file_hash": "hash", "is_self": False}})
        message = self.queue.get_nowait().message_obj
        self.assertIsInstance(message.message[0], C.File)
        self.assertEqual(self.client.calls[-1], ("get_private_file_download_url", {"user_id": 2, "file_id": "f", "file_hash": "hash", "is_self_send": False}))

    async def test_group_information_and_member_roles(self):
        class GroupClient(FakeClient):
            async def call_api(self, api, **params):
                if api == "get_group_info":
                    return {"group": {"group_name": "New", "member_count": 3}}
                return {"members": [{"user_id": 1, "nickname": "Owner", "role": "owner"},
                                    {"user_id": 2, "card": "Admin", "role": "admin"}]}
        self.adapter.client = GroupClient()
        event = self.adapter.create_event(await self.adapter.convert_message(self.event()))
        group = await event.get_group()
        self.assertEqual(group.group_name, "New")
        self.assertEqual(group.group_owner, "1")
        self.assertEqual(group.group_admins, ["2"])
        self.assertEqual(group.members[1].nickname, "Admin")

    async def test_forward_expansion_and_depth_limit(self):
        class ForwardClient(FakeClient):
            async def call_api(self, api, **params):
                return {"messages": [{"sender_name": "Alice", "time": 10,
                                      "segments": [{"type": "text", "data": {"text": "old"}}]}]}
        self.converter.client = ForwardClient()
        result = await self.converter.incoming([{"type": "forward", "data": {"forward_id": "f"}}], "group", 100)
        self.assertIsInstance(result[0], C.Nodes)
        self.assertEqual(result[0].nodes[0].uin, "0")
        self.assertEqual(result[0].nodes[0].content[0].text, "old")
        result = await self.converter.incoming([], "group", 100, depth=9)
        self.assertIn("nesting limit", result[0].text)

    async def test_outgoing_basic_segments(self):
        result = await self.converter.outgoing([
            C.Plain("hello"), C.At(qq="12"), C.AtAll(), C.Face(id=14),
            C.Reply(id="group:100:42"), C.Image(file="https://example.com/a.png")])
        self.assertEqual([s["type"] for s in result], ["text", "mention", "mention_all", "face", "reply", "image"])
        self.assertEqual(result[4]["data"], {"message_seq": 42})
        self.assertEqual(result[5]["data"], {"uri": "https://example.com/a.png"})

    async def test_files_preserve_order_and_use_upload_api(self):
        await self.converter.send("group", 100, [C.Plain("before"), C.File(name="a.txt", url="https://example.com/a"), C.Plain("after")])
        self.assertEqual([c[0] for c in self.client.calls], ["send_group_message", "upload_group_file", "send_group_message"])
        self.assertEqual(self.client.calls[1][1], {"group_id": 100, "file_name": "a.txt", "file_uri": "https://example.com/a"})

    async def test_unsupported_outgoing_preflight_has_no_side_effects(self):
        with self.assertRaises(ValueError):
            await self.converter.send("friend", 2, [C.Plain("hello"), object()])
        self.assertEqual(self.client.calls, [])

    async def test_forward_node_structure(self):
        result = await self.converter.outgoing([C.Nodes(nodes=[C.Node(uin="2", name="Alice", time=10, content=[C.Plain("hello")])])])
        node = result[0]["data"]["messages"][0]
        self.assertEqual(node, {"user_id": 2, "sender_name": "Alice", "time": 10, "segments": [{"type": "text", "data": {"text": "hello"}}]})

    async def test_media_reply_file_and_unknown_incoming(self):
        result = await self.converter.incoming([
            {"type": "image", "data": {"resource_id": "r"}},
            {"type": "reply", "data": {"message_seq": 3, "sender_id": 4, "segments": [{"type": "text", "data": {"text": "old"}}]}},
            {"type": "file", "data": {"file_name": "a", "file_id": "f"}},
            {"type": "future", "data": {}},
        ], "group", 100)
        self.assertEqual(result[0].url, "https://example.com/media")
        self.assertEqual(result[1].id, "group:100:3")
        self.assertEqual(result[1].message_str, "old")
        self.assertEqual(result[2].url, "https://example.com/file")
        self.assertIn("unsupported", result[3].text)

    async def test_resource_failure_keeps_rest_of_message(self):
        self.client.error = asyncio.TimeoutError()
        result = await self.converter.incoming([{"type": "image", "data": {"resource_id": "r"}}, {"type": "text", "data": {"text": "still here"}}], "friend", 2)
        self.assertIn("unavailable", result[0].text)
        self.assertEqual(result[1].text, "still here")

    async def test_local_media_upload_limits_and_file_uri(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "a b.bin"
            path.write_bytes(b"abc")
            self.assertEqual(await converter_module.media_uri(path.as_uri(), 3), "base64://YWJj")
            with self.assertRaises(ValueError):
                await converter_module.media_uri(str(path), 2)
        with self.assertRaises(ValueError):
            await converter_module.media_uri("base64://YWJjYWJj", 3)

    async def test_base64_exact_size_and_validation(self):
        self.assertEqual(await converter_module.media_uri("base64://YQ==", 1), "base64://YQ==")
        with self.assertRaises(ValueError):
            await converter_module.media_uri("base64://YWI=", 1)
        with self.assertRaises(ValueError):
            await converter_module.media_uri("base64://!!!!", 100)

    async def test_malformed_segments_preserve_following_text(self):
        result = await self.converter.incoming([None, {"type": "image", "data": None}, {"type": "text", "data": {"text": "hello"}}], "friend", 2)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[-1].text, "hello")

    async def test_proactive_group_unique_session(self):
        session = Component(message_type=MessageType.GROUP_MESSAGE, session_id="2_100")
        await self.adapter.send_by_session(session, Component(chain=[C.Plain("hello")]))
        self.assertEqual(self.client.calls[0][1]["group_id"], 100)

    async def test_login_preserves_platform_task_identity(self):
        connected = asyncio.Event()
        class LoggedInClient:
            closed = False
            async def call_api(self, api):
                return {"uin": 12345}
            async def events(self, callback):
                callback()
                connected.set()
                await asyncio.Event().wait()
                yield {}
            async def close(self):
                self.closed = True
        self.adapter.client = LoggedInClient()
        task_id = self.adapter.client_self_id
        task = asyncio.create_task(self.adapter.run())
        try:
            await asyncio.wait_for(connected.wait(), 2)
            self.assertEqual(self.adapter.client_self_id, task_id)
            self.assertEqual(self.adapter.self_id, "12345")
        finally:
            await self.adapter.terminate()
            await asyncio.gather(task, return_exceptions=True)

    async def test_terminate_interrupts_idle_run(self):
        started = asyncio.Event()
        class WaitingClient:
            closed = False
            async def call_api(self, api):
                started.set()
                await asyncio.Event().wait()
            async def close(self):
                self.closed = True
        self.adapter.client = WaitingClient()
        task = asyncio.create_task(self.adapter.run())
        await asyncio.wait_for(started.wait(), 2)
        await asyncio.wait_for(self.adapter.terminate(), 2)
        self.assertTrue(task.done())
        self.assertTrue(self.adapter.client.closed)


if __name__ == "__main__":
    unittest.main()
