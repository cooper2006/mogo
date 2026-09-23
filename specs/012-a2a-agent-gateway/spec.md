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

- FR-1: 对外暴露 AgentCard（能力/端点/鉴权/协议版本）；**必含字段 = agent 名 / 描述 / 端点 URL / 协议版本 / 鉴权方式 / 能力清单；"能力清单"表达为 `skills[]`（每个含 id/name/description/inputModes/outputModes，对齐 A2A 标准字段）**
- FR-2: 提供 A2A JSON-RPC 端点（任务下发/状态/结果）；**方法名对齐 A2A 标准：`message/send`（下发）、`tasks/get`（状态）、`tasks/result`（结果）**
- FR-3: 支持作为 A2A 客户端调用外部 Agent；**外部 Agent 不可达时按超时（默认 30s）+ failover 到配置的备 Agent，重试沿用 007 退避原语**
- FR-4: 对接 Dify/LangGraph 等主流生态协议；**优先兼容 Dify 的 AgentCard 字段，LangGraph 经适配层字段映射**
- FR-5: AgentCard 随能力变更自动更新；**触发条件 = 能力注册/变更事件即刷新（非定时轮询）**
- FR-6: A2A 调用入口受 001 治理层权限与审计约束；**入站（被调）与出站（调外部）双向都过 001 门禁/审计**
- FR-7: 错误按 JSON-RPC 规范返回；**MOVO 侧被调 Agent 失败（如 001 拒绝）映射为 JSON-RPC error（code -32000 段，message 含 001 拒绝原因）**
- FR-8: 多 Agent 节点各自独立 AgentCard；**按 agent id 路由，URL 结构 `/a2a/{tenant}/{agent_id}`**
- FR-9: **AgentCard 鉴权方式枚举：API key / OAuth2 / 组织互信凭据（同期靠 006 RBAC 组织边界）；鉴权凭证协商走既有密钥管理，不进仓库**
- FR-10: **任务幂等：同一 `task id` 重复下发按幂等处理（返回既有任务状态，不重复执行）**
- FR-11: **外部 Agent 列表维护：中心式注册于本地 `a2a_agent_cards` 集合，由 018 显式标记 `a2a_exposed` 的资产自动生成 + 管理员手工登记外部 Agent**

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

### 跨特性关系（被依赖方视角，2026-07-08 双向声明）
- **与 018（capability-asset-registration）**：012 的 AgentCard **仅对 018 显式标记 `a2a_exposed` 的资产生成**——018 的资产默认不暴露 A2A，标记后方生成 AgentCard（见 018 FR-12）。
- **与 001（gatekeeper）**：012 的 A2A 调用入口（入站 + 出站）是 001 门禁链的受管入口（见 001 spec 跨特性关系）。
