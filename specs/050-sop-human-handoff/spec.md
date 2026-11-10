# Feature Specification: SOP 转人工节点（编排工作流人工审批 + 运行持久化）

**Feature Branch**: `050-sop-human-handoff`

**Created**: 2026-11-09

**Status**: Draft

**Input**: 整合方案 §4.1：编排工作流新增 `human_approval` 节点——流程执行到该节点挂起并持久化运行态，向指定审批人发通知，批准续跑、驳回走分支或终止、超时 fail-closed。复用 `ApprovalRuntime` 票据机制与 013 渠道渲染；关键工程缺口为编排引擎无断点续跑，需新增运行持久化（同时是 052 团队模式的地基）。

> **设计来源**：本规约来自 `docs/MOGO-StaffDeck整合方案.md` §4.1（2026-11-09 代码级勘察结论）。StaffDeck 为 AGPL-3.0，**仅借鉴产品设计，不拷贝代码**。
>
> **性质说明**：**已实现（2026-11-09，tasks 27/27）**——`human_approval` 节点 + 运行持久化 + 挂起/恢复落地；OQ 已按 spec 已定默认值消解并回填。
>
> **背景事实（代码级核实，2026-11-09）**：编排六模式枚举 `services/chat-api/app/orchestration/graph.py:13`（`VALID_MODES`，无 human 节点）；`Node` 为 payload 字典（`graph.py:21`），节点级 mode 形状校验有先例（`loader.py:282-309` 的 round_robin/debate 检查）；引擎 `run_graph`（`engine.py:84`）为进程内异步执行，**无 checkpoint/resume/persist**；统一分发入口 `dispatch.py:66`（`execute_orchestration`）；编排定义已有持久化集合 `dag_definitions`（`store.py:30`）；审批票据机制 `governance/approval_runtime.py:25,32,56`（`ApprovalRuntime.issue / validate_and_consume`，一次性票据、审批与消费分离）；IM 五渠道（`im_gateway/adapter_base.py:18`）出站为应答式渲染（`:96` `render_reply`，**无主动推送 send**）；运行恢复测试范式 `tests/scheduled_tasks/test_scheduler_recovery.py`、`app/dsh_runtime/turn_recovery.py`。

## 定位（一句话）

把 mogo 的人工审批从"工具调用层"（001）提升到"业务流程层"：编排工作流中的 `human_approval` 节点使流程可挂起等待指定审批人决策（批准续跑 / 驳回走分支 / 超时 fail-closed），运行态持久化支持跨进程恢复；**既有六模式语义零改动**。

## 已定决策（2026-11-09，spec 撰写时拍板）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | 节点审批机制 | 复用 `ApprovalRuntime`：节点挂起时 `issue` 票据，审批决策经 `validate_and_consume` 消费；**不另造审批状态机**；审批与消费分离（发起人不可自审）沿用 001 语义 | `orchestration/human_approval.py` |
| 2 | 运行持久化 | 新增 `orchestration_runs` 集合：运行快照（定义版本 + 节点状态 + 共享上下文 + 挂起点）；节点完成即写快照（checkpoint），挂起时持久化后释放执行协程；恢复 = 读快照重建执行。**这是本特性最大工作量，也是 052 的地基** | `orchestration/run_store.py` |
| 3 | 挂起中定义变更 | 运行创建时锁定定义版本（快照含定义全文或版本引用）；挂起期间原定义被修改不影响在途运行（延续 002 版本化语义） | `run_store.py` + loader |
| 4 | 超时策略 | 默认 fail-closed：超时未决策 → 节点失败、下游阻塞（010 FR-6 语义）；超时时长节点可配（默认值待 clarify，建议 24h）；**不做"超时自动批准"** | 节点 payload `timeout` |
| 5 | 通知渠道 | 首期 = 站内审批入口（既有审批页）+ 审计事件；IM 通知经 013 `render_reply` 渲染，**主动推送能力按渠道参差列为 clarify 点**——首期可回落"应答式触达"（审批人下次与 bot 交互时提示待办），不承诺全渠道主动推送 | 通知接线 |
| 6 | 驳回语义 | 驳回默认终止运行（`rejected`）；节点可声明 `on_reject` 指向驳回分支节点（加载期校验目标存在，fail-closed）；驳回必须附理由（进审计与运行记录） | 节点 payload `on_reject` |
| 7 | 画布触点 | 039 画布新增 `human_approval` 节点卡片 + 属性面板（审批人/超时/驳回分支）；YAML 为权威（039 既有口径） | `apps/user-web` 编排画布 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 工作流挂起等待审批并续跑 (Priority: P1) 🎯 MVP

编排作者定义含 `human_approval` 节点的工作流（如合同审查：起草 → 法务审批 → 用印）。流程执行到审批节点时挂起，向指定审批人生成待办；审批人批准后流程从挂起点续跑至完成，驳回则按声明走分支或终止。全程审计可查。

**Why this priority**: 这是 StaffDeck 合同审查多环节审批的核心形态，也是 mogo 审批能力从工具层到流程层的最小完整闭环；单独交付即有业务价值。

**Independent Test**: 定义三节点工作流（mock runner → human_approval → mock runner），执行后断言运行挂起且票据生成；模拟批准 → 断言第三节点执行、运行完成；另一运行模拟驳回（带理由）→ 断言运行终止且理由可查。

**Acceptance Scenarios**:

1. **Given** 工作流含 `human_approval` 节点且指定审批人，**When** 执行到该节点，**Then** 运行状态置 `awaiting_approval`、快照持久化、审批票据生成、待办对审批人可见。
2. **Given** 运行挂起中，**When** 审批人批准，**Then** 票据被消费、运行从挂起点续跑、后续节点正常执行、运行最终 `completed`。
3. **Given** 运行挂起中且节点未声明 `on_reject`，**When** 审批人驳回（附理由），**Then** 运行终止为 `rejected`，理由进运行记录与审计。
4. **Given** 节点声明 `on_reject: <node_id>`，**When** 驳回，**Then** 流程跳转到驳回分支节点继续执行。
5. **Given** 发起人试图审批自己发起的运行，**When** 提交决策，**Then** 拒绝（审批与消费分离，沿用 001 语义）。

---

### User Story 2 - 挂起运行跨进程恢复 (Priority: P1)

运行挂起期间服务重启（发布/故障），恢复后挂起运行不丢失：审批人决策后仍可续跑；已完成节点的输出不重跑。

**Why this priority**: 没有恢复能力的"挂起"只是进程内等待，一次发布就丢流程——生产可用性硬需求；且运行持久化是 052 团队模式异步执行的地基，必须与节点本身同批交付。

**Independent Test**: 执行工作流至挂起 → 丢弃执行进程状态（模拟重启）→ 从 `orchestration_runs` 恢复 → 批准 → 断言续跑成功且已完成节点未重复执行（runner 调用计数）。

**Acceptance Scenarios**:

1. **Given** 运行挂起且快照已持久化，**When** 服务重启后触发恢复扫描，**Then** 挂起运行重新可见、待办不丢、票据仍有效。
2. **Given** 恢复后的挂起运行，**When** 审批人批准，**Then** 从挂起点续跑，已完成节点不重复执行。
3. **Given** 运行在节点执行中（非挂起）进程崩溃，**When** 恢复扫描，**Then** 按快照从最后 checkpoint 重建；运行中节点的副作用重放策略按节点幂等声明处理（无幂等声明的节点标记 `needs_review`，不静默重跑）。
4. **Given** 挂起期间原编排定义被修改，**When** 运行续跑，**Then** 仍按运行锁定的定义版本执行（决策 #3）。

---

### User Story 3 - 超时与异常 fail-closed (Priority: P1)

审批超时、审批人不存在、票据重复消费等异常路径全部显式失败，不静默放行。

**Why this priority**: 审批节点是治理触点，任何"异常时默认放行"都是治理旁路（宪法 II/III）；异常语义必须与节点同批交付。

**Independent Test**: 配置短超时执行挂起运行，等待超时 → 断言节点失败、下游阻塞、审计事件；对已消费票据再次提交决策 → 断言拒绝；加载 `approver` 指向不存在用户的定义 → 断言加载期报错。

**Acceptance Scenarios**:

1. **Given** 节点配置超时时长，**When** 超时内无决策，**Then** 节点失败（`timeout`）、下游按 010 FR-6 阻塞、审计记录超时事件。
2. **Given** 票据已被消费，**When** 再次提交同票据决策，**Then** 拒绝（一次性语义，`ApprovalRuntime` 既有行为）。
3. **Given** YAML 的 `approver` 指向不存在用户/岗位角色，或 `on_reject` 指向不存在节点，**When** 加载定义，**Then** 加载期 fail-closed 报错（与 044 arbiter 校验同风格）。

---

### User Story 4 - 画布节点与契约文档同步 (Priority: P2)

039 画布支持 `human_approval` 节点（卡片 + 属性面板），画布 ↔ YAML 双向往返不丢字段；`specs/010-dag-orchestration-engine/contracts/orchestration.md` 补充转人工节点的 YAML 形态与语义。

**Why this priority**: 画布是编排作者的主要入口，契约是下游消费真相；低于引擎本体但同批交付。

**Independent Test**: 画布拖入审批节点、配置审批人/超时/驳回分支 → 导出 YAML 可被 loader 加载；反向导入含审批节点的 YAML → 画布正确渲染；契约示例 YAML 可加载执行。

**Acceptance Scenarios**:

1. **Given** 画布中的审批节点配置，**When** 导出 YAML 再导入，**Then** 字段无损往返（039 既有口径）。
2. **Given** 契约文档的审批节点 YAML 示例，**When** 用 loader 加载，**Then** 成功且字段进入节点 payload。

---

### Edge Cases

- **多审批节点串联**：每个节点独立票据与挂起快照；前一节点批准后续跑至下一审批节点再次挂起（合同审查多环节形态）。
- **并行分支中的审批节点**：graph 模式并行分支各自挂起，运行级状态为 `awaiting_approval` 当且仅当存在挂起节点；任一分支驳回终止按 `on_reject`/默认语义处理，不阻塞其他分支的快照记录。
- **审批人离职/停用**：决策时校验审批人有效性，无效 → 运行转 `needs_review` 由管理员改派（改派进审计），不静默超时放行。
- **恢复扫描与在途执行并发**：同一运行不得被两个进程同时恢复（租约/乐观锁，参照 `scheduled_tasks` 恢复范式）。
- **挂起运行被管理员取消**：运行置 `cancelled`，票据作废，审计记录。
- **快照写入失败**：节点挂起前快照写失败 → 节点失败 fail-closed，不进入"内存挂起"（避免重启即丢）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 编排引擎 MUST 支持 `human_approval` 节点类型（节点 payload 声明 `approver`、可选 `timeout`、可选 `on_reject`、可选 `prompt` 审批说明）；加载期 MUST 校验 approver 与 on_reject 目标存在（fail-closed）。
- **FR-002**: 执行到 `human_approval` 节点 MUST 挂起运行：持久化快照、经 `ApprovalRuntime.issue` 生成票据、运行状态置 `awaiting_approval`；MUST NOT 在进程内无限等待。
- **FR-003**: 审批决策 MUST 经 `ApprovalRuntime.validate_and_consume` 消费票据；批准续跑、驳回按 `on_reject` 分支或终止（附理由）；发起人自审 MUST 拒绝。
- **FR-004**: 系统 MUST 新增编排运行持久化（`orchestration_runs`）：运行创建锁定定义版本、节点完成写 checkpoint、挂起/恢复/终态全程可查；恢复 MUST 保证已完成节点不重复执行。
- **FR-005**: 服务重启后恢复扫描 MUST 重建挂起运行（待办与票据不丢）；同一运行 MUST NOT 被并发恢复（租约或乐观锁）。
- **FR-006**: 超时 MUST fail-closed（节点失败 + 下游阻塞 + 审计）；MUST NOT 提供"超时自动批准"。
- **FR-007**: 审批待办与决策结果 MUST 通知审批人/发起人：首期站内审批入口 + 审计事件；IM 触达按 013 既有能力渲染，主动推送缺口以应答式触达回落（决策 #5）。
- **FR-008**: 节点挂起、批准、驳回、超时、改派、取消 MUST 全部落审计（001 审计流，含运行 ID/节点 ID/决策人/理由）。
- **FR-009**: 既有六模式（sequential/supervisor/hybrid/graph/round_robin/debate）的执行路径与语义 MUST 零改动；不含审批节点的既有工作流行为不变（既有测试零修改全绿）。
- **FR-010**: 039 画布 MUST 支持审批节点卡片与属性面板，画布 ↔ YAML 往返无损；`contracts/orchestration.md`（010 目录下）MUST 补充审批节点 YAML 形态。
- **FR-011**: 运行持久化 MUST 双后端兼容（MongoDB 默认 / PanWeiDB 经 027 兼容门面），不新增后端分叉代码。

### Key Entities

- **OrchestrationRun**: 一次编排运行（运行 ID / 租户 / 定义版本快照 / 状态 / 共享上下文 / checkpoint 序列 / 发起人），状态机 `running → awaiting_approval → running → completed | rejected | timeout | cancelled | needs_review`。
- **ApprovalNodeConfig**: 审批节点声明（approver / timeout / on_reject / prompt），物化自节点 payload。
- **RunCheckpoint**: 节点级快照（节点状态 + 输出 + 上下文增量），恢复与"不重跑"的依据。
- **ApprovalTodo**: 审批待办（运行 ID / 节点 ID / 审批人 / 票据引用 / 创建时间 / 超时时刻），站内入口与 IM 触达的数据源。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 含两个审批节点的工作流 E2E 跑通：挂起 → 批准 → 再挂起 → 批准 → 完成；驳回与超时路径各有契约测试。
- **SC-002**: 挂起运行经服务重启后可恢复续跑，已完成节点零重跑（runner 调用计数断言）。
- **SC-003**: 异常路径全部 fail-closed：自审、重复票据、无效审批人、超时、快照写失败均有拒绝/失败断言，无静默放行。
- **SC-004**: 既有编排测试（`tests/orchestration/` 全量）零修改全绿；不含审批节点的工作流行为不变。
- **SC-005**: 审计链可从运行 ID 还原完整决策序列（挂起/决策人/理由/时刻）。

## Assumptions

- 审批人解析复用既有用户/岗位角色体系（006），不新建审批人注册。
- 运行持久化走 027 兼容门面，双后端同口径（与 `scheduled_tasks` 一致）。
- 节点执行体仍经 runner 注入（010 transport-agnostic 口径），引擎不直接依赖 DSH runtime。
- 首期不做审批代理（委派他人审批）与多级会签；多环节审批用多个审批节点串联表达。
- IM 主动推送能力边界在 clarify 阶段定死；首期承诺口径 = 站内待办 + 应答式触达。

## 待澄清（clarify 门禁）

- **OQ-1**: 超时默认时长（建议 24h）与可配范围。
- **OQ-2**: IM 主动推送的渠道边界（飞书应用消息主动发送是否首期纳入，还是全部回落应答式触达）。
- **OQ-3**: 运行中节点崩溃后无幂等声明时的 `needs_review` 处置入口（管理员重跑/跳过）首期是否交付。
- **OQ-4**: 挂起运行的保留期与清理策略（终态运行快照保留多久，参照审计 ≥180 天口径还是独立配置）。

> **消解记录（2026-11-09 实现期，T002）**
> - **OQ-1 定值**：默认 `timeout: 86400`（24h），钳制 60s..30d；越界加载期钳制并记事件（loader `_validate_050_shapes`，与 `normalize_period` 宽容归一化同风）。**不做超时自动批准**（FR-006）。
> - **OQ-2 定值**：首期**全部回落应答式触达**——站内待办入口（`/api/v1/orchestration-runs/todos`）+ 审计事件 + 待办经 `notifications.render_approval_reminder` 渲染；**不纳入**飞书应用消息主动发送（留扩展，不改 013 渠道注册语义）。
> - **OQ-3 定值**：**首期交付** `needs_review` 处置入口（`POST /runs/{id}/review`，skip 续跑 / terminate 终止），恢复扫描把崩溃运行标记 `needs_review`（`scan_interrupted`）。
> - **OQ-4 定值**：终态运行快照保留 **180 天**（对齐审计 ≥180 天口径），可经 `ORCHESTRATION_RUN_RETENTION_DAYS` 调整；`cleanup_terminal` 由恢复扫描驱动。

## 跨特性关系（被依赖方视角，双向声明）

- **与 010（dag-orchestration-engine）**：本特性是 010 的直接扩展——节点类型、运行持久化、恢复落在 orchestration 包；既有六模式零改动是硬约束（FR-009）；契约文档联合刷新（FR-010）。
- **与 001（gatekeeper-governance）**：审批票据复用 `ApprovalRuntime`，审批与消费分离语义不变；节点事件进 001 审计流；不新增治理旁路。
- **与 002（session-versioning）**：运行锁定定义版本延续 002 版本化语义；工作流定义版本化接口不变。
- **与 013（multi-im-entry）**：通知渲染复用 `render_reply`；主动推送缺口如实声明（决策 #5），不改 013 渠道注册语义。
- **与 039（visual-orchestration）**：画布新增节点类型，YAML 权威与往返口径不变。
- **与 052（team-collaboration-mode，本批次）**：052 的异步执行与人工接管消费本特性的运行持久化与审批节点——**050 必须先于 052 落地**。
- **与 027（mongo-to-panweidb）**：新集合经兼容门面，双后端同口径（FR-011）。

## Non-Goals

- 不做自然语言生成 SOP（整合方案 P2 观察项）。
- 不做审批代理/会签/加签（多环节用串联节点表达）。
- 不做"超时自动批准"或任何异常默认放行。
- 不做全渠道 IM 主动推送承诺（clarify 定边界）。
- 不改既有六模式任何语义；不做跨实例分布式编排协调（恢复扫描为单活租约，非分布式调度）。
- 不拷贝 StaffDeck（AGPL-3.0）任何代码。