"""Offline contract tests against the stable Milky v1.3.0 API inventory.

No AstrBot, HTTP client, external schema or network access is required.
The independent inventory is transcribed from the official tag's five API files.
"""
from __future__ import annotations

import ast
import inspect
import unittest

from milky_api import MilkyAPIMixin


# Each line contains API name, required fields, then defaulted fields in the
# specification's order. A None default represents an optional, omitted field.
CONTRACT = """
get_login_info |
get_impl_info |
get_user_profile user_id |
get_friend_list | no_cache=False
get_friend_info user_id | no_cache=False
get_group_list | no_cache=False
get_group_info group_id | no_cache=False
get_group_member_list group_id | no_cache=False
get_group_member_info group_id user_id | no_cache=False
get_peer_pins |
set_peer_pin message_scene peer_id | is_pinned=True
set_avatar uri |
set_nickname new_nickname |
set_bio new_bio |
get_custom_face_url_list |
get_cookies domain |
get_csrf_token |
send_private_message user_id message |
send_group_message group_id message |
recall_private_message user_id message_seq |
recall_group_message group_id message_seq |
get_message message_scene peer_id message_seq |
get_history_messages message_scene peer_id | start_message_seq=None limit=20
get_resource_temp_url resource_id |
get_forwarded_messages forward_id |
mark_message_as_read message_scene peer_id message_seq |
send_friend_nudge user_id | is_self=False
send_profile_like user_id | count=1
delete_friend user_id |
get_friend_requests | limit=20 is_filtered=False
accept_friend_request initiator_uid | is_filtered=False
reject_friend_request initiator_uid | is_filtered=False reason=None
set_group_name group_id new_group_name |
set_group_avatar group_id image_uri |
set_group_member_card group_id user_id card |
set_group_member_special_title group_id user_id special_title |
set_group_member_admin group_id user_id | is_set=True
set_group_member_mute group_id user_id | duration=0
set_group_whole_mute group_id | is_mute=True
kick_group_member group_id user_id | reject_add_request=False
get_group_announcements group_id |
send_group_announcement group_id content | image_uri=None
delete_group_announcement group_id announcement_id |
get_group_essence_messages group_id page_index page_size |
set_group_essence_message group_id message_seq | is_set=True
quit_group group_id |
send_group_message_reaction group_id message_seq reaction | reaction_type='face' is_add=True
send_group_nudge group_id user_id |
get_group_notifications | start_notification_seq=None is_filtered=False limit=20
accept_group_request notification_seq notification_type group_id | is_filtered=False
reject_group_request notification_seq notification_type group_id | is_filtered=False reason=None
accept_group_invitation group_id invitation_seq |
reject_group_invitation group_id invitation_seq |
upload_private_file user_id file_uri file_name |
upload_group_file group_id file_uri file_name | parent_folder_id='/'
get_private_file_download_url user_id file_id file_hash | is_self_send=False
get_group_file_download_url group_id file_id |
get_group_files group_id | parent_folder_id='/'
move_group_file group_id file_id | parent_folder_id='/' target_folder_id='/'
rename_group_file group_id file_id new_file_name | parent_folder_id='/'
delete_group_file group_id file_id |
persist_group_file group_id file_id |
create_group_folder group_id folder_name |
rename_group_folder group_id folder_id new_folder_name |
delete_group_folder group_id folder_id |
"""


def contracts():
    for line in CONTRACT.strip().splitlines():
        required, defaulted = line.split("|")
        name, *fields = required.split()
        defaults = {}
        for field in defaulted.split():
            key, value = field.split("=", 1)
            defaults[key] = ast.literal_eval(value)
        yield name, fields, defaults


def sample(field):
    if field == "message":
        return [{"type": "text", "data": {"text": "contract test"}}]
    if field == "message_scene":
        return "group"
    if field == "notification_type":
        return "join_request"
    if field in {"user_id", "group_id", "peer_id", "page_index", "page_size"} or field.endswith("_seq"):
        return 123
    return "value-" + field


class RecordingAPI(MilkyAPIMixin):
    def __init__(self):
        self.calls = []
        self.response = {"unchanged": {"result": []}}

    async def call_api(self, api, **params):
        self.calls.append((api, params))
        return self.response


class MilkyAPITests(unittest.IsolatedAsyncioTestCase):
    def test_complete_explicit_async_inventory(self):
        expected = {name for name, _, _ in contracts()}
        actual = {name for name in vars(MilkyAPIMixin) if not name.startswith("_")}
        self.assertEqual(len(expected), 65)
        self.assertEqual(actual, expected)
        for name, required, defaults in contracts():
            with self.subTest(api=name):
                method = getattr(MilkyAPIMixin, name)
                self.assertTrue(inspect.iscoroutinefunction(method))
                params = dict(inspect.signature(method).parameters)
                params.pop("self")
                self.assertEqual(set(params), set(required) | set(defaults))
                self.assertFalse(any(p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) for p in params.values()))
                for field in required:
                    self.assertIs(params[field].default, inspect.Parameter.empty)
                for field, value in defaults.items():
                    self.assertEqual(params[field].default, value)

    async def test_every_route_required_parameters_and_defaults(self):
        for name, required, defaults in contracts():
            with self.subTest(api=name):
                api = RecordingAPI()
                supplied = {field: sample(field) for field in required}
                result = await getattr(api, name)(**supplied)
                expected = supplied | {key: value for key, value in defaults.items() if value is not None}
                self.assertEqual(api.calls, [(name, expected)])
                self.assertIs(result, api.response)

    async def test_every_route_with_all_explicit_parameters(self):
        for name, required, defaults in contracts():
            with self.subTest(api=name):
                api = RecordingAPI()
                supplied = {field: sample(field) for field in required}
                for field, default in defaults.items():
                    if isinstance(default, bool):
                        supplied[field] = not default
                    elif isinstance(default, int):
                        supplied[field] = default + 1
                    else:
                        supplied[field] = sample(field)
                self.assertIs(await getattr(api, name)(**supplied), api.response)
                self.assertEqual(api.calls, [(name, supplied)])

    async def test_every_optional_none_is_omitted_and_falsy_values_are_kept(self):
        seen = set()
        for name, required, defaults in contracts():
            for optional, default in defaults.items():
                if default is not None:
                    continue
                seen.add((name, optional))
                for value in (None, 0 if optional.endswith("_seq") else ""):
                    with self.subTest(api=name, optional=optional, value=value):
                        api = RecordingAPI()
                        supplied = {field: sample(field) for field in required}
                        supplied[optional] = value
                        await getattr(api, name)(**supplied)
                        expected = {key: val for key, val in defaults.items() if val is not None}
                        expected.update({field: sample(field) for field in required})
                        if value is not None:
                            expected[optional] = value
                        self.assertEqual(api.calls, [(name, expected)])
        self.assertEqual(len(seen), 5)

    async def test_every_required_parameter_is_required(self):
        for name, required, _ in contracts():
            for missing in required:
                with self.subTest(api=name, missing=missing):
                    api = RecordingAPI()
                    supplied = {field: sample(field) for field in required if field != missing}
                    with self.assertRaises(TypeError):
                        await getattr(api, name)(**supplied)
                    self.assertEqual(api.calls, [])

    async def test_required_none_is_not_globally_filtered(self):
        # No v1.3.0 API input is nullable. Required fields are nevertheless not
        # stripped by a blanket None filter; validation belongs to the server.
        api = RecordingAPI()
        await api.set_group_member_card(group_id=123, user_id=456, card=None)
        self.assertEqual(api.calls, [("set_group_member_card", {"group_id": 123, "user_id": 456, "card": None})])

    async def test_transport_error_is_propagated(self):
        class FailingAPI(MilkyAPIMixin):
            async def call_api(self, api, **params):
                raise RuntimeError("transport failed")

        with self.assertRaisesRegex(RuntimeError, "transport failed"):
            await FailingAPI().get_login_info()


if __name__ == "__main__":
    unittest.main()
