"""AstrBot components <-> Milky segments."""
from __future__ import annotations

import asyncio
import base64
import binascii
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from urllib.request import url2pathname

from astrbot.api import message_components as C


async def media_uri(value: str, max_bytes: int) -> str:
    if not value:
        raise ValueError("Empty media source")
    if value.startswith(("http://", "https://", "base64://")):
        if value.startswith("base64://"):
            encoded = value[9:]
            if len(encoded) > ((max_bytes + 2) // 3) * 4:
                raise ValueError("Media exceeds max_upload_mb")
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("Invalid base64 media") from exc
            if len(decoded) > max_bytes:
                raise ValueError("Media exceeds max_upload_mb")
        return value
    if value.startswith("file:"):
        parsed = urlsplit(value)
        if parsed.netloc not in {"", "localhost"}:
            raise ValueError("Remote file URI is not supported")
        value = url2pathname(parsed.path)
    path = Path(value)

    def encode():
        with path.open("rb") as handle:
            content = handle.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError("Media exceeds max_upload_mb")
        return "base64://" + base64.b64encode(content).decode("ascii")

    return await asyncio.to_thread(encode)


def sequence(value) -> int:
    # Full AstrBot IDs are scene:peer:seq; plain sequence IDs also work.
    return int(str(value).rsplit(":", 1)[-1])


class MessageConverter:
    def __init__(self, client, max_upload_bytes=20 * 1024 * 1024):
        self.client = client
        self.max_upload_bytes = max_upload_bytes

    async def outgoing(self, components, depth=0):
        if depth > 8:
            raise ValueError("Forward nesting exceeds 8 levels")
        result = []
        for part in components:
            kind, data = None, {}
            if isinstance(part, C.Plain):
                if not part.text:
                    continue
                kind, data = "text", {"text": part.text}
            elif isinstance(part, C.At):
                kind = "mention_all" if str(part.qq) == "all" else "mention"
                data = {} if kind == "mention_all" else {"user_id": int(part.qq)}
            elif isinstance(part, C.Face):
                kind, data = "face", {"face_id": str(part.id)}
            elif isinstance(part, C.Reply):
                kind, data = "reply", {"message_seq": sequence(part.id)}
            elif isinstance(part, (C.Image, C.Record, C.Video)):
                kind = "image" if isinstance(part, C.Image) else "record" if isinstance(part, C.Record) else "video"
                source = getattr(part, "url", "") or part.file or getattr(part, "path", "")
                data = {"uri": await media_uri(source, self.max_upload_bytes)}
            elif isinstance(part, (C.Node, C.Nodes)):
                nodes = [part] if isinstance(part, C.Node) else part.nodes
                messages = []
                for node in nodes:
                    item = {"user_id": int(node.uin or 0), "sender_name": node.name or "QQ",
                            "segments": await self.outgoing(node.content, depth + 1)}
                    if node.time:
                        item["time"] = int(node.time)
                    messages.append(item)
                kind, data = "forward", {"messages": messages}
            else:
                raise ValueError(f"Unsupported outgoing component: {type(part).__name__}")
            result.append({"type": kind, "data": data})
        return result

    async def send(self, scene: str, peer: int, components):
        if scene not in {"friend", "group"}:
            raise ValueError("Temporary sessions are receive-only; Milky has no temp send API")
        target = {"group_id" if scene == "group" else "user_id": int(peer)}
        # Preflight the entire chain before side effects; preserve file/text ordering.
        operations, pending = [], []
        for part in components:
            if isinstance(part, C.File):
                if pending:
                    operations.append(("send", pending))
                    pending = []
                source = await part.get_file(allow_return_url=True)
                uri = await media_uri(source, self.max_upload_bytes)
                operations.append(("file", {"file_uri": uri, "file_name": part.name or "file"}))
            else:
                pending.extend(await self.outgoing([part]))
        if pending:
            operations.append(("send", pending))
        results = []
        for kind, payload in operations:
            api = ("upload_group_file" if scene == "group" else "upload_private_file") if kind == "file" else (
                "send_group_message" if scene == "group" else "send_private_message")
            params = dict(target)
            params.update(payload if kind == "file" else {"message": payload})
            results.append(await self.client.call_api(api, **params))
        return results

    async def incoming(self, segments, scene, peer, depth=0):
        if depth > 8:
            return [C.Plain("[Milky: nesting limit]")]
        result = []
        for segment in segments:
            if not isinstance(segment, dict):
                result.append(C.Plain("[Milky: malformed segment]"))
                continue
            kind, data = segment.get("type"), segment.get("data", {})
            if not isinstance(data, dict):
                result.append(C.Plain(f"[Milky: malformed {kind}]"))
                continue
            try:
                if kind == "text":
                    part = C.Plain(data["text"])
                elif kind == "mention":
                    part = C.At(qq=str(data["user_id"]), name=data.get("name", ""))
                elif kind == "mention_all":
                    part = C.AtAll()
                elif kind == "face":
                    part = C.Face(id=str(data["face_id"]))
                elif kind in {"image", "record", "video"}:
                    url = data.get("temp_url")
                    if not url:
                        url = (await self.client.call_api("get_resource_temp_url", resource_id=data["resource_id"]))["url"]
                    cls = {"image": C.Image, "record": C.Record, "video": C.Video}[kind]
                    part = cls(file=url, url=url)
                elif kind == "reply":
                    chain = await self.incoming(data.get("segments", []), scene, peer, depth + 1)
                    part = C.Reply(id=f"{scene}:{peer}:{data['message_seq']}", chain=chain,
                                   sender_id=str(data.get("sender_id", 0)),
                                   sender_nickname=data.get("sender_name") or "",
                                   time=data.get("time", 0),
                                   message_str="".join(p.text for p in chain if isinstance(p, C.Plain)))
                elif kind == "forward":
                    nodes = []
                    try:
                        forwarded = await self.client.call_api(
                            "get_forwarded_messages", forward_id=data["forward_id"]
                        )
                    except (RuntimeError, aiohttp.ClientError, asyncio.TimeoutError):
                        result.append(C.Forward(id=data["forward_id"]))
                        continue
                    for item in forwarded.get("messages", []):
                        if not isinstance(item, dict):
                            continue
                        node = C.Node(
                            content=await self.incoming(item.get("segments", []), scene, peer, depth + 1),
                            uin="0", name=item.get("sender_name") or "QQ",
                            time=item.get("time", 0),
                        )
                        nodes.append(node)
                    part = C.Nodes(nodes=nodes) if nodes else C.Forward(id=data["forward_id"])
                elif kind == "file":
                    if scene == "group":
                        info = await self.client.call_api("get_group_file_download_url", group_id=int(peer), file_id=data["file_id"])
                    else:
                        info = await self.client.call_api("get_private_file_download_url", user_id=int(peer),
                                                          file_id=data["file_id"], file_hash=data.get("file_hash"),
                                                          is_self_send=data.get("is_self_send", False))
                    part = C.File(name=data["file_name"], url=info["download_url"])
                else:
                    part = C.Plain(f"[Milky: unsupported {kind}]")
            except (KeyError, TypeError, ValueError, RuntimeError, aiohttp.ClientError, asyncio.TimeoutError):
                part = C.Plain(f"[Milky: unavailable {kind}]")
            result.append(part)
        return result
