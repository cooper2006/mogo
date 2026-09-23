# Feature Specification: A2A Agent Interop Gateway

**Feature Branch**: `012-a2a-agent-gateway`

**Created**: 2026-07-08

**Status**: Draft

**Input**: 补齐规划文档清单 8（P2 规模化生态）"A2A Agent 互通网关"（知识库《PilotMind》MCP+A2A 双协议）：输出 AgentCard + JSON-RPC，对接 Dify/LangGraph 等外部生态，使 MOVO 的 Agent 能力可被外部系统以标准协议发现和调用。

## User Scenarios & Testing *(mandatory)*

用户故事按优先级排列，每个独立可交付、可测试。

### User Story 1 (P1) — AgentCard 对外发现

MOVO 注册为 A2A 节点后，外部生态（Dify/LangGraph 等）可拉取其 AgentCard（能力描述、端点、鉴权方式、支持的协议版本），据此把 MOVO 的 Agent 纳入自己的编排。

**Acceptance Scenarios:**
- 外部系统拉取 AgentCard → 返回 JSON 能力清单（agent 名/描述/端点/协议/鉴权）
- AgentCard 随 Agent 能力变更自动更新
- 多 Agent 节点 → 每个 Agent 独立 AgentCard

### User Story 2 (P1) — JSON-RPC 标准调用

外部系统通过 A2A 的 JSON-RPC 端点调用 MOVO Agent（任务下发/状态查询/结果回传），协议与 Dify/LangGraph 兼容。

**Acceptance Scenarios:**
- 外部发起任务 → MOVO 受理并执行，按 JSON-RPC 语义返回
- 任务状态可查询（进行中/完成/失败）
- 错误按 JSON-RPC 错误码规范返回

### User Story 3 (P2) — 双向对接（既调用别人，也被调用）

MOVO 既能作为 A2A 客户端调用外部 Agent（把外部生态纳入 MOVO 工作流），也能作为服务端被外部调用。

**Acceptance Scenarios:**
- MOVO 发起对外 Agent 调用 → 按 A2A 协议
- 外部调用 MOVO Agent → 在权限范围内受理
- 双向都受 001 治理层权限/审计约束

### Notes / Assumptions
- 本特性补齐规划文档清单 8（P2 规模化生态，后置），属缺口新特性
- 现状：MOVO 已有 MCP 接入（Skills/Tools 连 HTTP/MCP 业务系统），A2A 是"Agent-to-Agent"层，与 MCP 互补（MCP=工具，A2A=Agent 互操作）
- 协议版本以 A2A 标准（AgentCard + JSON-RPC/JSON-RPC over HTTP）为准
- 与特性 001（gatekeeper）的关系：A2A 调用入口复用 001 门禁与审计
- 与特性 018（能力资产化）的关系：对外 Agent 能力可注册为可审计资产

## Functional Requirements

- FR-1: 对外暴露 AgentCard（能力/端点/鉴权/协议版本）
- FR-2: 提供 A2A JSON-RPC 端点（任务下发/状态/结果）
- FR-3: 支持作为 A2A 客户端调用外部 Agent
- FR-4: 对接 Dify/LangGraph 等主流生态协议
- FR-5: AgentCard 随能力变更自动更新
- FR-6: A2A 调用入口受 001 治理层权限与审计约束
- FR-7: 错误按 JSON-RPC 规范返回
- FR-8: 多 Agent 节点各自独立 AgentCard

## Non-Goals
- 不实现 A2A 协议本身的扩展（仅按标准实现端点）
- 不实现跨组织 A2A 共享（A2A 对接在同一可信域/租户内，跨域另议）
- 不改变现有 MCP 工具接入契约（A2A 与 MCP 并存）
- 不实现 A2A 的 P2P 去中心化发现（本期为中心式 AgentCard 注册）

## Success Criteria
- AgentCard 可被 Dify/LangGraph 解析成功
- JSON-RPC 任务调用全链路可完成（受理/状态/结果）
- 双向对接均可调用
- A2A 调用 100% 进 001 审计

## Further Details
- 技术实现（AgentCard 生成、JSON-RPC 端点、客户端封装）由 plan.md 承载
- 与特性 001/018 的关系已述
- 协议版本兼容范围需 clarify
