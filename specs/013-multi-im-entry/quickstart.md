# 013 Multi-IM Entry — Quickstart

## Modules (chat-api `app/im_gateway/`)

| Module | Concern |
| --- | --- |
| `router.py` | `ChannelRouter` — per-channel registration + enable/disable + routing |
| `adapter_base.py` | `ChannelAdapter` base + `ChannelMessage` envelope |
| `bindings.py` | Conversation <-> agent bindings |
| `webhook.py` | IM webhook ingress |
| `audit.py` | T999 审计/可观测接入 (001 落点) |

## Register + route an IM channel

```python
from app.im_gateway.router import ChannelRouter
from app.im_gateway.adapter_base import ChannelAdapter

router = ChannelRouter()
router.register("wecom", adapter=my_wecom_adapter)
router.enable("wecom")
message = router.route("wecom", {"payload": ...})   # -> ChannelMessage
```

## T999 审计接入

每个 IM 入口事件（进入/离开/消息投递/失败）都写入 001 审计落点
（`gate_events`），与会话事件共用同一审计追踪。见 `app/im_gateway/audit.py`。
