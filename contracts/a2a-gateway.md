# A2A Gateway Contract (012)

> 012-a2a-agent-gateway — JSON-RPC 协议 + AgentCard + 出站客户端契约。
> 本文件定义 chat-api `app/a2a/` 的对外接口与不变量。

## JSON-RPC 方法

| 方法 | 语义 |
| --- | --- |
| `message/send` | 下发任务（dispatch） |
| `tasks/get` | 查询任务状态 |
| `tasks/result` | 结果回传 |

`JsonRpcRequest.validate()` 校验 jsonrpc=2.0 / 方法在支持集内 / params 为对象。
`TaskLifecycle` 维护 task id 幂等（FR-10：同 id 重发返回既有任务，不重复执行）。

## 错误码映射（US2 验收）

| 代码 | 常量 | 语义 |
| --- | --- | --- |
| `-32700` | `ERROR_PARSE` | 解析错误 |
| `-32600` | `ERROR_INVALID_REQUEST` | 非法请求 |
| `-32601` | `ERROR_METHOD_NOT_FOUND` | 方法不支持 |
| `-32602` | `ERROR_INVALID_PARAMS` | 参数非法 |
| `-32603` | `ERROR_INTERNAL` | 内部错误 |
| `-32000` | `ERROR_MOVO_DENIED` | 治理层拒绝（001 gatekeeper） |

`map_error_code(exc)` 把出站异常映射为 JSON-RPC 错误码：
`JsonRpcError` 透传其 code、`PermissionError` → `-32000`、其它 → `-32603`。

## 出站客户端契约（T009 / FR-3）

`A2AClient(transport, ClientConfig)`：
- **超时默认 30s**（`DEFAULT_TIMEOUT_SECONDS`）。
- **failover**：primary 不可达 → 依序 failover 到 `backup_agents`。
- **复用 007 退避**：节点级重试走 `RetryPolicy`（指数退避），模型级退避委托
  007 韧性调度器（FR-3 / 010 T017 分层不重复）。
- **治理拒绝（`-32000`）不重试、不 failover**，立即透出错误码供调用方区分
  "被治理拒绝"与"传输失败"。
- `OutboundCall.as_document()` 序列化为可审计记录（T999）。

## AgentCard schema（US1）

`build_agent_card(agent_id, name, endpoint, ...)` / `parse_agent_card(document)`
— Dify-first 字段映射（clarify OQ-4）；`a2a_exposed` 标记（018）决定哪些
能力资产生成 AgentCard。

## T999 审计接入

`a2a.outbound` / `a2a.inbound` / `a2a.denied` 事件经
`app/services/feature_audit.py::record_feature_event("012", ...)` 进 001 审计
落点。
