# Feature Specification: 三级配额（部门/项目级）

**Feature Branch**: `042-three-level-quota`

**Created**: 2026-10-23

**Status**: Implemented（2026-10-30 复核：23/24 任务完成；入口可发现性与驾驶舱展示待整改）

**Input**: 整合方案 §4.11：`quota_policy` 增加 `scope_type: team|project`（现仅 org/user）；管理端配置入口扩展；告警复用 008 异常枚举。文章口径：「三级配额（部门/项目/用户）+ 异常实时告警」。

> **设计来源**：本规约来自 `docs/MOGO-AgentOS整合方案.md` §4.11（2026-10-23 代码级勘察结论）。
>
> **性质说明（2026-10-30 复核更新）**：**本特性已实现，但入口不可发现**。`tasks.md` 已勾选 **23/24**（仅 T023 前端校验 + 手工联调未勾选）。后端 FR-001/002/004/005/006/007/009/010/011/012 到位；**三处缺口**：① **FR-003** —— `quota_projects` 独立分组按 ADR-8 需改为"项目 = 工作目录"（口径变更，非缺陷）；② **FR-008** —— 入口藏在弹窗二级 tab，且 `?open=quota` 深链打开的是租户额度而非部门/项目额度；③ **FR-011 前端半边** —— `/overview` 已返回 `quotaAnomalies`（`dashboard.py:967`），admin-web 全仓零引用，驾驶舱看不到配额告警。逐条核对见 `specs/035-cost-attribution/review-2026-10-30-dimension-source-audit.md` §5（FR 表）与 §6（问题清单）。
>
> **2026-10-30 口径修订（先看这条再读正文）**：
> 1. **「部门」= 部门树节点**（`org_units`），**原"团队"一词已全文替换为"部门"**（含 US1 标题、验收文案、错误文案模板）。产品语言此后**不再使用"团队"字样**；**机器标识符保留 `team`**（改枚举要迁数据、收益为零），对照表见下。
> 2. **「项目」按 ADR-8 收敛为「工作目录」**（`Decisions/ADR-8-统一项目概念-项目即工作目录.md`）：不再新建 `quota_projects` 这类独立分组实体，项目层 `scope_id` 直接取 `project_id`（= 会话绑定的 `workspace_id`，web 会话为 `"default"`）。正文 US2 描述的"自定义分组 + 内嵌成员"**已作废**。
> 3. **配置入口独立成菜单**：不再往「流量分配」页塞部门/项目额度 tab，改为 admin-web 独立菜单「项目管理」（只含项目，无部门 tab）。
> 4. **「企业额度」改称「租户额度」**：`scope_type='org'` 层就是租户层（"企业"与"租户"是同一个概念），对外文案统一改称「租户」；深链参数 `?open=enterprise` 相应改为 `?open=tenant`。
>
> **标识符对照表（改代码时按此表，**不要**顺手全局替换）**
>
> | 层面 | 保留 `team` 的标识符 |
> |---|---|
> | 存储枚举 | `scope_type = "team"` / `"project"` |
> | 返回字段 | `limitingScope ∈ {"team","project","org","user"}`；`teamRemainingPoints` / `teamTotalPoints` / `teamUsedPoints` / `teamResetAt` |
> | 概览字段 | `teamAssignedTokens` / `teamPolicyCount` |
> | 审计动作 | `action = setup_team` / `update_team` |
> | HTTP 端点 | `PUT /traffic-allocations/teams/{org_unit_id}/policy`（含同路径 `DELETE`） |
> | 集合名 | `user_quota_policies`（历史遗留，不改） |
>
> 判据很简单：**中文文案改「部门」，英文标识符一律不动**——两者在本文件中不交叉，替换时不会互相污染。
>
> 详细依据与整改批次见 `specs/035-cost-attribution/review-2026-10-30-dimension-source-audit.md` §6/§7.2/§9。
>
> **背景事实（代码级核实）**：`services/chat-api/app/core/quota_policy.py`（`services/admin-api/app/core/quota_policy.py` 为同名副本）现有集合 `org_quota_policies` / `user_quota_policies` / `user_quota_overrides` / `user_token_allocation_logs`（L11-18）；`scope_type` 现仅 org/user（`resolve_user_policy` L137-149、`sum_active_overrides` L152-168）；双层扣减取最小 `remaining = max(0, min(user_total - user_used, org_total - org_used))`（L266）；`grep scope_type.*(team|project|space)` 全仓无匹配；001 配额层复用该体系（`services/admin-api/app/governance/layers/quota.py` docstring L1-16 明示"001 配额层复用 020 配额体系"，`default_credit_checker` L31-54 调 `get_quota_summary`）；默认不限额为 020 decision 12（`services/admin-api/app/services/setup_quota.py` L37-47 `unlimited` 语义 + `quota_policy.py` L183-197 / L245-265 短路）。

## 定位（一句话）

把用量配额从"租户 + 用户"两级扩展为"部门/项目 + 租户 + 用户"三级：部门 = 部门树节点（复用 `org_units`，零新建实体），项目 = 工作目录（`project_id`，口径见修订 #2，**不新建实体**）；三层策略同时生效时扣减取三层最小、单层超限即拒（fail-closed，与现有语义一致），超限/接近阈值时复用 008 异常枚举与驾驶舱口径触发告警；管理端部门额度在既有流量分配页（`/organizations/traffic?open=quota`）配置，项目额度进独立菜单「项目管理」。

## 已定决策（2026-10-23，spec 撰写时拍板）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | 部门与项目的实体定义 | **部门 = 复用部门树节点**：`org_units`（`services/admin-api/app/repositories/directory_repository.py:9` `DEPARTMENT_COLLECTION = "org_units"`，树形见 `api/routes/directory.py:241-264`）+ 成员关系复用既有 `end_user_org_relations`，零新建实体；~~**项目 = 新建轻量自定义分组**（新集合 + 内嵌成员），因现有 `services/chat-api/app/api/endpoints/projects.py` 是桌面 Code 工作区绑定（其 docstring 明示"persists the user-visible project record"），非组织级分组，语义不可复用~~ —— **该结论已于 2026-10-30 按 ADR-8 推翻**：项目就是工作目录（`project_id`），上面这段"新建分组"的设计作废，保留原文仅为记录当时的判断 | plan.md §Project Structure |
| 2 | 三层扣减语义 | 现有双层"取最小"**扩展为三层取最小**：`remaining = max(0, min(team/project 层 remaining, user_remaining, org_remaining))`；不做逐层独立配额——那会改变"最严层决定放行"的现有语义，且与 001 门禁"remaining ≤ 0 即拒"的消费方式冲突 | `quota_policy.py` `get_quota_summary` |
| 3 | 默认策略 | 延续 020 decision 12：**未显式配置的层视为 unlimited、不参与取小**（查询无策略记录即跳过该层），与租户/用户默认不限额语义一致；部门/项目策略默认不预置 | `quota_policy.py` 三层解析函数 |
| 4 | 告警阈值与通道 | 阈值：`remaining ≤ 0`（超限，随拒绝动作触发）+ `remaining < 阈值比例 × total`（默认 20%，租户可配，"接近"告警）；通道：**复用 008 异常枚举口径**（`services/admin-api/app/api/dashboard_metrics.py:34` `ANOMALY_STATUSES` 增加 quota 类状态）+ 001 审计事件 + 008 驾驶舱异常展示；**不新建推送通道**（008 spec Non-Goal 明示"不实现告警推送（告警属独立能力）"） | `dashboard_metrics.py` + 审计落点 |
| 5 | 与 001 门禁配额层的接口边界 | 本特性管**策略管理层**（三层解析与扣减计算，产出 `remainingPoints` 及分层明细）；001 管**执行门禁点**（`governance/layers/quota.py` `default_credit_checker` 消费 `remainingPoints`，≤0 拒 429）。本特性**不修改 001 门禁代码**，仅扩展其依赖的数据源——门禁链末端位置与 fail-closed 语义不变 | `governance/layers/quota.py` 零改动 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 按部门树节点配置部门级额度并生效 (Priority: P1)

租户管理员在管理端「流量分配」页看到既有"租户总额度 / 成员额度"旁新增"部门额度"配置区：左侧为部门树（复用现有目录部门树），选中某部门节点即可设置该部门的本周期 Token 额度与周期；保存后，该部门成员的每次对话都受这道限额约束——部门剩余为 0 时成员被拒（错误信息指明"部门额度已用尽"）。

**Why this priority**: 三级配额的主场景就是"按部门包干"——租户按部门切预算时，没有部门层就退回到只控租户总盘子，部门间互相挤占。部门层同时是零新建实体的一层（复用部门树），投入最小、价值最直接。

**Independent Test**: 选一个有两个成员的测试部门，配置部门额度 = 成员 A 单独一次调用的用量；用成员 A 发起对话成功，成员 B 再发起被拒且错误信息含"部门"；删除该策略后两人均恢复可用（回归 unlimited 默认）。

**Acceptance Scenarios**:

1. **Given** 租户已有部门树且部门有成员，**When** 管理员选中部门节点配置部门额度（非 0）并保存，**Then** 策略落库（`user_quota_policies`，`scope_type=team`、`scope_id=部门ID`）并写一条 `user_token_allocation_logs` 审计。
2. **Given** 部门额度已配置，**When** 该部门成员发起对话，**Then** `get_quota_summary` 的 `remainingPoints` 包含部门层计算（部门剩余 = 部门总额度 − 当前成员周期用量之和）。
3. **Given** 部门剩余为 0 而租户/用户层仍有剩余，**When** 成员发起对话，**Then** 请求被拒（`QuotaExceededError`）且错误信息指明超限层为部门。
4. **Given** 某部门从未配置部门额度，**When** 其成员发起对话，**Then** 行为与现状完全一致（该层不参与扣减）。

---

### User Story 2 - 配置项目级额度（自定义分组 + 成员）并生效 (Priority: P1)

> **口径已作废**（2026-10-30，修订 #2）：项目 = 工作目录（`project_id`），没有"新建分组 + 勾选成员"这一步。本 US 保留作历史记录；现行口径为：项目额度按 `project_id` 配置，成员即该项目下产生过会话的用户（按当前归属聚合）。

租户管理员可新建"项目"分组（命名、备注、勾选成员），为分组设置本周期额度；跨部门的成员可加入同一项目，项目额度对该项目全部成员合计生效。项目分组与桌面 Code 的"项目"（工作区绑定）是两回事，管理端入口与命名明确区分。

**Why this priority**: "项目"是跨部门的横向协作单元（临时组、专项组），部门树表达不了；这是三级里唯一需要新建实体的一层，也是与桌面 Code `projects` 端点最易混淆的一层，必须显式定义边界。

**Independent Test**: 新建项目组 P 加入两名跨部门成员，配置额度 = 一次调用用量；成员甲调用成功、成员乙调用被拒且信息含"项目"；把成员乙移出 P 后乙恢复可用（无项目层约束）。

**Acceptance Scenarios**:

1. **Given** 管理员在配置区新建项目分组并添加成员，**When** 保存，**Then** 分组落库（新集合，含名称/成员/状态）并可再次编辑增删成员。
2. **Given** 项目分组已配置额度，**When** 任一成员发起对话，**Then** 项目层剩余 = 项目总额度 − 项目全部成员周期用量之和，并参与三层取小。
3. **Given** 项目剩余为 0 而其他层仍有剩余，**When** 成员发起对话，**Then** 被拒且错误信息指明超限层为项目。
4. **Given** 成员被移出项目分组，**When** 其再发起对话，**Then** 项目层不再对其生效（即时，无需等周期重置）。

---

### User Story 3 - 三层同时生效：取最小扣减 + 单层超限即拒 (Priority: P1)

某用户同时受部门策略、项目策略、租户策略、用户策略约束时，系统对四个已配置层分别计算剩余，最终可用剩余取各层最小；任一层剩余 ≤ 0 即拒绝请求（fail-closed）。用户命中多个部门/项目策略时（如兼任多个项目），该层取最严者。

**Why this priority**: 这是本特性的核心语义——三层配置如果各算各的（逐层独立），就会出现"每层都没超但总量爆了"或"最严层失效"的漏洞；取最小是现有双层语义的自然扩展，也是 001 门禁消费端（`remainingPoints`）唯一能无缝对接的形状。

**Independent Test**: 单测构造四层策略（team=1000/project=2000/user=3000/org=5000），分别注入各层周期用量，断言 `remainingPoints` 等于手算的四层取小；再把部门用量推到 1000，断言 `assert_quota_available` 抛错且信息含"部门"。

**Acceptance Scenarios**:

1. **Given** 四层策略均已配置且用量已知，**When** 查询/消费配额，**Then** `remainingPoints = max(0, min(各层 total − used))`，与手算一致。
2. **Given** 任一已配置层 remaining ≤ 0，**When** 发起对话，**Then** 拒绝，错误信息指明具体超限层（部门/项目/租户/用户）。
3. **Given** 用户同时属于两个项目组（均有策略），**When** 计算，**Then** 项目层取两个策略中 remaining 较小者（最严），再与部门/租户/用户层取小。
4. **Given** 租户被标记 `points_unlimited`（020 不限额短路），**When** 查询，**Then** 维持现有短路（直接返回 unlimited），不计算三层（与 `quota_policy.py` L183-197 行为一致）。

---

### User Story 4 - 超限与接近阈值时触发告警 (Priority: P2)

当任一层的剩余跌破 0（超限拒绝）或跌破阈值比例（默认 20%）时，系统记录一条 quota 类异常事件（008 异常枚举口径），进入审计与驾驶舱异常统计；管理员可在驾驶舱质量看板看到该类异常并下钻到租户/层/策略。

**Why this priority**: 文章的"异常实时告警"是三级配额的运营闭环——只有限额没有告警，超支永远后知后觉。但 008 明确不实现推送通道，本特性只把告警事件接进既有异常枚举与展示口径，优先级因此低于限额语义本身。

**Independent Test**: 构造部门层 remaining = total × 15%（< 20%），触发一次调用，断言产生一条可审计的 quota 接近告警事件且 `ANOMALY_STATUSES` 口径能统计到；再把 remaining 打到 0，断言超限告警事件与拒绝动作同时发生。

**Acceptance Scenarios**:

1. **Given** 某层 remaining 跌破阈值比例（默认 20%，可配），**When** 该层被消费（查询/扣减路径），**Then** 产生一条"接近阈值"告警事件（含 tenant/scope_type/scope_id/比例）。
2. **Given** 某层 remaining ≤ 0，**When** 请求被拒，**Then** 同时产生一条"超限"告警事件；同一租户同一层同一周期内不重复刷量（去重）。
3. **Given** 告警事件已产生，**When** 管理员查看驾驶舱质量看板异常统计，**Then** quota 类异常计入异常口径（`ANOMALY_STATUSES` 扩展后）且可下钻。
4. **Given** 本特性范围内，**When** 检查代码，**Then** 无任何新推送通道（IM/邮件/webhook）代码。

---

### User Story 5 - 既有 org/user 两层行为零回归 (Priority: P2)

未配置任何部门/项目策略的存量租户，其配额行为（含 unlimited 短路、个人空间赠送额度、用户临时追加 override、双层取小数值）与改造前逐字段一致；001 配额门禁层与既有配额测试全绿。

**Why this priority**: 配额是计费相邻链路，任何静默漂移都是生产事故；三层扩展必须证明"没配就是没变"，这是企业生产就绪的底线（宪法 II）。

**Independent Test**: 回归测试对同一 fixture 对比改造前后 `get_quota_summary` 输出（JSON 序列化相等）；`services/admin-api` 与 `services/chat-api` 既有配额相关测试（如 `tests/test_setup_quota.py`）全绿；`git diff` 断言 `governance/layers/quota.py` 零改动。

**Acceptance Scenarios**:

1. **Given** 存量租户无任何 team/project 策略记录，**When** 走完整查询/扣减/拒绝路径，**Then** 输出与改造前逐字段一致（含 `orgRemainingPoints`、`resetAt`、`status` 等）。
2. **Given** 用户有 `user_quota_overrides` 临时追加，**When** 计算，**Then** override 仍只作用于 user 层（不穿透部门/项目层），数值与现状一致。
3. **Given** 001 配额门禁层代码，**When** 对比改造前后，**Then** 零 diff，`default_credit_checker` 自动获得三层语义而无需修改。

---

### Edge Cases

- **用户同属多个部门/多个项目**：层内取最严（最小 remaining），层间再取小；不因多归属而放宽或重复扣减。
- **成员中途换部门/移出项目**：按**当前归属**解析策略；历史用量不随人迁移（周期窗口内部门/项目用量 = 当前成员用量之和），周期重置后自然恢复——这是明确的运营口径，写入管理端说明。
- **部门节点被删除**：其部门策略即时失效（按 unlimited 处理）并记审计，不阻断该部门遗留成员的调用。
- **策略 period 与租户 period 不一致**：各层按各自 `period_window` 计量（与现有 org/user 分层窗口语义一致），不强行统一。
- **项目分组与桌面 Code projects 端点混淆** ~~：新集合独立命名（`quota_projects`）、API 入口独立，docstring 明示与桌面 Code 工作区项目的区别。~~ —— **已作废**（修订 #2）：项目即工作目录，与桌面 Code 的 projects 是同一个概念，不存在混淆。
- **新层查询异常（DB 抖动）**：该层按 unlimited 跳过并记日志，不阻断主链路——与 `governance/layers/quota.py` L46-49"unreadable quota row must not block"的既有口径同源；不得因新层引入新的全量拒绝面。
- **个人空间（space_type=personal）**：部门/项目层不适用（成员关系属企业空间），维持个人空间现有分支。
- **策略 status=disabled**：org/user 层的既有语义是 `status != "active"` → 汇总 `status=disabled` → `assert_quota_available` 拒绝；部门/项目层采用**"视同未配置、不参与取小"**，避免"部门策略停用却阻断全租户"的过度连锁。两套语义并存是刻意的，口径写入 FR-006。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 支持 `scope_type ∈ {org, user, team, project}` 四层配额策略；team/project 策略 MUST 存于既有 `user_quota_policies` 集合（其 `(tenant_id, scope_type, scope_id)` 结构天然支持；集合名历史遗留不改，避免数据迁移）。
- **FR-002**: 部门层 MUST 以 `org_units` 部门树节点为 `scope_id`，成员关系 MUST 复用 `end_user_org_relations`（直接成员口径，不做子树自动聚合）。
- **FR-003** ~~项目层 MUST 使用新建轻量分组实体（集合 `quota_projects`，成员以内嵌数组维护），MUST 与桌面 Code `projects` 端点语义隔离（命名、入口、docstring 三处区分）~~ —— **已作废**（修订 #2）：项目层 `scope_id` 直接取 `project_id`，不再新建集合；原"与桌面 Code projects 语义隔离"的顾虑随之消失。
- **FR-004**: `get_quota_summary` MUST 对每个已配置层分别计算剩余，总结算 `remainingPoints = max(0, min(各已配置层 remaining))`，并在返回值中给出分层明细与 `limitingScope`（当前最严层）。
- **FR-005**: 任一已配置层 remaining ≤ 0 时 `assert_quota_available` MUST 拒绝（`QuotaExceededError`），错误信息 MUST 指明超限层（部门/项目/租户/用户）。
- **FR-006**: 未配置（无记录）或 `status != "active"` 的层 MUST 视为 unlimited、不参与取小；延续 020 decision 12 的默认不限额语义。
- **FR-007**: 用户命中多个部门/项目策略时，该层 MUST 取所有命中策略中 remaining 的最小者（最严）。
- **FR-008**: 管理端 MUST 在既有流量分配页（`apps/admin-web/src/views/organizations/TrafficAllocationsPage.vue`，路由 `/organizations/traffic?open=quota`）提供部门额度配置（部门树选择 + 额度/周期）与项目分组 CRUD（名称/成员/额度）入口，与既有 org/user 配置同级。
- **FR-009**: 部门/项目策略的创建与变更 MUST 写 `user_token_allocation_logs`（复用既有集合，`action` 字段区分 setup_team/setup_project/update 等），保证可审计。
- **FR-010**: 超限（remaining ≤ 0）与接近阈值（remaining < 阈值比例，默认 20%，租户可配）MUST 产生 quota 类告警事件，复用 008 异常枚举口径（`ANOMALY_STATUSES` 扩展）与审计落点；同租户同层同周期 MUST 去重。
- **FR-011**: 本特性 MUST NOT 新建任何告警推送通道（复用 008 驾驶舱展示口径 + 审计查询）。
- **FR-012**: 未配置任何部门/项目策略时，`get_quota_summary` 输出 MUST 与改造前逐字段一致；001 配额门禁层（`governance/layers/quota.py`）MUST NOT 被修改，其既有测试全绿。

### Key Entities

- **DepartmentQuotaPolicy**（原文档名 `TeamQuotaPolicy`，仅文档层改名，存储值仍 `scope_type="team"`）：`user_quota_policies` 中 `scope_type="team"`、`scope_id=<org_unit_id>` 的策略文档（额度/周期/状态/优先级），成员来自 `end_user_org_relations`。
- **ProjectGroup**（新增）~~：项目自定义分组，`{tenant_id, name, note, member_user_ids[], status, created_at, updated_at}`，与桌面 Code 工作区项目无关~~ —— **已作废**（修订 #2）：项目即工作目录，不新建分组实体。
- **ProjectQuotaPolicy**：`user_quota_policies` 中 `scope_type="project"`、`scope_id=<project_id>` 的策略文档。
- **QuotaSummary（扩展）**：既有返回结构新增 `teamRemainingPoints` / `projectRemainingPoints` / `limitingScope` 等分层明细字段；未配置层对应字段缺省（不回填哨兵值，延续 FR-037"明确标识而非算术哨兵"精神）。
- **QuotaAlertEvent**：quota 类异常事件 `{tenant_id, scope_type, scope_id, kind: exceeded|approaching, ratio, at}`，进 008 异常枚举口径与审计。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 三层（加租户/用户共四层）策略同时生效时，`remainingPoints` 等于各层取小的手算值（单测覆盖 team/project/user/org 组合矩阵）。
- **SC-002**: 任一单层超限即拒，错误信息 100% 指明超限层；001 门禁消费端无需改动即获得该语义。
- **SC-003**: 零部门/项目策略的租户，`get_quota_summary` 输出与改造前逐字段相等（等价回归测试），既有 `test_setup_quota.py` 等配额测试全绿。
- **SC-004**: 超限与 20% 接近阈值各产生一条可审计告警事件，`ANOMALY_STATUSES` 口径可统计，无重复刷量；无任何新推送通道代码（grep 断言）。
- **SC-005**: `git diff` 断言 `governance/layers/quota.py` 与 001/020 既有配额测试零改动、全绿。

## Assumptions

- 每个租户已有部门树（020 建租户时建根组织，FR-005），`end_user_org_relations` 是用户-部门关系的现成来源。
- 部门/项目层用量 = **当前成员**在各自周期窗口内的用量之和；成员中途变动不追溯历史归属（运营口径写入管理端说明文案）。
- token 计量继续走 `token_usage_logs`；035（成本归集）落地后与本特性共用同一计量源，但本特性不依赖 035（只需计量、不需要成本金额）。
- 告警消费方为 008 驾驶舱与审计查询；IM/邮件/ webhook 推送不在范围（008 Non-Goal）。
- 项目分组成员由租户管理员在管理端手工维护，不与 IM/SSO 组织自动同步（YAGNI，需要时后续）。
- admin-api 与 chat-api 两份 `quota_policy.py` 保持行为同步修改（现状即为同名副本，本特性不打破该格局）。

## 跨特性关系（被依赖方视角，双向声明）

- **与 001（gatekeeper-governance）**：001 配额层（`services/admin-api/app/governance/layers/quota.py` `default_credit_checker`）复用 020 配额体系读 `get_quota_summary`——本特性扩展该 summary 的层级语义，001 的消费点（`remainingPoints`）**自动获得三层限额而代码零改动**；本特性不改变门禁链末端位置与 fail-closed 语义，001 spec 中的配额层描述继续成立。
- **与 008（ops-dashboard）**：告警口径复用 008 异常枚举（`services/admin-api/app/api/dashboard_metrics.py:34` `ANOMALY_STATUSES`）与质量看板异常统计/下钻；008"不实现告警推送"的 Non-Goal 不变，本特性不新建推送通道。
- **与 020（platform-multi-tenancy）**：配额体系归属 020（org/user 两级 + decision 12 unlimited 默认 + FR-035~038 不限额口径）；本特性是 020 配额体系的**层级扩展**，集合结构、默认值语义、个人空间分支均延续 020，不回退。
- **与 035（成本归集补维，未来 spec）**：035 的成本归集与本特性共用 token 计量数据源（`token_usage_logs`）；两特性独立演进、互不阻塞——本特性产出"限额管控"，035 产出"花了多少钱"，消费方不同。

## 判定口径补充（2026-10-24，/speckit-checklist 回填）

> 来源：`checklists/requirements.md` 的 CHK001–CHK016 需求质量评审。本节只补"可执行口径"，**不改动上文 FR 的既有表述**；与上文冲突处，以本节为准并注明冲突原因。**实现现状结论（2026-10-30 更新）：本节写于 2026-10-24，当时结论是"未实现"；现已实现 23/24**（证据见本节末验收证据行）。下文各条尾注的"首期未实现"应读作**当时时点**的结论，当前实际缺口只剩三处：FR-003 项目口径、FR-008 入口可发现性、FR-011 驾驶舱展示。

- **R-1 实现现状核查（2026-10-24，代码级）——结论已于 2026-10-30 推翻**：当时判定"三层语义首期未实现"，原因是当日基线尚无实现提交。2026-10-30 复核，同样的检索已全部命中：`TEAM_SCOPE` / `PROJECT_SCOPE`（`chat-api/app/core/quota_policy.py:28-29`）、`_team_scope_ids`（`:206`）、`_layer_denial_message`（`:500`）、`services/admin-api/app/services/quota_projects.py`、`quota_alert_events` 的 producer 与 consumer 两侧、`quotaAnomalies`（`dashboard.py:967`）；`tasks.md` 勾选 23/24。**以下原文保留作当时时点的历史记录**：三层语义首期未实现。证据：`grep -rn "scope_type" --include=*.py services/ | grep -E "team|project"` 零命中；`grep -rn "quota_projects" --include=*.py services/` 零命中；`services/chat-api/app/core/quota_policy.py:137-149` 的 `resolve_user_policy` 只解析 `scope_type="user"`，`:266` 仍是双层 `max(0, min(user_total - user_used, org_total - org_used))`；`services/admin-api/app/api/routes/traffic_allocations.py` 只有 `org-policy`（L138）/`default-policy`（L178）/`users/{id}/policy`（L280）三个写端点，无部门/项目入口；`services/admin-api/app/api/dashboard_metrics.py:34` 的 `ANOMALY_STATUSES = ("failed", "timeout", "error")` 未含 quota 类。**建议落点**：T010/T012 改两份 `quota_policy.py`；T013 新建 `services/admin-api/app/services/quota_projects.py`；T014 扩 `traffic_allocations.py`；T015 扩 `dashboard_metrics.py`；告警新集合在 T011（chat-api 侧）与 T015（统计侧）各持一份常量，避免跨服务 import。

- **R-2 层解析顺序与扣减顺序（CHK001/CHK005）**：解析与评估**固定按 `team → project → org → user` 顺序**逐层求值，但"顺序"只决定**计算与归因的稳定次序**，不决定放行（放行由 R-6 的最小值与 fail-closed 决定）。每层求值三步：①按 `(tenant_id, scope_type, scope_id)` 点查策略；②该层 `used` 由 R-5 聚合；③`remaining = max(0, total - used)`。**不做有状态递减**：`get_quota_summary` 与 `assert_quota_available` 全程只读（现状即如此，`quota_policy.py:171-296`），"扣减"= 请求完成后由 `services/chat-api/app/llm/instrumented_client.py:215-244` 写 `token_usage_logs`，下次查询自然反映。**必须保留的短路次序**：`space_type != "enterprise"`（个人空间，L199-232）与 `org.points_unlimited`（L183-197）两条短路**先于**任何层解析，即部门/项目层在个人空间与 unlimited 租户下完全不参与（见 R-6 末段）。

- **R-3 部门层 = `org_units` 节点的复用方式（CHK001）**：`scope_type="team"`，`scope_id` = `str(org_units._id)`（字符串化的 back-end id，与 `traffic_allocations.py:97` 用 `to_backend_id(...)` 反解的口径一致；写入时直接用部门树节点 id，不做前缀编码）。成员来自 `end_user_org_relations`，查询条件 `{"tenant_id": tid, "org_id": scope_id}`，**取全部行、不以 `is_primary` 过滤**——一个用户有多条部门关系即同时命中多个部门策略，按 FR-007 层内取最严；`is_primary` 仅供管理端展示"主部门"（现状 `_department_maps` L73-79 只取 `is_primary` 是**展示口径**，不得作为限额解析口径，两处必须分家）。**不做子树聚合**（Non-Goals 已声明）：父部门策略不覆盖子部门成员。部门节点被删除 → 该部门策略即时失效、按 unlimited 处理并记审计（沿用 Edge Cases L121）。**（2026-10-24 时点未实现 → 2026-10-30 复核已落地，逐条核对见 035 核查 §5）**。

- **R-4 项目实体字段与孤儿策略处置（CHK002）**：~~新集合 `quota_projects`……三处显式区分。~~ **本节整体作废**（修订 #2，ADR-8）：项目不再有独立集合与成员表，`scope_id = project_id`；"孤儿策略"问题随之消失——项目归档后策略行保留即可，解析侧按项目 `status` 判定。以下原文保留仅作历史记录：新集合 `quota_projects`，文档字段严格为 `{tenant_id: str, name: str(≤64), note: str(≤200), member_user_ids: [str], status: "active"|"disabled"|"deleted", created_at, updated_at}`；`name` 在租户内唯一（`(tenant_id, name)` 唯一索引，软删除行不计入唯一性校验可由应用层实现，不建部分索引）。策略仍存 `user_quota_policies`（`scope_type="project"`, `scope_id=str(quota_projects._id)`），**项目文档不内嵌额度字段**，避免双写。**删除/停用处置**：项目 `status="deleted"` 时其策略即时失效（等同未配置、不参与取小）并写一条 `user_token_allocation_logs` 审计；**不物理删除策略行**（保留可回溯），因此存在"孤儿策略"是**预期状态**而非缺陷——解析侧必须先查项目文档、`status != "active"` 即跳过该策略（R-7 同一口径）。与桌面 Code `services/chat-api/app/api/endpoints/projects.py` 的隔离：集合名、API 前缀（`/traffic-allocations/projects`）、docstring 三处显式区分。**（2026-10-24 时点未实现 → 2026-10-30 复核已落地，逐条核对见 035 核查 §5）**。

- **R-5 层用量聚合形状与规模上界（CHK003）**：部门/项目层用量用**单次聚合**完成：`token_usage_logs.aggregate([{$match: {tenant_id, user_id: {$in: member_ids}, created_at: {$gte: start, $lt: end}, status: {$ne: "failed"}}}, {$group: {_id: null, tokens: {$sum: {$ifNull: ["$total_tokens", 0]}}}}])`——即把现 `sum_usage`（`quota_policy.py:122-134`）的 `user_id` 参数从 `str` 泛化为 `list[str]`，不新增 N 次往返。**上界**：单层成员集合截断到 5000（与 `traffic_allocations.py:73` 的 `to_list(length=50000)` 同量级但更保守）；超界时**只聚合前 5000 个成员并记 `warn` 日志**，不报错（避免把配置规模问题变成全量拒绝）。**归属口径**：按**当前**成员 ID 集合聚合，成员离开后其历史用量不再计入该部门/项目——与 Assumptions L166 一致，不追历史归属。**（2026-10-24 时点未实现 → 2026-10-30 复核已落地，逐条核对见 035 核查 §5）**。

- **R-6 跨层合并规则、`limitingScope` 与 unlimited 优先级（CHK005/CHK006/CHK011）**：`remainingPoints = max(0, min(各"已配置且 active"层 remaining))`；**无已配置层时**维持现状语义（`org_total <= 0 and user_total <= 0` → unlimited 短路，`quota_policy.py:248-265` 不动）。`limitingScope` 取值域固定为 `{"team", "project", "org", "user"}` 四值枚举，**承载层名、不承载 policy id 或 scope_id**；并列最小值时按 `team → project → org → user` 取第一个（更具体层优先归因），并在分层明细中同时给出全部并列层以便排查。分层明细字段：`teamRemainingPoints` / `projectRemainingPoints` / `teamTotalPoints` / `projectTotalPoints` / `teamUsedPoints` / `projectUsedPoints`，**未配置层该组字段整体不出现**（不写 `null`、不写 `0`、不写 `-1`），前端按 optional 处理；`remainingPoints` / `status` / `resetAt` / `totalPoints` / `usedPoints` / `orgTotalPoints` / `orgUsedPoints` / `orgRemainingPoints` **字段名与语义一律不变**（FR-012 零回归的硬约束）。**unlimited 优先级（显式定稿）**：`org.points_unlimited == True` 的短路**压过全部三层**——部门/项目层在该租户下不生效、不产生告警，理由是 FR-012/SC-003 的零回归优先，且 unlimited 是产品版本级的"不设上限"语义，局部限额会与之矛盾。**（2026-10-24 时点未实现 → 2026-10-30 复核已落地，逐条核对见 035 核查 §5）**。

- **R-7 `status != "active"` 与查询异常口径（CHK008/CHK012）**：team/project 层：策略不存在、`status != "active"`（含 `disabled`）、或所属 `quota_projects` 非 active → **该层视同未配置、不参与取小**（与 FR-006 一致）。**这与 org/user 层"策略未启用即拒"（`quota_policy.py:278` → `:287-288`）是两套语义**，差异已显式声明、不得统一：org/user 是"总闸"，停用即全停；team/project 是"局部包干"，停用只解除局部约束，否则停一个部门策略会连锁阻断该部门全部成员。**查询异常**：单层读失败（DB 抖动/超时）→ 该层按 unlimited 跳过 + 计数 + 落一条 `kind="layer_unreadable"` 告警事件（R-11），不阻断主链路（与 `services/admin-api/app/governance/layers/quota.py:46-49` fail-open 同源）；**三层同时异常仍放行**，但 `layer_unreadable` 事件的 `scope_type` 记 `"*"`、`scope_id` 记 `""`，保证"静默不限额"在驾驶舱可观测（这是新增约束，不是放宽）。**（2026-10-24 时点未实现 → 2026-10-30 复核已落地，逐条核对见 035 核查 §5）**。

- **R-8 超限错误码与错误契约（CHK009）**：保留 `QuotaExceededError(ValueError)`（`quota_policy.py:24`）类型不变（三处调用方 `dsh_chat.py:172`、`configured_models.py:399`、`scheduled_tasks/runner.py:39` 均按此捕获），**新增构造参数** `layer: str = ""`、`scope_id: str = ""`、`kind: str = "exceeded"`，并提供 `.layer` / `.scope_id` 属性供调用方结构化取用。**HTTP 状态码不改**：chat-api 走 402（`dsh_chat.py:174` `HTTPException(status_code=402, detail=str(exc))`），admin-api 001 门禁走 429（该层返回 denial reason、由门禁统一映射）——统一状态码会破坏既有前端与 001 契约，属跨特性改动，Not in scope。**文案模板**（按 `limitingScope` 选）：部门「部门额度已用尽（{部门名}），请联系租户管理员调整额度。」、项目「项目额度已用尽（{项目名}），请联系租户管理员调整额度。」、org/user 沿用现有两句原文（`quota_policy.py:294-295`）。`assert_quota_available` 判定改为"逐层检查任一 `remaining <= 0` 即抛"，与 R-6 的取小结果等价但能精确归因。

- **R-9 两份 `quota_policy.py` 副本的同步判据（CHK010）**：以**三个可执行判据**替代"行为同步"的口号：①逐函数体归一化 diff 为空（去掉 `import` 顺序与类型注解格式差异后，`grep -n "^async def \|^def "` 两侧函数名集合相等、同名函数体 AST dump 相等）；②新增测试 `tests/test_quota_three_level.py` 在**两个服务各存一份同内容文件**，对同一 fixture（四层策略 + 固定用量）断言 `get_quota_summary` 的 JSON 序列化结果相等；③既有 `test_quota_unlimited.py` / `test_setup_quota.py` 两侧全绿。**不追求字节级相同**：实测两文件已不同长度（chat-api 12431B / admin-api 11152B，差异在 `product_edition_fields` 等既有分支），字节相等是不可达目标。**（2026-10-24 时点未实现 → 2026-10-30 复核已落地，逐条核对见 035 核查 §5）**。

- **R-10 阈值比例的配置载体与区间（CHK007）**：字段落 `org_quota_policies.alert_threshold_ratio`（`float`，默认 `0.2`），读写入口为 `traffic_allocations.py` 的 `PUT /org-policy`（`OrgQuotaPayload` 增 `alertThresholdRatio: float = Field(default=0.2, gt=0, le=1)`，向后兼容：缺省不覆盖既有值）。**区间 `(0, 1]`**：`0` 无意义（永不触发"接近"）、`1` 表示"一启动就告警"，均允许但需前端提示；**不做按层单独配置**（YAGNI，层差异用绝对额度表达即可）。判定：`remaining < threshold_ratio * total` 且 `remaining > 0` 记 `approaching`；`remaining <= 0` 记 `exceeded`（与 US4 一致）。`total <= 0`（unlimited 层）**不产生 approaching**。**（2026-10-24 时点未实现 → 2026-10-30 复核已落地，逐条核对见 035 核查 §5）**。

- **R-11 告警事件结构、落库与去重（CHK004）**：新集合 `quota_alert_events`，文档 `{tenant_id, scope_type, scope_id, kind: "exceeded"|"approaching"|"layer_unreadable", ratio: float, layer_name: str, period_start: datetime, at: datetime, alert_key: str}`。**去重键** `alert_key = f"{tenant_id}:{scope_type}:{scope_id}:{kind}:{period_start.isoformat()}"`，写入用 `update_one({"alert_key": key}, {"$setOnInsert": {...}}, upsert=True)`（幂等，等价于唯一索引去重但不依赖建索引时机）；`period_start` 取该层 `period_window` 的 start（R-14），因此"同一周期内不重复刷量"由键天然保证。**写入位置**：`assert_quota_available` 的拒绝分支（`exceeded`）与 `get_quota_summary` 的层计算后（`approaching` 判定，只在该层被消费的查询路径触发）；写入失败**不回滚**主流程、只记 `warn`（告警是旁路）。**（2026-10-24 时点未实现 → 2026-10-30 复核已落地，逐条核对见 035 核查 §5）**。

- **R-12 与 008 异常枚举的复用方式（CHK013）**：**明确不改** `ANOMALY_STATUSES`（`services/admin-api/app/api/dashboard_metrics.py:34`）。原因：该元组被 `is_anomaly_status` 用于**过滤 `token_usage_logs.status` 字段**（`:73`），quota 告警是独立事件、不写 usage 行，把 `"quota_exceeded"` 塞进元组不会有任何行命中，SC-004 的"口径可统计"会变成假绿。**替代口径**：新增模块常量 `QUOTA_ALERT_KINDS = ("exceeded", "approaching", "layer_unreadable")`（与 R-11 的 `kind` 值域同源），驾驶舱"异常统计"新增独立 `quotaAnomalies` 分组（按 `scope_type` 分解 + 可按 `tenant_id`/`scope_id` 下钻），与既有 `ANOMALY_STATUSES` 统计**并列展示、互不覆盖**。若评审坚持"复用异常枚举"字面口径，可再把 `kind` 值映射进驾驶舱的 `anomalyKind` 维度（映射表 `{"exceeded": "error", "approaching": "warning"}`），但**不得**使其进入 `token_usage_logs.status` 的过滤条件。**不新建推送通道**（FR-011/008 Non-Goal 不变）。**（2026-10-24 时点未实现 → 2026-10-30 复核已落地，逐条核对见 035 核查 §5）**。

- **R-13 并发扣减的原子性（CHK014）**：**首期不做原子预扣**，口径与既有 org/user 双层完全一致（`assert_quota_available` 只读判定 → 请求执行 → `instrumented_client.py:215-244` 异步写 usage），因此存在 **TOCTOU 窗口 = 单次请求时长**：并发 N 个请求可能一起越过同一层限额，最多超额 `(N-1) × 单请求用量`。**这是已知边界、显式接受**，理由：①引入预扣需要"预留-结算-回滚"三态与周期键计数文档，会把本特性的实现面从"读扩展"变成"记账重构"，与本 spec 定位（策略管理层、001 门禁零改动）冲突；②既有双层语义下同样的窗口已存在，单方面收紧部门/项目层会造成层间不一致；③本期配额是**预算管控**而非强计费闸门。**后续落点（不在本期验收范围）**：以 `(tenant_id, scope_type, scope_id, period_start)` 为键的计数文档，用 `find_one_and_update` 条件更新 `$inc` + 条件 `$expr: {"$lte": ["$used", {"$subtract": ["$total", n]}]}`（pg_compat 已支持 `find_one_and_update`，见 `services/chat-api/app/core/pg_compat.py:1827`），无匹配即拒；需同批落地 TTL 与结算补偿。**SC 层面必须体现该边界**：SC-001 的正确性单测为串行断言，不得宣称"并发下严格不超额"。

- **R-14 周期重置口径与 `traffic_allocations` 页面关系（CHK015/CHK016）**：**周期重置**：各层按自身 `user_quota_policies.period` 走 `period_window`（沿用 `quota_policy.py:47-69`，`hourly|daily|monthly` + 租户 `timezone`），**不做跨层对齐**；顶层 `resetAt` **保持取 user 层 window end**（`:277` 现状不变，FR-012 零回归），分层明细各自新增 `teamResetAt` / `projectResetAt`（同组字段缺省规则见 R-6），并新增 `limitingResetAt`（当前 `limitingScope` 对应层的 window end）供前端"下次重置"提示——**三处并存的原因**：单一 `resetAt` 无法表达"部门层明日重置、用户层下月重置"，而改 `resetAt` 语义会破坏既有前端。**页面关系**：`apps/admin-web/src/views/organizations/TrafficAllocationsPage.vue` 同一路由（`/organizations/traffic?open=quota`）内新增"部门额度"与"项目分组"两个分区，**同一页面、不同 API 端点**：`GET /traffic-allocations/overview` **只做向后兼容扩展**（新增 `teamAssignedTokens`/`projectAssignedTokens`/`teamPolicyCount`/`projectPolicyCount`，既有 `assignedTokens`/`assignedPolicyCount` **仍只统计 `scope_type="user"`**，语义不动，避免既有展示数字漂移）；部门端点 `PUT /traffic-allocations/teams/{org_unit_id}/policy`、`DELETE` 同路径；项目端点 `GET|POST /traffic-allocations/projects`、`PUT|DELETE /traffic-allocations/projects/{project_id}`、`PUT /traffic-allocations/projects/{project_id}/policy`。所有写端点必须写 `user_token_allocation_logs`（FR-009，`action ∈ {setup_team, update_team, setup_project, update_project, delete_project}`）。

**验收证据（本节口径的可测判据；2026-10-30 已补齐命中数）**：①`grep -rn "scope_type" --include=*.py services/ | grep -E "team|project"` ≥1 命中且落在两份 `quota_policy.py` 与 `traffic_allocations.py`；②`pytest services/chat-api/tests/test_quota_three_level.py services/admin-api/tests/test_quota_three_level.py` 全绿，含"四层取小矩阵"（SC-001）与"零策略等价回归"（SC-003）；③`git diff --stat services/admin-api/app/governance/layers/quota.py` 输出为空（SC-005）；④`grep -rn "quota_alert_events" --include=*.py services/` 覆盖 producer 与 consumer 两侧，且 `ANOMALY_STATUSES` 仍为 `("failed","timeout","error")`；⑤`grep -rn "webhook\|smtplib\|send_mail" --include=*.py services/admin-api/app/services/quota_projects.py services/chat-api/app/core/quota_policy.py` 零命中（SC-004 无推送通道）；⑥当前基线（2026-10-30 复核，**已实现态**）：`grep -c "^- \[x\]" specs/042-three-level-quota/tasks.md` = **23 / 24**（仅 T023 前端校验 + 手工联调未勾选）；①的 `scope_type` 检索已命中，④的 `quota_alert_events` 已覆盖 producer 与 consumer 两侧，⑤无推送通道仍成立。

## 实现期补充（2026-10-24）

- **R-15 配置端点的展示口径**：`GET /traffic-allocations/teams` 返回部门名（取自 `org_units`，策略缺失时回落）；`GET /traffic-allocations/projects` 在项目文档基础上附带 `quotaTokens`/`period`/`policyStatus`（联查 `user_quota_policies` 的 `scope_type="project"`）。前端在未配置额度时显示「未设置额度」而非 `0`，**不得伪造数值**。
- **R-16 双副本单测口径**：两层单测文件 `tests/test_quota_three_level.py` 在 chat-api 与 admin-api **逐字节同内容**（R-9 的可测化形态）；admin-api 未安装 `pytest-asyncio`，故统一用文件内 `@async_test` 装饰器（`asyncio.run` 包装）而非 `pytest.mark.asyncio`。既有 fake（`tests/test_quota_unlimited.py::_MemCol`）需补 `find()`，因为三层解析要枚举部门成员（`col.find({...}).to_list()`）。
## Non-Goals

- 不新建告警推送通道（IM/邮件/webhook）——复用 008 展示口径 + 审计落点。
- 不修改 001 门禁层代码与门禁链结构（只扩展其数据源）。
- 不做部门子树自动聚合限额（部门额度 = 部门树节点直接成员；子树聚合留待后续需求）。
- 不做配额购买/计费/充值/透支（仅用量限额）。
- 不做部门/项目级的用户二次分配（`user_quota_overrides` 仍只作用于 user 层）。
- 不做跨租户部门/项目共享，不做个人空间的部门/项目层。
- 不改 `user_quota_policies` 集合名、不做存量数据迁移。
