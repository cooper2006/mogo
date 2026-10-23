# Feature Specification: 可信评级 L1–L4 资产分级（Agent/Skill/工作流可信度与权限强绑定）

**Feature Branch**: `036-trust-rating`

**Created**: 2026-10-23

**Status**: Draft

**Input**: 整合方案 §4.5「可信评级 L1–L4 资产分级」+ §3.4 评级映射 + §2.5 可信评级对照（`docs/MOGO-AgentOS整合方案.md`）

> **设计来源**：本规约把《企业 Agent OS 产品落地方案》的「可信评级 L1 实验级 / L2 辅助级 / L3 生产级 / L4 关键级」落地为 mogo 的资产分级能力。整合方案已明确定性：mogo 现有的 **L1–L5 自主级别 × R0–R4 风险级 25 格矩阵**（`governance/risk.py` / `schema.py`）语义是「这次调用放行到哪一档」，与本特性的「这个资产整体可不可信」是**两个维度**——本特性做映射与绑定，**不另起炉灶、不替换 001 矩阵**。
>
> **性质说明**：**全新特性，代码尚未开工**（与 031「回溯补规格」本质不同）。tasks.md 全部任务未勾选。

## 定位（一句话）

给资产（Agent / Skill / 工作流）打 L1–L4 可信评级，评级与权限强绑定：L1 实验级仅创建者本人可用、L2 辅助级输出必须人审后采用、L3 生产级可接入正式业务流、L4 关键级含写操作需双人复核；连续 3 周评测不达标自动降级并收缩权限（自主级上限随评级封顶）。

## 已定决策（2026-10-23，spec 撰写时拍板）

| # | 决策点 | 结论 | 依据 / 落点 |
| --- | --- | --- | --- |
| 1 | 评级初始值 | **新资产默认 L1**（fail-safe）。未经显式升级流程，任何路径不得获得 L2+ | 实验级语义最保守；与 001「未知工具默认 R0」的最小负担兜底同向 |
| 2 | 升级路径与授权 | 升级由**资产 owner 或持 `trust:manage` 权限码的管理员**发起；L2→L3、L3→L4 **必须同时满足质量达标证据**（首期消费 016 效果分；032 评测门禁就绪后切换为 032 评测结果，可配置、留审计） | 整合方案 §4.5「评级与权限强绑定」；016 `scoring.py` 阈值现成可兜底 |
| 3 | 降级触发 | **连续 21 天（3 周）评测不达标自动降一级**；开关**默认开启**、租户可配（关闭需管理员操作并留审计）；已为 L1 仍不达标 → 经 018 `set_state` 迁入 `deprecated`（可见性收敛，不直接 offline） | 整合方案 §4.5；018 `registry.py` 三态状态机复用 |
| 4 | L4 双人复核兼容方式 | **不新建第二张审批表**：扩展 001 `ApprovalRegistry`（`gate_approvals`）增加 `required_approvals` 与 `approvals[]`（记录两名不同 `decided_by`），consume 时校验双人齐备；**单人审批路径（`require_approval`）零改动、零回归** | `approval.py:46-145` 一次性票据 + 5min TTL + fail-closed 机制原样保留，仅加字段与校验 |
| 5 | 评级维度 | **资产级**（`asset_type ∈ {skill, agent, workflow}` + `asset_key`），**不细化到版本级**。理由：文章口径是「资产整体可不可靠」；版本级评级会把 018 已有的版本机制（契约版本、历史留档）重复一遍，机械变更量大，YAGNI | 整合方案 §3.4/§4.5；018 FR-5 版本化已覆盖版本关切 |
| 6 | 存储选型 | **新建 `trust_ratings` 集合**（键 `tenant_id + asset_type + asset_key`），不扩建 `skills` / `capability_assets` 表。理由：资产载体跨三类（Skill/工作流同表不同类型、能力资产单表、Agent 为运行时定义），统一软键关联避免改三张表；论证详见 plan.md | 001「矩阵即数据」模式（`schema.py` 种子集合）的同构做法 |
| 7 | 与 001 矩阵的关系 | 新增**评级→自主级上限映射表** `TRUST_TO_AUTONOMY_CAP`（L1→L1、L2→L2、L3→L3、L4→L5），canonical 常量 + 租户可覆盖 + fail-closed（同 001 矩阵的「数据即矩阵」模式）；**不修改 `AUTONOMY_MATRIX` 本体**，R4 红线恒拒不变 | 整合方案 §2.5/§3.4；`schema.py:32-38` 25 格表保持权威 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 资产打标与升级管理（Priority: P1）

治理管理员（或资产 owner）在 admin-web 查看资产的当前评级（默认 L1），按规则发起升级：L1→L2 仅需授权人批准；L2→L3、L3→L4 需系统校验质量达标证据（016 效果分，032 就绪后切换）后方可批准。每一次评级变更（升级/降级）都落 022 审计链，可回查 before/after/reason/evidence/actor。

**Why this priority**: 这是整个特性的数据底座——没有评级记录，门禁封顶、自动降级、驾驶舱分布都无输入。默认 L1 + 显式升级也直接兑现「实验级不放开」的安全承诺。

**Independent Test**: 新建一个 Skill（`services/admin-api/app/api/routes/skills.py` 创建路径）→ 断言 `trust_ratings` 自动生成 L1 记录；调评级变更 API 升级 L1→L2 → 断言审计事件含 before=L1/after=L2；未持 `trust:manage` 的用户调用变更 API → 403 fail-closed。

**Acceptance Scenarios**:

1. **Given** 任意新注册/新发现的资产，**When** 首次被评级服务读取，**Then** 自动落一条 `level=L1` 的记录（upsert，不重复创建）。
2. **Given** 资产为 L1，**When** 持 `trust:manage` 的管理员批准升级到 L2，**Then** 评级更新、审计事件落链，且资产立即按 L2 语义获得「租户内可见、输出带人审标记」。
3. **Given** 资产为 L2 且效果分低于 016 阈值（`scoring.py` `LOW_QUALITY_THRESHOLD=0.4`），**When** 尝试升级到 L3，**Then** 系统拒绝并提示质量不达标，评级不变、拒绝事件留审计。
4. **Given** 未授权用户，**When** 调用任何评级变更 API，**Then** 403 fail-closed，且不产生任何评级写入。

---

### User Story 2 - 评级绑定执行门禁：自主级上限封顶 + L4 写操作双人复核（Priority: P1）

资产调用经过 001 六层门禁时，审批层先按资产信任评级封顶本次调用的自主级（`effective_level = min(ctx.autonomy_level, TRUST_TO_AUTONOMY_CAP[trust_level])`），再查 `AUTONOMY_MATRIX`——L2 资产不允许 L4+ 自主级执行。此外，L4 关键级资产上的写操作（风险级 ≥ R2）除矩阵判定外，还必须获得**两名不同审批人**的批准（双人复核）才放行；单人审批路径行为不变。

**Why this priority**: 这是「评级与权限强绑定」的核心兑现点，也是本特性区别于纯标签系统的价值所在。没有它，评级只是显示字段。

**Independent Test**: 构造一个 L2 资产，以 L4 自主级发起一次 R1 工具调用 → 断言门禁按 L2 上限裁定（不进入 L4 语义）；构造一个 L4 资产发起 R2 写操作 → 仅一名审批人批准时 consume 被拒（fail-closed），第二名不同审批人批准后才放行；同时跑 001 既有单人审批用例确认零回归。

**Acceptance Scenarios**:

1. **Given** 资产评级为 L2，**When** 以自主级 L4 发起调用，**Then** 封顶为 L2 后查矩阵（如 L2×R1=allow、L2×R3=require_approval），L4 语义永不生效。
2. **Given** 资产评级为 L4 且调用风险级 ≥ R2，**When** 审批流挂起，**Then** 票据携带 `required_approvals=2`；第一名审批人 `decide` 后票据仍 pending，requester 无法 consume。
3. **Given** 双人复核票据已获两名**不同**审批人批准，**When** requester 携票 resume，**Then** consume 成功放行，审计记录两名审批人。
4. **Given** 同一审批人尝试对同一票据重复 decide，**When** 第二次 decide，**Then** 不计入有效批准数（防单人凑数）。
5. **Given** 非 L4 资产的普通 `require_approval` 挂起，**When** 单人批准后 resume，**Then** 行为与 001 现状完全一致（零回归）。

---

### User Story 3 - 连续 3 周评测不达标自动降级并收缩权限（Priority: P1）

系统按周期扫描持有评级的资产：对质量信号（016 效果分 / 032 评测结果）连续 21 天不达标的资产自动降一级，同步重算权限（自主级上限、双人复核要求、L1 owner-only 可见性），落审计并通知 owner；降至 L1 后仍不达标的迁入 018 `deprecated`。整个自动降级受租户级开关控制（默认开）。

**Why this priority**: 「连续 3 周不达标自动降级」是文章评级体系的自循环机制，也是回应「资产腐化」困境的自动化手段（与 011 低采纳淘汰、016 低质标记并列的第三条防线）。

**Independent Test**: 用可注入的时钟/数据构造一个 L3 资产连续 21 天低于阈值 → 跑一次降级扫描 → 断言评级降为 L2、审计事件含 `auto_downgrade`、门禁封顶随之变为 L2；把租户开关置为关闭 → 再跑扫描 → 断言无任何降级发生。

**Acceptance Scenarios**:

1. **Given** 资产连续 21 天质量不达标且开关开启，**When** 周期扫描执行，**Then** 评级降一级、`trust_ratings` 文档的连续不达标计数重置、审计事件与 owner 通知发出。
2. **Given** 资产已为 L1 且继续不达标，**When** 扫描执行，**Then** 经 018 `set_state(..., role=<授权角色>)` 迁入 `deprecated`，留审计。
3. **Given** 租户关闭了自动降级开关，**When** 扫描执行，**Then** 不触发任何自动降级（手动降级路径不受影响）。
4. **Given** 资产刚降级到 L2，**When** 随后发起原 L3 上限的调用，**Then** 门禁按 L2 封顶拒绝/降档（权限实际收缩，非仅改标签）。

---

### User Story 4 - admin-web 评级标识、变更记录与驾驶舱分布（Priority: P2）

admin-web 的技能/资产列表展示评级徽标（L1–L4 四色），资产详情展示当前评级、变更历史与质量证据；评级管理视图支持筛选、批量查看与分布统计；008 驾驶舱可消费评级分布数据（各档资产数量）。

**Why this priority**: 管理可见性是治理闭环的一半——评级若不可见、不可查，运营方无法回答「我们有多少资产够格上生产」。优先级低于 US1–US3 的能力本身，但不阻塞其独立验证。

**Independent Test**: `@vue/compiler-sfc` 编译新增/改动的 SFC 通过；在 admin-web 技能列表核对徽标与后端评级一致；驾驶舱评级分布接口返回计数与 `trust_ratings` 聚合一致。

**Acceptance Scenarios**:

1. **Given** 后端存在 L1–L4 混合评级的资产，**When** 打开 admin-web 技能列表，**Then** 每个资产行显示对应评级徽标，点击可查看变更历史（actor/before/after/reason/时间）。
2. **Given** 评级管理视图，**When** 按评级筛选，**Then** 列表正确过滤且分布计数与聚合 API 一致。
3. **Given** 008 驾驶舱，**When** 渲染评级分布，**Then** 数据来自 036 提供的聚合（不新建第二套统计管道）。

---

### Edge Cases

- **资产载体异构**：Skill/工作流同在 `skills` 集合（`skills.py` `SKILL_TYPES` 含 `workflow`），能力资产在 `capability_assets`，Agent 为运行时定义。`trust_ratings` 以 `asset_type + asset_key` 软键关联，三者的键生成规则必须在文档中固化（skill 用 skill_id、workflow 用 skill_id、agent 用 agent 标识），避免同键碰撞。
- **评级记录与资产不同步**：资产被删除/下线后评级记录成为孤儿——扫描器与清理任务 MUST 容忍（按 asset_key 查不到载体时跳过并记 warning，不抛异常中断扫描）。
- **降级与审批竞态**：降级生效时若有按旧评级挂起未消费的票据——已签发票据按 fail-closed 处理：consume 时若资产评级已不满足票据签发时的前提，拒绝消费（与 `approval.py` consume 的 fail-closed 语义一致）。
- **L4 双人复核与 R4 红线**：R4 恒拒（`risk.py:117-118`）优先于一切——L4 资产 + R4 工具仍为 deny，双人复核不能放开红线（constitution 原则 II）。
- **降级通知失败**：owner 通知（站内/邮件通道）失败不得阻塞降级与审计主流程（审计失败同样只记 warning，对齐 `registry.py` audit 的容错写法）。
- **租户开关被关闭后又开启**：关闭期间累积的连续不达标天数保留（不清零），恢复扫描后按完整窗口判定，避免「关几天开关绕过降级」。
- **质量信号缺失**：新资产无任何调用数据时效果分为 0（`scoring.py` 空样本口径）——不达标判定 MUST 要求最低样本量（`quality_metrics.py` `MIN_EFFECT_SAMPLES=20`），防止冷启动资产被误降级。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 支持资产可信评级四档 `L1|L2|L3|L4`，语义为：L1 实验级（仅创建者本人可用）、L2 辅助级（输出必须人审后采用）、L3 生产级（可接入正式业务流）、L4 关键级（含写操作需双人复核）；评级作用于**资产级**（`asset_type ∈ {skill, agent, workflow}` + `asset_key`），不细化到版本级。
- **FR-002**: 新注册/新发现的资产 MUST 默认 L1；除显式升级流程外，任何路径（含批量导入、同步、内部服务）不得直接写入 L2+。
- **FR-003**: 评级 MUST 持久化于 `trust_ratings` 集合（键 `tenant_id + asset_type + asset_key`，含 `level`/`below_streak_days`/`updated_by`/`updated_at`/`last_evidence`），与 `capability_assets` 等载体表**软关联**，不修改既有资产表结构。
- **FR-004**: 系统 MUST 提供评级管理 API（查询/筛选/详情/变更/开关配置），鉴权走 001 权限码模型：读 `trust:read`、写 `trust:manage`，未授权 fail-closed（403）。
- **FR-005**: 升级 MUST 由资产 owner 或持 `trust:manage` 的管理员发起；L2→L3、L3→L4 MUST 校验质量达标证据（首期 = 016 效果分 ≥ 阈值；032 就绪后切换为 032 评测结果，切换可配置且留审计）。
- **FR-006**: 每一次评级变更（手动升级/手动降级/自动降级/开关变更）MUST 落 022 审计链，含 actor、before、after、reason、证据摘要。
- **FR-007**: 系统 MUST 维护评级→自主级上限映射 `TRUST_TO_AUTONOMY_CAP = {L1: L1, L2: L2, L3: L3, L4: L5}`，形态为 canonical 常量 + `autonomy_matrix` 同构的租户覆盖存储 + fail-closed（覆盖值非法或缺失时回落常量），**不修改 `AUTONOMY_MATRIX` 25 格本体**。
- **FR-008**: 门禁审批层 MUST 在查矩阵前按评级封顶自主级：`effective_level = min(ctx.autonomy_level, cap(trust_level))`；资产无评级记录时按 L1 封顶（fail-safe）。
- **FR-009**: L4 资产的写操作（调用风险级 ≥ R2）MUST 要求双人复核：票据 `required_approvals=2` 且 `approvals[]` 含两名**不同**审批人才可消费；复用 `gate_approvals` 扩展，不新建第二张审批表；R4 红线恒拒不受双人复核影响。
- **FR-010**: 自动降级 MUST 支持租户级开关（默认开启）与窗口配置（默认连续 21 天）；扫描任务 MUST 复用 016 `SkillQualityScanner` 的周期任务模式（admin-api startup 注册、shutdown 停止）。
- **FR-011**: 触发自动降级时 MUST 原子完成：评级降一级、连续不达标计数重置、权限重算（自主级上限/双人复核要求/L1 可见性）、审计事件、owner 通知（通知失败不阻塞主流程）。
- **FR-012**: 资产已为 L1 且仍连续不达标时，自动降级流程 MUST 经 018 `set_state` 将其迁入 `deprecated`（授权角色调用，留审计），不得直接 `offline`（offline 保留给显式审批路径）。
- **FR-013**: 降级后权限 MUST 实际收缩：新调用按新上限即时生效；降级前已签发未消费的审批票据在 consume 时复核评级前提，不满足则拒绝（fail-closed）。
- **FR-014**: L1 资产 MUST 仅创建者本人可用：目录/市场列表（`skills.py` 列表路径）对非创建者隐藏 L1 资产，API 直读同样拒绝。
- **FR-015**: L2 资产的调用结果 MUST 携带人审标记（如 `human_review_required`），编排/DAG 自动节点不得将 L2 输出作为终态自动采用。
- **FR-016**: 评级分布 MUST 可供 008 驾驶舱消费（聚合计数端点或复用列表统计），不新建第二套统计管道。
- **FR-017**: 质量信号来源 MUST 可配置：默认优先 032 评测结果（032 就绪前以 016 效果分 `compute_effect_score` 兜底）；切换来源 MUST 留审计；样本量不足（< `MIN_EFFECT_SAMPLES`）时 MUST 跳过不达标判定。

### Key Entities

- **TrustRating**：`{tenant_id, asset_type, asset_key, level, previous_level, below_streak_days, reason, last_evidence, updated_by, updated_at}`，`trust_ratings` 集合的一行；`below_streak_days` 由扫描器按日累计、达标或变更时重置。
- **TRUST_TO_AUTONOMY_CAP**：评级→自主级上限映射常量（L1→L1、L2→L2、L3→L3、L4→L5），租户覆盖存于 `autonomy_matrix` 同构集合（如 `trust_autonomy_caps`），fail-closed。
- **ApprovalTicket（扩展）**：`gate_approvals` 文档新增 `required_approvals`（默认 1）与 `approvals[]`（`[{decided_by, decided_at}]`）；双人复核 = `required_approvals=2` 且两名不同 `decided_by`。单人路径字段缺省即 1，行为不变。
- **DowngradeScanState**：扫描器游标与最近一次扫描摘要（单文档，仿 `quality_metrics.py` `COLLECTOR_STATE_COLLECTION` 的高水位文档模式），用于可观测与断点续扫。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 新资产 100% 默认 L1；测试证明不存在绕过升级流程获得 L2+ 的路径（含批量/同步/内部服务写入）。
- **SC-002**: L2 资产以 L4+ 自主级发起的调用 100% 被门禁按 L2 上限裁定（单测 + 集成测试双重证明）。
- **SC-003**: L4 资产写操作在仅一名审批人批准时 100% 被拒（fail-closed），双人不同批准后才执行；001 既有单人审批用例零回归。
- **SC-004**: 连续 21 天不达标资产 100% 触发自动降级 + 权限收缩 + 审计；租户开关关闭时 0 触发。
- **SC-005**: 评级变更（含自动降级）100% 可在 022 审计链回查 before/after/reason/actor。
- **SC-006**: 008 驾驶舱可展示 L1–L4 分布，计数与 `trust_ratings` 聚合一致（无第二套数据源）。

## Assumptions

- 资产载体现状：Skill 与工作流同在 `skills` 集合（`skills.py` `SKILL_TYPES = {"writing_style", "workflow", "ordinary", "expert_package"}`），能力资产在 `capability_assets` 集合（`registry.py` `COLLECTION`），Agent 为运行时定义经 `asset_key` 引用；`trust_ratings` 不要求三表同构。
- 016 效果分机制已生产可用（`scoring.py` 阈值 0.4 / 7 天，`quality_metrics.py` 扫描器 + 最小样本量 20），可作为 032 就绪前的过渡质量信号。
- 001 `ApprovalRegistry`（`approval.py:46-145`）的一次性票据 + 5min TTL + fail-closed 机制可向后兼容地扩展 `required_approvals`，不破坏既有 `decide`/`consume` 语义。
- 周期任务沿用 admin-api `main.py` 的 `on_event("startup")`/`on_event("shutdown")` 启停模式（`_QUALITY_SCANNER` 为样板），不引入新调度框架。
- 审计复用 022 既有落点（`gate_events` / 审计链），不新建审计集合。
- 032（`specs/032-eval-gate`，另一代理同步撰写）的评测结果契约以 032 spec 为准；本特性只声明消费关系，不在 032 就绪前阻塞任何功能（016 兜底）。

## 跨特性关系（被依赖方视角，2026-10-23 双向声明）

- **与 001（gatekeeper-governance）**：036 消费 001 的 `AUTONOMY_MATRIX`（`schema.py`）、`ApprovalRegistry`（`approval.py`，扩展双人复核）、RBAC 权限码模型与审计落点；036 **不修改** 25 格矩阵与 R4 红线，仅在矩阵查询前增加评级封顶。001 侧除 `approval.py` 的向后兼容扩展外无改动。
- **与 016（skill-market-hardening）**：036 消费 016 效果分（`quality_metrics.py` / `scoring.py`）作为质量达标与降级的输入信号；016 不依赖 036（036 失败不得影响 016 市场排序）。
- **与 018（capability-asset-registration）**：036 复用 018 资产状态机（`registry.py` `ASSET_STATES` / `set_state`）执行 L1 持续不达标时的 `deprecated` 迁移；036 不改 018 表结构与状态语义；018 不依赖 036。
- **与 032（eval-gate，同步撰写中）**：036 消费 032 的评测结果作为升级/降级的权威证据；**032 不依赖 036**（单向依赖，关系声明以 032 spec 为准）。
- **与 008（ops-dashboard）**：036 提供评级分布聚合供 008 驾驶舱展示；008 不依赖 036 的写入路径（036 不可用时分布区降级隐藏，不阻塞驾驶舱其他区）。
- **与 006（position-rbac-admin）**：评级管理权限码（`trust:read` / `trust:manage`）注册为 001 权限码模型的 `trust` resource 维度（沿用 001 FR「下游特性注册 resource」扩展点，如 014 `bizdata` / 015 `kg`）。

## Non-Goals

- 不新建第二套评级体系，不替换或修改 001 的 L1–L5 × R0–R4 执行门禁矩阵（本特性是资产维度的映射与绑定）。
- 不实现评测本身（黄金测试集、评测执行、幻觉率代理指标——属 032 评测门禁）。
- 不做版本级评级（版本关切由 018 契约版本化覆盖）。
- 不改变 018 资产状态机语义与 offline 审批路径（仅复用 `set_state` 做 deprecated 迁移）。
- 不新建审批表（复用 `gate_approvals` 扩展）。
- 不做跨租户评级共享或评级市场（评级是租户内治理数据）。
