# Feature Specification: Three-Scope Memory Granularity

**Feature Branch**: `017-three-scope-memory`

**Created**: 2026-07-08

**Status**: Draft

**Input**: 补齐规划文档清单 13（P2 规模化生态）"三范围 Memory 粒度"（知识库《CubePlex》）：区分个人 / Workspace / 组织 三级记忆，与特性 002（会话级多人协同）打通，让 Agent 在不同范围记住不同粒度的上下文。

## User Scenarios & Testing *(mandatory)*

用户故事按优先级排列，每个独立可交付、可测试。

### User Story 1 (P1) — 三级记忆范围

记忆按三个范围隔离：
- 个人：仅该用户可见（个人偏好/习惯）
- Workspace：该工作区成员共享（团队约定/项目上下文）
- 组织：全组织可见（组织级知识/规范）

**Acceptance Scenarios:**
- 写入个人记忆 → 仅本人可见
- 写入 Workspace 记忆 → 该工作区成员共享
- 写入组织记忆 → 全组织可见
- 跨范围读取 → 按可见性隔离，不越权

### User Story 2 (P1) — 记忆范围可指定

用户/Agent 写入记忆时可显式指定范围；不指定时按默认策略（如默认个人）。

**Acceptance Scenarios:**
- 指定 workspace 范围写入 → 存 workspace 级
- 不指定 → 默认个人级
- 范围升级（个人→组织）需授权

### User Story 3 (P2) — 与会话级多人协同打通

多人协同会话（特性 002）中，会话沉淀的记忆可按范围共享：会话产出的经验默认 Workspace 级，组织级需显式提升。

**Acceptance Scenarios:**
- 会话结束沉淀记忆 → 默认 Workspace 级
- 提升为组织级 → 需授权 + 审计
- 个人会话记忆 → 不进共享范围

### Notes / Assumptions
- 本特性补齐规划文档清单 13（P2 规模化生态，后置），属缺口新特性
- 现状：MOGO 会话/知识是临时或文档态，无三级记忆模型
- 与特性 002（session-versioning）的关系：会话沉淀 → 记忆，按范围共享
- 与特性 011（Dream Cycle）的关系：自进化经验按范围入库（个人/Workspace/组织）
- 与特性 001（gatekeeper）的关系：组织级记忆写入需 001 授权 + 审计
- 记忆生命周期（衰减/清理策略）需 clarify
- "个人"范围与 005 个人知识的关系：005 是个人知识库，017 是"记忆"模型（可能底层复用 005 个人知识）

## Functional Requirements

- FR-1: 记忆分三级：个人 / Workspace / 组织；**Workspace 粒度 = 租户内的协作工作区（一个租户可多个 Workspace，记忆绑定 workspace id，非"会话即 Workspace"）**
- FR-2: 跨范围读取按可见性隔离，不越权；**可见性 = personal 仅本人 / workspace 仅该 Workspace 成员 / org 全组织成员**
- FR-3: 写入可指定范围；未指定时按会话类型默认——单人会话默认 personal，多人协同会话（002 co-presence）默认 workspace
- FR-4: 范围升级（个人→组织）需授权 + 审计；**授权角色 = 006 的"全能力管理员"角色**
- FR-5: 会话结束沉淀记忆按范围共享——单人会话沉淀 personal，多人会话沉淀 workspace；组织级需显式提升（FR-4）
- FR-6: 记忆存储按范围隔离（存储设计）；**personal 范围复用 005 个人知识底层存储（不重复建库）**
- FR-7: 组织级记忆写入受 001 治理约束；**约束点 = 授权（FR-4 全能力管理员）+ 审计（写入/提升事件进 001 审计）**
- FR-8: 记忆生命周期（衰减/清理）可配置；**衰减周期默认 30 天，访问命中重置计时；清理触发条件 = 衰减到期后归档/删除（可配）**
- FR-9: **记忆进入 RAG 检索范围（005），检索时按 scope 可见性过滤（与 FR-2 隔离口径一致）**
- FR-10: **用户离职/删号时 personal 记忆随账号失效；workspace/org 记忆保留（不随个人账号清理）**
- FR-11: **记忆超限（超长）处理 = 优先分层**：超长记忆写入时拆分为 L0/L1/L2（见 FR-13/FR-15），不拒绝；仅当内容 `tierable=false` 且 L2 仍超过硬上限（`l2_hard_max_bytes`，可配）时拒绝写入并明确提示（不静默截断）。自动摘要/压缩算法本身属 Non-Goals（见 FR-15 生成职责划分）。
- FR-12: **同一内容写入多范围（personal + workspace）时各存独立副本（不走跨范围去重），检索时按可见性分别呈现**
- FR-13: **密度分层模型（与 scope 正交）**：每条记忆（无论 scope）维护三级信息密度——`l0_summary`（≤1 句，相关性初筛）、`l1_overview`（结构/要点，定检索方向）、`l2_raw`（原始详情，仅按需读取）。三层对所有 scope（personal/workspace/org）均适用。
- FR-14: **渐进检索（默认只注入 L0+L1）**：检索流程 = L0 粗筛（按 l0 相关性排序）→ 命中候选下探 L1（按 l1 决定方向）→ 仅当调用方显式请求 detail 时才取 L2。默认仅将 L0+L1 注入上下文，L2 不进上下文，避免一次性灌入原始长文本。
- FR-15: **摘要生成（写入时生成 + 读取时惰性补全，两者结合）**：写入时由上游 Agent/LLM 生成 L0/L1 并随记忆持久化（成本前移，首访快）；读取时若 l0/l1 缺失或超过 `summary_refresh_days`（默认 30，可配）则惰性补全（成本后移兜底）。纯二进制/不可解析内容标记 `tierable=false`，跳过分层、按 FR-11 兜底。017 不内置摘要模型/embedding 训练，仅负责存储与按需回退。
- FR-16: **检索轨迹/可回看**：每次检索产出 `retrieval_trace`，含命中项（uri / type / tier_used / 命中原因）、被跳过项及原因（scope 不可见 / 相关性不足 / 未请求 L2）。轨迹落**观测日志**（非 001 审计），支持按 `trace_id` 回看与调试；高价值命中可抽样进 001 审计（与 009/001 联动）。
- FR-17: **统一地址暴露点**：记忆暴露只读寻址 `mogo://memory/<scope>/<owner_id>/<memory_id>/[L0|L1|L2]`，供 021 统一上下文地址空间消费；017 仅定义 memory 这一根，resource/skill/session 根由 021 与各对应 spec 定义。
- FR-18: **tier 适配器契约（provenance）**：memory 暴露统一 `(l0, l1, l2, tierable, provenance)` 适配器接口，provenance 含 `source_session_id` + `source_type`（如 session / agent / manual），供 021 与检索轨迹复用；地址层（021）不重实现摘要生成。
- FR-19: **会话上下文可见性**：解析 `mogo://memory/...` 时，可见性针对**当前会话参与者集合**判定——单人会话可见 personal +（成员）workspace + org；co-presence（002 多人同会话）会话参与者共享 workspace 级记忆、personal 仅各自可见。与 FR-2/FR-3/FR-5 口径一致。
- FR-20: **会话沉淀→分层记忆（升级 FR-5）**：002 `SessionEnd`（经 009 hook 触发）沉淀到 017 时，产出**分层记忆**（L0=会话摘要、L1=关键决策/参与者、L2=快照/转录引用），并写 `source_session_id` + `source_type=session` 反向链接；默认 scope 按 FR-3（单人→personal、co-presence→workspace）。

## Non-Goals
- 不实现跨组织记忆共享
- 不改变 005 个人知识库契约（可复用其底层存储）
- 不内置摘要模型/embedding 训练：L0/L1 摘要由上游 Agent 在写入时生成，或由检索时惰性 LLM 调用补全（FR-15），017 仅负责存储与按需回退，不在本特性内训练或内置摘要引擎
- 不实现记忆的跨实例同步（单部署内）

## Success Criteria
- 三级记忆隔离 100% 无越权读取
- 范围升级 100% 有授权 + 审计
- 会话沉淀按范围共享
- 记忆生命周期 100% 可配置
- 渐进检索默认 100% 只注入 L0+L1（L2 不进上下文除非显式请求）
- 检索轨迹 100% 可回看（按 trace_id）

## Further Details
- 技术实现（记忆存储模型、范围隔离、生命周期）由 plan.md 承载
- 默认范围策略与生命周期阈值需 clarify
