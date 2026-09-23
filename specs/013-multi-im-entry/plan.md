# Implementation Plan: Multi-IM Entry Points

**Branch**: `013-multi-im-entry` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 缺口新特性（P2 规模化生态，后置）。接入飞书/钉钉/企业微信/Slack/Teams 作为 Agent 入口，复用既有 Workspace 与 Sandbox，能力面与 Web 一致。

## Summary

新增 `services/chat-api/app/im_gateway/` 子模块：IM 渠道适配层（每渠道一个 adapter）、IM↔MOVO 会话映射、统一路由。核心原则（CubePlex）：IM 只是入口，能力面复用既有 Workspace/Sandbox，不新建能力。首期仅接入 1 渠道，多渠道按节奏补齐。

## Technical Context

**Language/Version**: Python 3.13（chat-api 既有栈）

**Primary Dependencies**: 既有会话/Workspace 服务（IM 消息映射为会话）+ 既有 Sandbox/治理（渠道请求过 001 门禁）；各 IM 的 bot SDK/SDK 或 webhook（飞书/钉钉/Slack 等）

**Storage**: 新增 `im_channels`（渠道配置/bot token 指针）+ `im_session_bindings`（IM 会话 ↔ MOVO 会话映射）

**Testing**: pytest（IM 适配器契约测试 + 会话映射测试 + 渠道开关测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 新增模块（IM 入口网关，P2 后置）

## 现有挂载点依据

- 会话/Workspace：IM 消息落到既有会话（与 002 session-versioning 的会话一致）
- Sandbox/治理：渠道请求复用 001 gatekeeper 门禁与 006 RBAC 授权
- 渠道凭据（bot token/webhook）：按 001 安全原则不入仓库，经既有密钥管理注入（.env.example 约定）

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：渠道可独立开关 |
| III. Security | 通过：渠道请求过 001；凭据不入仓库 |
| IV. i18n | 通过：IM 渠道多语言 |
| V. Observability | 通过：渠道事件审计 |

## Project Structure

```text
services/chat-api/app/
└── im_gateway/
    ├── __init__.py
    ├── adapter_base.py         # 渠道适配基类（消息格式/卡片/鉴权）
    ├── adapters/
    │   ├── feishu.py          # 首期渠道（按 clarify 定）
    │   ├── dingtalk.py
    │   ├── wecom.py
    │   ├── slack.py
    │   └── teams.py
    ├── session_mapping.py      # IM 会话 ↔ MOVO 会话
    └── router.py              # 多渠道统一路由
services/chat-api/app/api/endpoints/
└── (新增 im_channels.py：渠道配置/开关管理)
```

## Open Questions（已 clarify 消解）
- OQ-1 首期渠道：**飞书**（目标企业常用 IM，且 bot/webhook 接入成熟度高）；其余按节奏补齐。
- OQ-2 卡片/富文本适配深度：**首期纯文本 + 基础卡片（markdown 文本卡片）**，不实现按钮/交互式卡片（避免与既有能力面脱节）。
- OQ-3 渠道会话纳入 002 版本化：**是**——IM 会话映射到 MOVO 会话（`im_session_bindings`），002 的 commit/share 对 IM 会话同样生效。
- OQ-4 webhook 签名校验/防重放：**HMAC-SHA256 签名校验 + nonce 去重（Redis/MongoDB 短期去重表）**，防重放窗口 5 分钟。

## 下一步
OQ 已 clarify 消解。P2 后置，按路线图节奏推进：`/speckit-checklist` → `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement` → `/speckit-converge`。
