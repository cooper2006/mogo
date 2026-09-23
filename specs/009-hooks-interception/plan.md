# Implementation Plan: Five-Event Hooks Interception Mechanism

**Branch**: `009-hooks-interception` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 缺口新特性。在 `dsh_runtime` 会话生命周期 + 工具调用链路上挂载五事件 Hooks，fail_closed + 声明式规则，复用既有 admission/gateway/approval 挂载点。

## Summary

新增 `dsh_runtime/hooks/` 子模块：五事件注册（SessionStart/PreToolUse/PostToolUse/SessionEnd/MemoryCommit）+ 声明式规则引擎（deny_tool/require_field/observe）+ 超时保护 + fail_closed。挂载点复用既有：`turn_admission.admit_skill_selection`（PreToolUse 切入）、`gateway` 会话生命周期（SessionStart/End/MemoryCommit）、`approval_runtime`（审批联动）。首期先落 PreToolUse 单事件（规划文档"落地建议 3"：先单事件低成本切入）。

## Technical Context

**Language/Version**: Python 3.13（chat-api）

**Primary Dependencies**: 既有 `dsh_runtime`（turn_admission/gateway/events）+ `governance/approval_runtime`

**Storage**: 钩子规则声明（MongoDB `hook_rules` 集合，声明式配置）

**Testing**: pytest（规则引擎单测 + fail_closed 注入测试 + 五事件触发集成测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 既有模块扩展（dsh_runtime 钩子层）

## 现有实现事实（挂载点依据）

- `dsh_runtime/turn_admission.py`：`admit_skill_selection`（PreToolUse 切入的既有准入逻辑）
- `dsh_runtime/gateway.py`：`DshAgentKernelGateway`（create/dispose/attach_session，会话生命周期钩子点）
- `dsh_runtime/tool_gateway/token.py`：`ToolGatewayTokenService`（工具调用凭据）
- `governance/approval_runtime.py`：`ApprovalRuntime.issue/validate_and_consume/deny`（审批联动）
- `dsh_runtime/events/`：authoritative_delivery / durable_writer / live_stream / projection（事件通道复用）

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：fail_closed 防越权 |
| III. Security | 通过：deny_tool 合规拦截 |
| IV. i18n | 通过 |
| V. Observability | 通过：钩子事件审计 |

## Project Structure

```text
services/chat-api/app/dsh_runtime/
└── hooks/                       # 新增子模块
    ├── __init__.py
    ├── registry.py             # 五事件注册/查找
    ├── engine.py               # 规则引擎（deny_tool/require_field/observe）
    ├── rules.py                # 声明式规则 schema
    ├── timeout.py              # 超时保护 + fail_closed
    └── integration.py          # 挂载到 turn_admission/gateway/events
services/chat-api/app/api/
└── (新增 hook_rules 管理端点，声明式配置 CRUD)
```

## Open Questions
- OQ-1: 钩子超时阈值默认值（spec 需 clarify；建议 5s 起步可配置）
- OQ-2: fail_closed 默认行为（超时/异常/规则解析失败是否一律拒绝，还是可配置为放行 + 告警）
- OQ-3: 首期是否仅落 PreToolUse（规划文档"落地建议 3"倾向是），其余四事件按节奏补齐
- OQ-4: 钩子规则作用域（按工具/会话/租户）的存储 schema

## 下一步
`/speckit-clarify` 消解 OQ → 补 research/data-model/contracts/quickstart → checklist → tasks → analyze → implement → converge。
