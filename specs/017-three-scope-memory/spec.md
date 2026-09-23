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
- 现状：MOVO 会话/知识是临时或文档态，无三级记忆模型
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
- FR-11: **记忆超限（超长）处理 = 拒绝写入并提示（不静默截断），自动摘要/压缩属 Non-Goals**
- FR-12: **同一内容写入多范围（personal + workspace）时各存独立副本（不走跨范围去重），检索时按可见性分别呈现**

## Non-Goals
- 不实现跨组织记忆共享
- 不改变 005 个人知识库契约（可复用其底层存储）
- 不实现记忆的自动摘要/压缩算法（属记忆引擎，非范围模型）
- 不实现记忆的跨实例同步（单部署内）

## Success Criteria
- 三级记忆隔离 100% 无越权读取
- 范围升级 100% 有授权 + 审计
- 会话沉淀按范围共享
- 记忆生命周期 100% 可配置

## Further Details
- 技术实现（记忆存储模型、范围隔离、生命周期）由 plan.md 承载
- 默认范围策略与生命周期阈值需 clarify
