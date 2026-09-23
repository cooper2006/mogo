# Feature Specification: Multi-IM Entry Points

**Feature Branch**: `013-multi-im-entry`

**Created**: 2026-07-08

**Status**: Draft

**Input**: 补齐规划文档清单 9（P2 规模化生态）"多 IM 入口"（知识库《CubePlex》）：接入飞书/钉钉/企业微信/Slack/Teams，复用既有 Workspace 与 Sandbox，让员工在常用 IM 里直接发起 Agent 会话与查看结果。

## User Scenarios & Testing *(mandatory)*

用户故事按优先级排列，每个独立可交付、可测试。

### User Story 1 (P1) — IM 渠道接入（首期 1 个）

接入一个 IM 渠道（飞书/钉钉/企业微信/Slack/Teams 之一，首期选 1 个），用户在 IM 内发起对话即映射到 MOVO 会话，结果回 IM。

**Acceptance Scenarios:**
- 用户在飞书 @bot 发消息 → 映射为 MOVO 会话消息，Agent 响应回飞书
- IM 会话与 MOVO 会话 1:1 关联，历史可查
- 多用户 → 各自会话隔离

### User Story 2 (P1) — 复用 Workspace 与 Sandbox

IM 入口不新建能力，复用既有 Workspace（上下文）与 Sandbox（隔离执行）；IM 收到的任务落到与 Web 一致的 Workspace 与 Sandbox。

**Acceptance Scenarios:**
- IM 发起任务 → 走既有 Workspace + Sandbox，能力面与 Web 一致
- Sandbox 隔离约束在 IM 渠道同样生效
- 不绕过 001 治理（IM 入口同样过门禁）

### User Story 3 (P2) — 多渠道同时在线 + 统一入口

多渠道（飞书/钉钉/Slack/Teams 等）可同时在线，统一路由到同一 Agent 能力面；渠道差异（消息格式/卡片）适配层隔离。

**Acceptance Scenarios:**
- 同时接入 2+ 渠道 → 各自独立工作，能力一致
- 渠道差异（卡片/富文本）→ 适配层转换，不污染核心
- 渠道开关可配置

### Notes / Assumptions
- 本特性补齐规划文档清单 9（P2 规模化生态，后置），属缺口新特性
- 现状：MOVO 有 Web 用户工作区，无 IM 渠道入口
- 核心原则（CubePlex）："Cloud Harness + 隔离 Sandbox + 多 IM"做安全触达——IM 只是入口，能力面不变
- 与特性 001（gatekeeper）的关系：IM 入口的请求同样过 001 门禁/审计
- 与特性 002（session-versioning）的关系：IM 会话纳入 002 会话版本化
- 首期仅 1 渠道，多渠道理按节奏补齐
- 各 IM 渠道的鉴权（bot token/webhook）不进仓库（001 安全原则）

## Functional Requirements

- FR-1: 至少接入 1 个 IM 渠道（飞书/钉钉/企业微信/Slack/Teams）
- FR-2: IM 消息映射为 MOVO 会话，响应回 IM
- FR-3: IM 入口复用既有 Workspace 与 Sandbox，能力面一致
- FR-4: 支持多渠道同时在线，统一路由
- FR-5: 渠道差异（格式/卡片）由适配层隔离
- FR-6: 渠道请求过 001 门禁/审计
- FR-7: 渠道会话纳入 002 会话版本化
- FR-8: 渠道凭据（token/webhook）不入仓库，可配置
- FR-9: 渠道可独立开关（停用某渠道不影响其他）

## Non-Goals
- 不改变核心 Agent 能力面（IM 仅入口）
- 不实现 IM 内的管理后台（管理仍走 Web 控制台）
- 不实现跨租户 IM 共享
- 不实现 IM 自定义渲染引擎（卡片适配有限）
- 首期 1 渠道，非一次全量

## Success Criteria
- 首期 IM 渠道 1:1 映射 MOVO 会话
- IM 入口 100% 过 001 治理
- 渠道停用不影响核心能力
- 渠道凭据 0 入仓库

## Further Details
- 技术实现（IM 适配器、会话映射、路由）由 plan.md 承载
- 首期渠道选择需 clarify（按目标企业常用 IM 定）
