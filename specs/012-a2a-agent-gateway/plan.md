# Implementation Plan: A2A Agent Interop Gateway

**Branch**: `012-a2a-agent-gateway` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 缺口新特性（P2 规模化生态，后置）。在既有 MCP/工具生态之上增加 A2A（Agent-to-Agent）互通层，输出 AgentCard + JSON-RPC，对接 Dify/LangGraph 等外部生态。

## Summary

新增 `services/chat-api/app/a2a/` 子模块：AgentCard 生成/注册、JSON-RPC 任务端点（下发/状态/结果）、A2A 客户端封装（对外调用）。复用既有挂载点：`enterprise_capabilities/tools`（工具执行/审批/回执）作为"被调用 Agent 能力"的执行后端，`governance` 作为鉴权与审计边界。A2A 与既有 MCP 并存（MCP=工具接入，A2A=Agent 互操作）。

## Technical Context

**Language/Version**: Python 3.13（chat-api 既有栈）

**Primary Dependencies**: 既有 `enterprise_capabilities/tools`（EnterpriseToolService.execute/decision + 审批 + ActionReceipt）+ `governance`（鉴权/审计）；新增 A2A 标准协议端点

**Storage**: 新增 `a2a_agent_cards`（AgentCard 注册）+ 复用既有 ActionReceipt 落库（任务回执）

**Testing**: pytest（AgentCard 生成单测 + JSON-RPC 端点契约测试 + 客户端/服务端双向集成测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 新增模块（A2A 互通网关，P2 后置）

## 现有挂载点依据

- `enterprise_capabilities/tools/service.py`：`EnterpriseToolService`（execute/decide/request_approval + ToolGatewayClaims）——被调用 Agent 能力的执行后端
- `enterprise_capabilities/tools/contracts.py`：`ToolExecuteRequest` / `EnterpriseActionReceipt` / `EnterpriseApproval`（任务受理/回执/审批的既有契约）
- `governance/action_receipt.py`：`ActionReceipt` / `RunningReceiptPolicy`（回执语义，A2A 任务回执可复用）
- 与 MCP 并存：现有 Skills/Tools 连 HTTP/MCP，A2A 是 Agent 层互通（非工具层）

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：任务回执可追溯 |
| III. Security | 通过：A2A 入口过 001 门禁/审计 |
| IV. i18n | 通过 |
| V. Observability | 通过：A2A 事件审计 |

## Project Structure

```text
services/chat-api/app/
└── a2a/                          # 新增 A2A 网关
    ├── __init__.py
    ├── agent_card.py            # AgentCard 生成/注册/更新
    ├── jsonrpc.py               # JSON-RPC 端点（task submit/status/result）
    ├── client.py                # 对外 A2A 客户端（调用外部 Agent）
    └── protocol.py              # A2A 协议版本/错误码
services/chat-api/app/api/endpoints/
└── (新增 a2a.py：AgentCard 拉取 + JSON-RPC 入口路由)
```

## Open Questions
- OQ-1: A2A 协议版本范围（对齐哪个 A2A 标准版本；spec 写"按标准实现端点"需定版本）
- OQ-2: AgentCard 注册中心是本地（a2a_agent_cards）还是对接外部 registry
- OQ-3: A2A 双向调用的鉴权模型（双向是否都要 001 门禁，跨域可信如何定）
- OQ-4: 与 Dify/LangGraph 的兼容优先级（先兼容哪个生态的 AgentCard 字段）

## 下一步
P2 后置。`/speckit-clarify` 消解 OQ → 补 research/data-model/contracts/quickstart → checklist → tasks → analyze → implement → converge。
