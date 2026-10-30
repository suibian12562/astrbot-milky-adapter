"""Explicit Milky 1.3 stable HTTP API methods.

Source: SaltifyDev/milky tag v1.3.0, protocol/src/ir/api/{system,message,
friend,group,file}.ts. Responses are unmodified dictionaries, not models.
The owning transport must implement async call_api(api: str, **params) -> dict.
"""
from __future__ import annotations


class MilkyAPIMixin:
    """All 65 stable APIs; transport, authentication and validation stay in call_api."""

    # System APIs.
    async def get_login_info(self) -> dict:
        return await self.call_api("get_login_info")

    async def get_impl_info(self) -> dict:
        return await self.call_api("get_impl_info")

    async def get_user_profile(self, user_id: int) -> dict:
        return await self.call_api("get_user_profile", user_id=user_id)

    async def get_friend_list(self, no_cache: bool = False) -> dict:
        return await self.call_api("get_friend_list", no_cache=no_cache)

    async def get_friend_info(self, user_id: int, no_cache: bool = False) -> dict:
        return await self.call_api("get_friend_info", user_id=user_id, no_cache=no_cache)

    async def get_group_list(self, no_cache: bool = False) -> dict:
        return await self.call_api("get_group_list", no_cache=no_cache)

    async def get_group_info(self, group_id: int, no_cache: bool = False) -> dict:
        return await self.call_api("get_group_info", group_id=group_id, no_cache=no_cache)

    async def get_group_member_list(self, group_id: int, no_cache: bool = False) -> dict:
        return await self.call_api("get_group_member_list", group_id=group_id, no_cache=no_cache)

    async def get_group_member_info(self, group_id: int, user_id: int, no_cache: bool = False) -> dict:
        return await self.call_api("get_group_member_info", group_id=group_id, user_id=user_id, no_cache=no_cache)

    async def get_peer_pins(self) -> dict:
        return await self.call_api("get_peer_pins")

    async def set_peer_pin(self, message_scene: str, peer_id: int, is_pinned: bool = True) -> dict:
        return await self.call_api("set_peer_pin", message_scene=message_scene, peer_id=peer_id, is_pinned=is_pinned)

    async def set_avatar(self, uri: str) -> dict:
        return await self.call_api("set_avatar", uri=uri)

    async def set_nickname(self, new_nickname: str) -> dict:
        return await self.call_api("set_nickname", new_nickname=new_nickname)

    async def set_bio(self, new_bio: str) -> dict:
        return await self.call_api("set_bio", new_bio=new_bio)

    async def get_custom_face_url_list(self) -> dict:
        return await self.call_api("get_custom_face_url_list")

    async def get_cookies(self, domain: str) -> dict:
        return await self.call_api("get_cookies", domain=domain)

    async def get_csrf_token(self) -> dict:
        return await self.call_api("get_csrf_token")

    # Message APIs.
    async def send_private_message(self, user_id: int, message: list[dict]) -> dict:
        return await self.call_api("send_private_message", user_id=user_id, message=message)

    async def send_group_message(self, group_id: int, message: list[dict]) -> dict:
        return await self.call_api("send_group_message", group_id=group_id, message=message)

    async def recall_private_message(self, user_id: int, message_seq: int) -> dict:
        return await self.call_api("recall_private_message", user_id=user_id, message_seq=message_seq)

    async def recall_group_message(self, group_id: int, message_seq: int) -> dict:
        return await self.call_api("recall_group_message", group_id=group_id, message_seq=message_seq)

    async def get_message(self, message_scene: str, peer_id: int, message_seq: int) -> dict:
        return await self.call_api("get_message", message_scene=message_scene, peer_id=peer_id, message_seq=message_seq)

    async def get_history_messages(self, message_scene: str, peer_id: int, start_message_seq: int | None = None, limit: int = 20) -> dict:
        params = {} if start_message_seq is None else {"start_message_seq": start_message_seq}
        return await self.call_api("get_history_messages", message_scene=message_scene, peer_id=peer_id, limit=limit, **params)

    async def get_resource_temp_url(self, resource_id: str) -> dict:
        return await self.call_api("get_resource_temp_url", resource_id=resource_id)

    async def get_forwarded_messages(self, forward_id: str) -> dict:
        return await self.call_api("get_forwarded_messages", forward_id=forward_id)

    async def mark_message_as_read(self, message_scene: str, peer_id: int, message_seq: int) -> dict:
        return await self.call_api("mark_message_as_read", message_scene=message_scene, peer_id=peer_id, message_seq=message_seq)

    # Friend APIs.
    async def send_friend_nudge(self, user_id: int, is_self: bool = False) -> dict:
        return await self.call_api("send_friend_nudge", user_id=user_id, is_self=is_self)

    async def send_profile_like(self, user_id: int, count: int = 1) -> dict:
        return await self.call_api("send_profile_like", user_id=user_id, count=count)

    async def delete_friend(self, user_id: int) -> dict:
        return await self.call_api("delete_friend", user_id=user_id)

    async def get_friend_requests(self, limit: int = 20, is_filtered: bool = False) -> dict:
        return await self.call_api("get_friend_requests", limit=limit, is_filtered=is_filtered)

    async def accept_friend_request(self, initiator_uid: str, is_filtered: bool = False) -> dict:
        return await self.call_api("accept_friend_request", initiator_uid=initiator_uid, is_filtered=is_filtered)

    async def reject_friend_request(self, initiator_uid: str, is_filtered: bool = False, reason: str | None = None) -> dict:
        params = {} if reason is None else {"reason": reason}
        return await self.call_api("reject_friend_request", initiator_uid=initiator_uid, is_filtered=is_filtered, **params)

    # Group APIs.
    async def set_group_name(self, group_id: int, new_group_name: str) -> dict:
        return await self.call_api("set_group_name", group_id=group_id, new_group_name=new_group_name)

    async def set_group_avatar(self, group_id: int, image_uri: str) -> dict:
        return await self.call_api("set_group_avatar", group_id=group_id, image_uri=image_uri)

    async def set_group_member_card(self, group_id: int, user_id: int, card: str) -> dict:
        return await self.call_api("set_group_member_card", group_id=group_id, user_id=user_id, card=card)

    async def set_group_member_special_title(self, group_id: int, user_id: int, special_title: str) -> dict:
        return await self.call_api("set_group_member_special_title", group_id=group_id, user_id=user_id, special_title=special_title)

    async def set_group_member_admin(self, group_id: int, user_id: int, is_set: bool = True) -> dict:
        return await self.call_api("set_group_member_admin", group_id=group_id, user_id=user_id, is_set=is_set)

    async def set_group_member_mute(self, group_id: int, user_id: int, duration: int = 0) -> dict:
        return await self.call_api("set_group_member_mute", group_id=group_id, user_id=user_id, duration=duration)

    async def set_group_whole_mute(self, group_id: int, is_mute: bool = True) -> dict:
        return await self.call_api("set_group_whole_mute", group_id=group_id, is_mute=is_mute)

    async def kick_group_member(self, group_id: int, user_id: int, reject_add_request: bool = False) -> dict:
        return await self.call_api("kick_group_member", group_id=group_id, user_id=user_id, reject_add_request=reject_add_request)

    async def get_group_announcements(self, group_id: int) -> dict:
        return await self.call_api("get_group_announcements", group_id=group_id)

    async def send_group_announcement(self, group_id: int, content: str, image_uri: str | None = None) -> dict:
        params = {} if image_uri is None else {"image_uri": image_uri}
        return await self.call_api("send_group_announcement", group_id=group_id, content=content, **params)

    async def delete_group_announcement(self, group_id: int, announcement_id: str) -> dict:
        return await self.call_api("delete_group_announcement", group_id=group_id, announcement_id=announcement_id)

    async def get_group_essence_messages(self, group_id: int, page_index: int, page_size: int) -> dict:
        return await self.call_api("get_group_essence_messages", group_id=group_id, page_index=page_index, page_size=page_size)

    async def set_group_essence_message(self, group_id: int, message_seq: int, is_set: bool = True) -> dict:
        return await self.call_api("set_group_essence_message", group_id=group_id, message_seq=message_seq, is_set=is_set)

    async def quit_group(self, group_id: int) -> dict:
        return await self.call_api("quit_group", group_id=group_id)

    async def send_group_message_reaction(self, group_id: int, message_seq: int, reaction: str, reaction_type: str = "face", is_add: bool = True) -> dict:
        return await self.call_api("send_group_message_reaction", group_id=group_id, message_seq=message_seq, reaction=reaction, reaction_type=reaction_type, is_add=is_add)

    async def send_group_nudge(self, group_id: int, user_id: int) -> dict:
        return await self.call_api("send_group_nudge", group_id=group_id, user_id=user_id)

    async def get_group_notifications(self, start_notification_seq: int | None = None, is_filtered: bool = False, limit: int = 20) -> dict:
        params = {} if start_notification_seq is None else {"start_notification_seq": start_notification_seq}
        return await self.call_api("get_group_notifications", is_filtered=is_filtered, limit=limit, **params)

    async def accept_group_request(self, notification_seq: int, notification_type: str, group_id: int, is_filtered: bool = False) -> dict:
        return await self.call_api("accept_group_request", notification_seq=notification_seq, notification_type=notification_type, group_id=group_id, is_filtered=is_filtered)

    async def reject_group_request(self, notification_seq: int, notification_type: str, group_id: int, is_filtered: bool = False, reason: str | None = None) -> dict:
        params = {} if reason is None else {"reason": reason}
        return await self.call_api("reject_group_request", notification_seq=notification_seq, notification_type=notification_type, group_id=group_id, is_filtered=is_filtered, **params)

    async def accept_group_invitation(self, group_id: int, invitation_seq: int) -> dict:
        return await self.call_api("accept_group_invitation", group_id=group_id, invitation_seq=invitation_seq)

    async def reject_group_invitation(self, group_id: int, invitation_seq: int) -> dict:
        return await self.call_api("reject_group_invitation", group_id=group_id, invitation_seq=invitation_seq)

    # File APIs. Keyword-only arguments preserve the specification's field order
    # when a field with a default precedes a required field.
    async def upload_private_file(self, user_id: int, file_uri: str, file_name: str) -> dict:
        return await self.call_api("upload_private_file", user_id=user_id, file_uri=file_uri, file_name=file_name)

    async def upload_group_file(self, group_id: int, *, parent_folder_id: str = "/", file_uri: str, file_name: str) -> dict:
        return await self.call_api("upload_group_file", group_id=group_id, parent_folder_id=parent_folder_id, file_uri=file_uri, file_name=file_name)

    async def get_private_file_download_url(self, user_id: int, file_id: str, file_hash: str, is_self_send: bool = False) -> dict:
        return await self.call_api("get_private_file_download_url", user_id=user_id, file_id=file_id, file_hash=file_hash, is_self_send=is_self_send)

    async def get_group_file_download_url(self, group_id: int, file_id: str) -> dict:
        return await self.call_api("get_group_file_download_url", group_id=group_id, file_id=file_id)

    async def get_group_files(self, group_id: int, parent_folder_id: str = "/") -> dict:
        return await self.call_api("get_group_files", group_id=group_id, parent_folder_id=parent_folder_id)

    async def move_group_file(self, group_id: int, file_id: str, parent_folder_id: str = "/", target_folder_id: str = "/") -> dict:
        return await self.call_api("move_group_file", group_id=group_id, file_id=file_id, parent_folder_id=parent_folder_id, target_folder_id=target_folder_id)

    async def rename_group_file(self, group_id: int, file_id: str, *, parent_folder_id: str = "/", new_file_name: str) -> dict:
        return await self.call_api("rename_group_file", group_id=group_id, file_id=file_id, parent_folder_id=parent_folder_id, new_file_name=new_file_name)

    async def delete_group_file(self, group_id: int, file_id: str) -> dict:
        return await self.call_api("delete_group_file", group_id=group_id, file_id=file_id)

    async def persist_group_file(self, group_id: int, file_id: str) -> dict:
        return await self.call_api("persist_group_file", group_id=group_id, file_id=file_id)

    async def create_group_folder(self, group_id: int, folder_name: str) -> dict:
        return await self.call_api("create_group_folder", group_id=group_id, folder_name=folder_name)

    async def rename_group_folder(self, group_id: int, folder_id: str, new_folder_name: str) -> dict:
        return await self.call_api("rename_group_folder", group_id=group_id, folder_id=folder_id, new_folder_name=new_folder_name)

    async def delete_group_folder(self, group_id: int, folder_id: str) -> dict:
        return await self.call_api("delete_group_folder", group_id=group_id, folder_id=folder_id)
