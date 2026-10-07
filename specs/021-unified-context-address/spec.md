# Feature Specification: Unified Context Address Space

**Feature Branch**: `021-unified-context-address`

**Created**: 2026-10-05

**Status**: Draft

**Input**: 受 OpenViking 思路（`viking://` 统一地址空间 + L0/L1/L2 密度 + 检索轨迹可回看）启发，在优化 017 三层记忆系统（叠加与 scope 正交的密度轴、统一地址暴露、会话结合）后，抽出的"上下文操作系统"层。把 MOGO 的四类上下文——记忆（017）、知识资源（005/014/015）、技能（004/018）、会话（002/009）——统一为可浏览、可寻址、可回看的地址空间 `mogo://`，让 Agent 像逛目录一样定位上下文、并解释"为什么召回这段、漏了哪些"。

## User Scenarios & Testing *(mandatory)*

### User Story 1 (P1) — 四类统一寻址

MOGO 的四类上下文各有规范地址根，且均可解析回溯到各后端真实存储，不在地址层重复建库：

- `mogo://memory/<scope>/<owner_id>/<memory_id>/[L0|L1|L2]`（017）
- `mogo://resource/doc/<tenant_id>/<document_id>/<chunk_id>`（005，citation 锚点 documentId:chunkId 即 L2 地址）
- `mogo://resource/biz/<system>/<entity_type>/<record_id>`（014，biz_entities.source_ref）
- `mogo://resource/kg/<node_id>`（015，kg_nodes，可反链 014/005）
- `mogo://skill/<org_id>/<skill_id>/<version>`（004，版本快照 digest）
- `mogo://skill/asset/<asset_id>`（018，capability asset，经 skill_refs 关联 004）
- `mogo://session/<tenant_id>/<session_id>/[L0|L1|L2]`（002，会话归档/浏览）

**Acceptance Scenarios:**
- 给定任一 `mogo://` URI → 地址层路由到对应后端并解析出 (l0,l1,l2,tierable)
- 未知 type 根 → 明确报错，不静默
- 解析不触发后端数据复制（虚拟路由）

### User Story 2 (P1) — 逐层加载（L0/L1/L2 按需）

任一上下文项按密度分层按需取：先 L0 粗筛相关性，命中下探 L1 定方向，仅显式请求 detail 才取 L2；默认只把 L0+L1 注入上下文。

**Acceptance Scenarios:**
- 检索返回候选 → 默认只含 L0+L1，L2 不进上下文
- 显式请求 detail(uri, layer=L2) → 返回 L2
- 非记忆类（doc/biz/kg/skill/asset）L0/L1 由后端既有字段提供，地址层不调 LLM

### User Story 3 (P1) — 委托式可见性（不重实现鉴权）

地址层不新建统一权限模型，把可见性判定**委托给各后端既有检查**，自身只做组合与静默裁剪：

- memory → 017 `visible_to`（personal/workspace/org）
- doc → 005 `retrieval_access_policy`（租户/组织隔离）
- biz → 014 `bizdata:read`（001 权限码）
- kg → 015 `kg:read`（001 权限码）
- skill → 004 角色授权（006）+ 018 `a2a_exposed`
- session → 002 会话参与者集合 + share 可见范围

**Acceptance Scenarios:**
- 跨范围/无权限 URI → 在候选中被静默剔除（不报错，与 017 "不越权"一致）
- 地址层无独立权限码，不新增 001 之外的授权面

### User Story 4 (P2) — 检索轨迹可回看

每次检索产出统一 `retrieval_trace`：命中项（uri/type/tier_used/命中原因）+ 被跳过项及原因（不可见/相关性不足/未请求 L2）。轨迹绑定 `session_id`+`turn_id`，落观测日志（非 001 审计，避免污染），支持按 `trace_id` 回看；高价值命中抽样进 001 审计。

**Acceptance Scenarios:**
- 一次检索 → 1 条 trace，含全部命中与跳过及原因
- 按 trace_id 回看 → 还原"为何命中/漏掉"
- 轨迹含记忆/资源/技能/会话元数据 → 需脱敏（与 001 PII 策略联动）

### User Story 5 (P2) — 会话结合（消费 + 生产 + 归档）

活跃会话（002）经本层消费统一上下文（同一检索+轨迹机制拉取 memory/resource/skill）；会话结束时（009 `SessionEnd` hook）触发 017 分层记忆沉淀；历史会话本身经 `mogo://session/...` 可浏览检索。

**Acceptance Scenarios:**
- 活跃会话 turn → 经 021 统一检索，轨迹绑定 session/turn
- 002 SessionEnd → 触发 017 沉淀产分层记忆（FR-20）
- 历史会话 → 可经 `mogo://session/...` 浏览其 L0/L1/L2

## Functional Requirements

- FR-1: 定义四类地址 scheme（`mogo://memory|resource|skill|session/...`），各根路由到对应后端；未知根报错。
- FR-2: 定义 per-type tier 适配器接口 `(l0, l1, l2, tierable)`，各后端实现；地址层不重实现摘要生成。
- FR-3: 渐进加载默认只注入 L0+L1，仅显式请求 detail 才取 L2。
- FR-4: 委托式可见性——地址层调用各后端既有可见性检查，不可见项静默裁剪；不新建统一权限模型。
- FR-5: 统一检索轨迹 schema + 观测日志落点（绑定 session_id/turn_id），抽样进 001 审计；轨迹脱敏。
- FR-6: 会话三重角色——消费方（活跃会话经本层检索）、生产方（SessionEnd 触发 017 分层沉淀）、归档方（`mogo://session/...` 可浏览）。
- FR-7: **首期 tenant = memory（017）**，作为样板验证"目录树可浏览 + 检索轨迹"范式；resource/skill/session 地址约定现在定、各 spec 反向声明，按节奏接入（不阻塞 017）。
- FR-8: 不新建统一存储——地址层是虚拟路由 + 适配器 + 轨迹，复用各后端库（与 017/005/004 "不重复建库"哲学一致）。
- FR-9: 与 009 hooks 集成——`SessionStart` 触发上下文解析预热、`SessionEnd` 触发 017 分层沉淀；钩子语义由 002 提供、009 提供挂载点。

## Non-Goals
- 不实现统一权限/能力模型（委托各后端既有鉴权，不新增授权面）
- 不新建统一存储（虚拟层，复用各后端库）
- 不训练摘要/embedding 模型（仅 memory 由上游 LLM 生成，其余复用既有字段）
- 不实现跨组织上下文共享（各后端既有隔离口径保留）
- 不替代 005/004/002 各自能力，仅在其上提供统一寻址与检索编排

## Success Criteria
- 四类地址 100% 可解析回溯到各后端（不复制数据）
- 渐进加载默认 100% 不注入 L2（除非显式请求）
- 越权读取 0（委托后端保证，地址层不引入新越权面）
- 检索轨迹 100% 可回看（按 trace_id）
- 首期 memory tenant 落地，resource/skill/session 地址约定已与各 spec 双向声明

## Further Details
- 技术实现（虚拟路由、适配器注册、轨迹落点、与 009 集成）由 plan.md 承载
- 与 017 关系：017 是首个 tenant 样板，暴露 memory:// 根 + tier 适配器（FR-17/FR-18）
- 与 002/009 关系：会话消费+生产+归档，SessionEnd 触发分层沉淀（FR-20/009）
- 与 005/014/015 关系：resource 三类根（doc/biz/kg），复用既有字段与 citation/source_ref 锚点
- 与 004/018 关系：skill 两类根（skill/asset），复用 004 元数据与 018 契约

### 跨特性关系（依赖方视角，2026-10-05 新建）
- **与 017（three-scope-memory）**：021 的 memory 根直接消费 017 暴露的 `mogo://memory/...` 地址与 `(l0,l1,l2,tierable,provenance)` 适配器（017 FR-17/FR-18）；017 是 021 首期 tenant。
- **与 002（session-versioning）**：021 的 `mogo://session/...` 根消费 002 会话快照（L0=摘要/L1=commit 结构/L2=快照）；002 活跃会话经 021 检索统一上下文，SessionEnd 经 009 触发 017 分层沉淀（021 FR-6/FR-9）。
- **与 009（hooks-interception）**：021 复用 009 的 `SessionStart`/`SessionEnd` 钩子触发上下文解析与分层沉淀（021 FR-9）。
- **与 005（knowledge-rag）**：021 `mogo://resource/doc/...` 根消费 005 的 citation 锚点 documentId:chunkId（即 L2 地址），L0/L1 复用 005 解析产物。
- **与 014（business-semantic-index）**：021 `mogo://resource/biz/...` 根消费 014 的 biz_entities.source_ref，L0/L1 复用 014 实体抽取。
- **与 015（knowledge-graph-layer）**：021 `mogo://resource/kg/...` 根消费 015 的 kg_nodes（可反链 014/005），L0/L1 复用 015 邻接信息。
- **与 004（skillhub-lifecycle）**：021 `mogo://skill/<org>/<skill_id>/<version>` 根消费 004 版本快照（digest）+ 元数据，L0/L1 复用 004 能力描述。
- **与 018（capability-asset-registration）**：021 `mogo://skill/asset/<asset_id>` 根消费 018 能力资产契约（输入/输出/错误/SLA），经 skill_refs 关联 004。
