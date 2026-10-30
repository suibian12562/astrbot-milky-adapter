# AstrBot Milky Adapter

将实现 Milky 协议的 QQ 客户端接入 AstrBot。插件注册 `milky` 消息平台，通过 HTTP API 发送请求，通过正向 WebSocket 接收事件，不需要修改 AstrBot 源码。

## 环境

- Python 3.10 或更新版本；开发测试使用 Python 3.12。
- AstrBot 4.9.2 或更新版本。当前接口按 AstrBot 上游 master 核对；最低版本未进行实机验证，推荐使用最新稳定版。
- 已登录 QQ、启用 HTTP API 和正向 WebSocket 的 Milky 实现端。
- 协议目标：Milky 1.3。不同实现端的媒体编码、上传限制和功能完整度可能不同。

## 安装

1. 将本项目放入 AstrBot 的 `data/plugins/astrbot_plugin_milky_adapter/`，该目录下应直接包含 `main.py` 和 `metadata.yaml`。不要将项目的 `.venv`、`.uv-cache`、测试临时目录或权限诊断报告一并部署。
2. 在 AstrBot 使用的 Python 环境安装依赖：

   ```sh
   python -m pip install -r data/plugins/astrbot_plugin_milky_adapter/requirements.txt
   ```

3. 重启 AstrBot，让插件先完成注册，再加载消息平台。不要直接运行 `main.py`。
4. 在 AstrBot 管理面板的消息平台页面新增 **Milky**，设置协议端地址和 token 后启用。不同 AstrBot 版本的界面可能不同；若未出现类型，先查看插件加载日志，再重启。
5. 协议端和 AstrBot 不在同一台主机或容器时，填写从 AstrBot 环境实际能够访问的地址。容器内的 `127.0.0.1` 指容器自身。

本项目还没有发布仓库地址，因此不提供虚构的插件市场安装链接。

## 配置

以下是平台配置对象，而不是插件独立配置。通过管理面板保存；手动编辑 AstrBot 主配置时，应作为 `platform` 列表中的一个对象加入，而不是替换整个主配置。

```json
{
  "type": "milky",
  "id": "milky_main",
  "enable": true,
  "base_url": "http://127.0.0.1:3000",
  "event_url": "",
  "access_token": "replace-with-your-token",
  "request_timeout": 30,
  "reconnect_interval": 3,
  "max_upload_mb": 20,
  "ignore_self": true
}
```

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `id` | `milky` | 平台实例唯一标识；多账号必须使用不同值 |
| `base_url` | `http://127.0.0.1:3000` | 协议端 HTTP 根地址；允许反向代理前缀及结尾 `/api` |
| `event_url` | 空字符串 | 留空时从根地址推导 `/event`；HTTPS 自动对应 WSS；可指定其他 WS/WSS 地址 |
| `access_token` | 空字符串 | HTTP 和 WebSocket 均使用 `Authorization: Bearer ...`；协议端未设置 token 时才留空 |
| `request_timeout` | `30` | HTTP 请求超时秒数，必须为有限正数 |
| `reconnect_interval` | `3` | 重连初始间隔秒数；失败指数退避，通常上限 60 秒 |
| `max_upload_mb` | `20` | 单个本地文件或 base64 媒体的上传限制，单位 MiB；不限制协议端自行下载的远程 URL |
| `ignore_self` | `true` | 不将机器人自己发送的消息提交给 AstrBot |

例如 `https://example.com/milky/api` 对应 HTTP `https://example.com/milky/api/send_group_message` 和 WS `wss://example.com/milky/event`。地址中不要携带用户名、密码、token 查询参数或 fragment；使用专用 `access_token` 字段。

## 能力与边界

- 接收好友、群聊和临时消息，保留原始 Milky 事件。
- 文本、@用户、@全体、QQ 表情、图片、语音、视频、引用回复的收发。
- 发送 AstrBot `Node` / `Nodes` 合并转发；接收转发自动调用 `get_forwarded_messages` 展开为 `Nodes`，嵌套限制 8 层，资源请求失败时保留 `Forward.id`。接收节点没有发送者 QQ 号，使用 `uin="0"` 标识未知，保留昵称和时间。
- 文件接收解析下载链接；文件发送调用独立上传 API，并保留文本与文件的顺序。
- 主动发送支持好友和群聊，兼容群聊独立会话 ID。引用消息 ID 为 `scene:peer:message_seq`，发送引用时也允许直接传入序列号。
- 流式结果先聚合再发送，不提供原生流式消息更新。
- 临时消息与好友消息使用不同会话 ID。Milky 没有发送临时会话消息的 API，回复临时消息会抛出明确错误，不会错误地路由至好友 API。
- 未知接收消息段转换为文本占位符；不支持的发送组件显式报错。
- 非消息事件统一进入 AstrBot `OTHER_MESSAGE` 事件队列，保留完整 `raw_message`。通过 `event.message_obj.raw_message["event_type"]` 判断通知类型；不是 OneBot 的 notice/request 模型，也不会自动批准好友/入群请求。
- 好友/群文件上传事件解析为 `File` 组件；私聊文件下载传递 `is_self_send`。通知没有唯一 ID，不按秒级时间戳去重。
- `await event.get_group()` 可查询群信息、群成员、群主及管理员，接口失败时保留已有入站群信息。
- 客户端显式封装固定 `v1.3.0` 规范的全部 65 个 HTTP API，返回未修改的响应 `data` 字典，尚无类型化响应模型或全部参数值的本地校验。
- 传输只实现正向 WebSocket；Webhook、SSE 尚未实现。API 覆盖完整不代表所有传输方式和 AstrBot 业务语义均已完整适配。
- 去重仅保留当前进程最近 2048 条已入队消息，不持久化。断线期间消息没有历史补偿，不承诺恰好一次投递。
- 消息发送不自动重试，避免超时后重复发送。包含多个文件/消息的链不具备事务性，后续请求失败时前面的内容可能已发送。
- 图片等媒体使用 `temp_url`；缺失时通过 `resource_id` 获取临时链接。资源请求失败时保留占位符及其他消息段；临时 URL 过期后不自动刷新。

本地媒体和文件会读取并编码为 `base64://`，因此 AstrBot 与协议端无需共享磁盘。`http(s)://` 媒体由协议端下载，需保证协议端也能访问目标地址。上传上限不会强制远程 URL 的实际下载大小；实现端还可能有更低的限制。

## 插件调用

在其他 AstrBot 插件里，Milky 事件的 `event.bot` 是协议客户端，可直接调用标准 API；这是 Milky API，不是 OneBot `call_action`：

```python
info = await event.bot.get_login_info()
forward = await event.bot.get_forwarded_messages(forward_id="your-forward-id")
history = await event.bot.get_history_messages("group", peer_id=123456, limit=20)
# 扩展 API 仍可调用 await event.bot.call_api("extension_name", ...)
```

自动回复使用 AstrBot 的标准 `event.send()` / `yield event.plain_result(...)`。主动发送使用 AstrBot 标准 `context.send_message()` 和事件的 `unified_msg_origin`，不要自行猜测会话字符串。

## 测试

独立测试不需要安装整个 AstrBot：

```sh
python -m pip install -r requirements.txt
python -m unittest discover -v
```

- `tests/test_api.py`：7 项数据驱动测试覆盖全部 65 个稳定 API 的路由、参数、默认值、必填项和 optional 省略规则。
- `tests/test_client.py`：启动本地随机端口的 aiohttp 服务，验证真实 HTTP/WS 通信、鉴权、错误信封、坏帧过滤、关闭和 URL 配置。
- `tests/test_adapter.py`：使用最小 AstrBot 测试替身，验证组件映射、文件顺序、主动消息路由、去重、媒体大小限制和终止过程。

测试替身不能代替真实 AstrBot 插件加载验收。当前共 43 项测试，显式排除已知受权限阻止的本地媒体测试后，其余 42 项通过；本地媒体测试在 Windows 受限执行环境创建临时目录后遇到权限拒绝，尚未完成该项验证。这不是完整测试通过。未使用真实 QQ 账号或实机协议端验证。

部署后建议依次验证：插件加载、平台连接、好友文字、群聊 @机器人、图片/语音/视频、引用、文件、主动发送、协议端重启后重连，以及 AstrBot 停止时连接释放。

## 故障排查与安全

- HTTP 401：检查两端 token 一致；日志不会输出 token 或协议端错误正文。
- HTTP 404：检查端口和代理前缀，确认连接的是 Milky 而不是 OneBot 服务。
- 收不到消息：检查 `/event` WebSocket 已启用，代理允许 Upgrade，并确认账号登录状态及 AstrBot 唤醒/平台启用设置。
- 能收到但不能发送：查看发送 API 错误码、临时会话限制和协议端自身日志。
- 文件或图片不可用：检查本地读取权限、上传限制、URL 有效期、协议端下载网络和资源 API 支持情况。
- 正向连接无需为本插件额外开放监听端口。不要把未鉴权的 Milky 服务暴露到公网；远程连接使用 HTTPS/WSS、访问控制或可信内网。
- 接收媒体/文件 URL 来自协议端，应仅连接可信实现端。配置含明文 token，勿提交实际配置或日志到公开仓库。

## 接口依据

- [AstrBot 平台注册接口](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/platform/register.py)
- [AstrBot 平台接口](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/platform/platform.py)
- [Milky 通信规范](https://milky.ntqqrev.org/guide/communication)
- [Milky 接收消息](https://milky.ntqqrev.org/struct/IncomingMessage)
- [Milky 接收消息段](https://milky.ntqqrev.org/struct/IncomingSegment)
- [Milky 发送消息段](https://milky.ntqqrev.org/struct/OutgoingSegment)
- [Milky 文件 API](https://milky.ntqqrev.org/api/file)
