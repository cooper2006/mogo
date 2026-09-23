# 012 A2A Agent Gateway — Quickstart

## Modules (chat-api `app/a2a/`)

| Module | Concern |
| --- | --- |
| `protocol.py` | JSON-RPC 请求/响应 + `TaskLifecycle`（task id 幂等，FR-10） |
| `agent_card.py` | `AgentCard` 输出/解析（`build_agent_card` / `parse_agent_card`） |
| `client.py` | T009 出站客户端（30s 超时 + failover + 复用 007 退避） |

## 1. 输出 AgentCard（US1）

```python
from app.a2a.agent_card import build_agent_card, parse_agent_card

card = build_agent_card(agent_id="a-1", name="movo-agent", endpoint="https://...")
parse_agent_card(card.as_dict())   # 外部系统可解析（Dify-first 字段映射）
```

## 2. JSON-RPC 标准调用（US2）

```python
from app.a2a.protocol import JsonRpcRequest, TaskLifecycle

request = JsonRpcRequest(method="message/send", params={"text": "hi"}, id=1)
assert request.validate() is None     # 方法/参数校验
```

## 3. 出站调用（US2 / T009 / FR-3）

```python
from app.a2a.client import A2AClient, ClientConfig

client = A2AClient(my_http_jsonrpc_transport,
                   ClientConfig(primary_agent="primary", backup_agents=("backup",)))
call = await client.send({"text": "hi"}, task_id="t-1")
# 超时 30s + failover + 复用 007 退避；治理拒绝(-32000) 不重试不 failover，立即透出错误码
call.as_document()   # 可审计化
```

## T999 审计接入

`a2a.outbound` / `a2a.inbound` / `a2a.denied` 事件经
`app/services/feature_audit.py::record_feature_event("012", ...)` 进 001
审计落点；出站调用结果可用 `OutboundCall.as_document()` 序列化为审计记录。

## T998 契约文档

见 `contracts/a2a-gateway.md`：JSON-RPC 方法 / 错误码映射 / 超时与 failover
契约 / AgentCard schema。
