"""Integration tests for the Milky HTTP and forward WebSocket client."""
from __future__ import annotations

import asyncio
import unittest

from aiohttp import web

from milky_client import MilkyClient, MilkyError, endpoints


class MilkyClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.ws_requests = []
        self.response = web.json_response(
            {"status": "ok", "retcode": 0, "data": {"user_id": 123}}
        )
        self.frames = []
        self.hold_ws = False
        self.ws_ready = asyncio.Event()
        self.clients = []
        app = web.Application()
        app.router.add_post("/api/{api}", self.handle_api)
        app.router.add_get("/event", self.handle_events)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        try:
            site = web.TCPSite(self.runner, "127.0.0.1", 0)
            await site.start()
        except BaseException:
            await self.runner.cleanup()
            raise
        self.base_url = f"http://127.0.0.1:{self.runner.addresses[0][1]}"

    async def asyncTearDown(self):
        try:
            for client in self.clients:
                await client.close()
        finally:
            await self.runner.cleanup()

    def make_client(self, **kwargs):
        client = MilkyClient(self.base_url, **kwargs)
        self.clients.append(client)
        return client

    async def handle_api(self, request):
        self.requests.append(
            {
                "api": request.match_info["api"],
                "authorization": request.headers.get("Authorization"),
                "content_type": request.content_type,
                "query": dict(request.query),
                "body": await request.json(),
            }
        )
        return self.response

    async def handle_events(self, request):
        self.ws_requests.append(
            {
                "authorization": request.headers.get("Authorization"),
                "query": dict(request.query),
            }
        )
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        for frame in self.frames:
            if isinstance(frame, bytes):
                await ws.send_bytes(frame)
            else:
                await ws.send_str(frame)
        self.ws_ready.set()
        if self.hold_ws:
            async for _ in ws:
                pass
        else:
            await ws.close()
        return ws

    async def assert_api_error(self, response, expected_code):
        self.response = response
        with self.assertRaises(MilkyError) as caught:
            await self.make_client().call_api("get_login_info")
        self.assertEqual(caught.exception.api, "get_login_info")
        self.assertEqual(caught.exception.retcode, expected_code)
        return caught.exception

    async def test_api_authentication_and_json_body(self):
        client = self.make_client(access_token="secret-token")
        result = await client.call_api(
            "send_private_message", user_id=42,
            message=[{"type": "text", "data": {"text": "hello"}}],
        )
        self.assertEqual(result, {"user_id": 123})
        self.assertEqual(self.requests, [{
            "api": "send_private_message",
            "authorization": "Bearer secret-token",
            "content_type": "application/json",
            "query": {},
            "body": {
                "user_id": 42,
                "message": [{"type": "text", "data": {"text": "hello"}}],
            },
        }])

    async def test_no_token_omits_authorization_and_empty_params_are_object(self):
        await self.make_client().call_api("get_login_info")
        self.assertIsNone(self.requests[0]["authorization"])
        self.assertEqual(self.requests[0]["body"], {})

    async def test_business_error_does_not_expose_response_body(self):
        error = await self.assert_api_error(web.json_response({
            "status": "failed", "retcode": 10001,
            "message": "private-response-secret",
        }), 10001)
        self.assertNotIn("private-response-secret", str(error))
        self.assertIn("get_login_info", str(error))
        self.assertIn("10001", str(error))

    async def test_invalid_success_envelopes(self):
        cases = [
            ([], "invalid_envelope"),
            (None, "invalid_envelope"),
            ({"status": "failed", "retcode": "bad"}, "invalid_retcode"),
            ({"status": "failed"}, "invalid_retcode"),
            ({"status": "failed", "retcode": 0}, 0),
            ({"status": "ok", "retcode": 5}, 5),
            ({"status": "ok", "retcode": 0, "data": []}, "invalid_data"),
            ({"status": "ok", "retcode": 0, "data": None}, "invalid_data"),
        ]
        for payload, code in cases:
            with self.subTest(payload=payload):
                await self.assert_api_error(web.json_response(payload), code)

    async def test_success_without_data_returns_empty_object(self):
        self.response = web.json_response({"status": "ok", "retcode": 0})
        self.assertEqual(await self.make_client().call_api("get_login_info"), {})

    async def test_non_json_responses(self):
        cases = [
            web.Response(text="not JSON", content_type="application/json"),
            web.Response(text='{"status":"ok","retcode":0}', content_type="text/plain"),
        ]
        for response in cases:
            with self.subTest(content_type=response.content_type):
                await self.assert_api_error(response, "invalid_json")

    async def test_http_errors_and_redirects_are_not_followed(self):
        for status in (302, 401, 403, 404, 500):
            with self.subTest(status=status):
                before = len(self.requests)
                error = await self.assert_api_error(web.Response(
                    status=status, text="private-http-secret",
                    headers={"Location": self.base_url + "/api/redirect_target"},
                ), status)
                self.assertNotIn("private-http-secret", str(error))
                self.assertEqual(len(self.requests), before + 1)
                self.assertEqual(self.requests[-1]["api"], "get_login_info")

    async def test_invalid_api_names_do_not_send_requests(self):
        client = self.make_client()
        for api in ("", "../secret", "get/info", "get?token=x", "bad-name"):
            with self.subTest(api=api):
                with self.assertRaises(ValueError):
                    await client.call_api(api)
        self.assertEqual(self.requests, [])

    async def test_websocket_authentication_bad_frames_and_events(self):
        self.frames = [
            "not-json", "[]", "null", "42", '"text"',
            b'{"event_type":"binary_must_be_ignored"}',
            '{"event_type":"message_receive","data":{"message_id":7}}',
            "{broken", '{"event_type":"heartbeat","data":{}}',
        ]
        connected = []
        client = self.make_client(access_token="ws-secret")

        async def collect():
            return [event async for event in client.events(
                connected=lambda: connected.append(True)
            )]

        events = await asyncio.wait_for(collect(), timeout=5)
        self.assertEqual(events, [
            {"event_type": "message_receive", "data": {"message_id": 7}},
            {"event_type": "heartbeat", "data": {}},
        ])
        self.assertEqual(connected, [True])
        self.assertEqual(self.ws_requests, [{
            "authorization": "Bearer ws-secret", "query": {},
        }])
        self.assertIsNone(client._ws)

    async def test_websocket_without_token(self):
        async def collect():
            return [event async for event in self.make_client().events()]

        self.assertEqual(await asyncio.wait_for(collect(), timeout=5), [])
        self.assertIsNone(self.ws_requests[0]["authorization"])

    async def test_close_active_websocket_and_session(self):
        self.hold_ws = True
        client = self.make_client()
        connected = asyncio.Event()

        async def consume():
            return [event async for event in client.events(connected=connected.set)]

        task = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(connected.wait(), timeout=5)
            session = client._session
            ws = client._ws
            await asyncio.wait_for(client.close(), timeout=5)
            self.assertEqual(await asyncio.wait_for(task, timeout=5), [])
            self.assertTrue(session.closed)
            self.assertTrue(ws.closed)
            self.assertIsNone(client._ws)
            await client.close()
            with self.assertRaises(RuntimeError):
                await client.start()
            with self.assertRaises(RuntimeError):
                await client.call_api("get_login_info")
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_close_before_start_is_idempotent(self):
        client = self.make_client()
        await client.close()
        await client.close()
        self.assertIsNone(client._session)
        with self.assertRaises(RuntimeError):
            await client.start()

    async def test_start_reuses_session_and_close_releases_it(self):
        client = self.make_client()
        await client.start()
        session = client._session
        await client.start()
        self.assertIs(client._session, session)
        await client.close()
        self.assertTrue(session.closed)

    def test_endpoints_normalization(self):
        cases = [
            ("http://localhost:3000", "", "http://localhost:3000/api", "ws://localhost:3000/event"),
            (" http://localhost:3000/api/ ", "", "http://localhost:3000/api", "ws://localhost:3000/event"),
            ("https://example.com/prefix/api", "", "https://example.com/prefix/api", "wss://example.com/prefix/event"),
            ("http://[::1]:3000/", "", "http://[::1]:3000/api", "ws://[::1]:3000/event"),
            ("https://example.com", " ws://localhost:4000/custom ", "https://example.com/api", "ws://localhost:4000/custom"),
        ]
        for base, event, expected_api, expected_event in cases:
            with self.subTest(base=base, event=event):
                self.assertEqual(endpoints(base, event), (expected_api, expected_event))

    def test_invalid_base_endpoints(self):
        for base in (
            "", "localhost:3000", "ws://localhost", "ftp://localhost", "http://",
            "http://user:secret@localhost", "http://localhost?token=secret",
            "http://localhost/#fragment",
        ):
            with self.subTest(base=base):
                with self.assertRaises(ValueError):
                    endpoints(base)

    def test_invalid_event_endpoints(self):
        for event in (
            "localhost:3000/event", "http://localhost/event", "ws://",
            "wss://user:secret@localhost/event", "ws://localhost/event?token=secret",
            "ws://localhost/event#fragment",
        ):
            with self.subTest(event=event):
                with self.assertRaises(ValueError):
                    endpoints("http://localhost", event)

    def test_invalid_timeouts(self):
        for timeout in (0, -1, float("inf"), float("-inf"), float("nan")):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    self.make_client(timeout=timeout)


if __name__ == "__main__":
    unittest.main()
