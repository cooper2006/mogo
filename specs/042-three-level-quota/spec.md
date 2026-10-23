# Feature Specification: 三级配额（团队/项目级）

**Feature Branch**: `042-three-level-quota`

**Created**: 2026-10-23

**Status**: Draft

**Input**: 整合方案 §4.11：`quota_policy` 增加 `scope_type: team|project`（现仅 org/user）；管理端配置入口扩展；告警复用 008 异常枚举。文章口径：「三级配额（团队/项目/用户）+ 异常实时告警」。

> **设计来源**：本规约来自 `docs/MOGO-AgentOS整合方案.md` §4.11（2026-10-23 代码级勘察结论）。
>
> **性质说明**：**全新特性，代码尚未开工**——与 031 的"回溯补规格"（代码先于 spec）本质不同，本特性先把规约拍板再进入实现；`tasks.md` 全部任务未勾选。
>
> **背景事实（代码级核实）**：`services/chat-api/app/core/quota_policy.py`（`services/admin-api/app/core/quota_policy.py` 为同名副本）现有集合 `org_quota_policies` / `user_quota_policies` / `user_quota_overrides` / `user_token_allocation_logs`（L11-18）；`scope_type` 现仅 org/user（`resolve_user_policy` L137-149、`sum_active_overrides` L152-168）；双层扣减取最小 `remaining = max(0, min(user_total - user_used, org_total - org_used))`（L266）；`grep scope_type.*(team|project|space)` 全仓无匹配；001 配额层复用该体系（`services/admin-api/app/governance/layers/quota.py` docstring L1-16 明示"001 配额层复用 020 配额体系"，`default_credit_checker` L31-54 调 `get_quota_summary`）；默认不限额为 020 decision 12（`services/admin-api/app/services/setup_quota.py` L37-47 `unlimited` 语义 + `quota_policy.py` L183-197 / L245-265 短路）。

## 定位（一句话）

把用量配额从"租户 + 用户"两级扩展为"团队/项目 + 租户 + 用户"三级：团队 = 部门树节点（复用 `org_units`，零新建实体），项目 = 自定义分组（新建轻量实体）；三层策略同时生效时扣减取三层最小、单层超限即拒（fail-closed，与现有语义一致），超限/接近阈值时复用 008 异常枚举与驾驶舱口径触发告警；管理端在既有流量分配页（`/organizations/traffic?open=quota`）旁扩展团队/项目额度配置。

## 已定决策（2026-10-23，spec 撰写时拍板）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | 团队与项目的实体定义 | **团队 = 复用部门树节点**：`org_units`（`services/admin-api/app/repositories/directory_repository.py:9` `DEPARTMENT_COLLECTION = "org_units"`，树形见 `api/routes/directory.py:241-264`）+ 成员关系复用既有 `end_user_org_relations`，零新建实体；**项目 = 新建轻量自定义分组**（新集合 + 内嵌成员），因现有 `services/chat-api/app/api/endpoints/projects.py` 是桌面 Code 工作区绑定（其 docstring 明示"persists the user-visible project record"），非组织级分组，语义不可复用 | plan.md §Project Structure |
| 2 | 三层扣减语义 | 现有双层"取最小"**扩展为三层取最小**：`remaining = max(0, min(team/project 层 remaining, user_remaining, org_remaining))`；不做逐层独立配额——那会改变"最严层决定放行"的现有语义，且与 001 门禁"remaining ≤ 0 即拒"的消费方式冲突 | `quota_policy.py` `get_quota_summary` |
| 3 | 默认策略 | 延续 020 decision 12：**未显式配置的层视为 unlimited、不参与取小**（查询无策略记录即跳过该层），与租户/用户默认不限额语义一致；团队/项目策略默认不预置 | `quota_policy.py` 三层解析函数 |
| 4 | 告警阈值与通道 | 阈值：`remaining ≤ 0`（超限，随拒绝动作触发）+ `remaining < 阈值比例 × total`（默认 20%，租户可配，"接近"告警）；通道：**复用 008 异常枚举口径**（`services/admin-api/app/api/dashboard_metrics.py:34` `ANOMALY_STATUSES` 增加 quota 类状态）+ 001 审计事件 + 008 驾驶舱异常展示；**不新建推送通道**（008 spec Non-Goal 明示"不实现告警推送（告警属独立能力）"） | `dashboard_metrics.py` + 审计落点 |
| 5 | 与 001 门禁配额层的接口边界 | 本特性管**策略管理层**（三层解析与扣减计算，产出 `remainingPoints` 及分层明细）；001 管**执行门禁点**（`governance/layers/quota.py` `default_credit_checker` 消费 `remainingPoints`，≤0 拒 429）。本特性**不修改 001 门禁代码**，仅扩展其依赖的数据源——门禁链末端位置与 fail-closed 语义不变 | `governance/layers/quota.py` 零改动 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 按部门树节点配置团队级额度并生效 (Priority: P1)

租户管理员在管理端「流量分配」页看到既有"企业总额度 / 成员额度"旁新增"团队额度"配置区：左侧为部门树（复用现有目录部门树），选中某部门节点即可设置该团队的本周期 Token 额度与周期；保存后，该部门成员的每次对话都受这道限额约束——团队剩余为 0 时成员被拒（错误信息指明"团队额度已用尽"）。

**Why this priority**: 三级配额的主场景就是"部门/团队包干"——企业按部门切预算时，没有团队层就退回到只控租户总盘子，部门间互相挤占。团队层同时是零新建实体的一层（复用部门树），投入最小、价值最直接。

**Independent Test**: 选一个有两个成员的测试部门，配置团队额度 = 成员 A 单独一次调用的用量；用成员 A 发起对话成功，成员 B 再发起被拒且错误信息含"团队"；删除该策略后两人均恢复可用（回归 unlimited 默认）。

**Acceptance Scenarios**:

1. **Given** 租户已有部门树且部门有成员，**When** 管理员选中部门节点配置团队额度（非 0）并保存，**Then** 策略落库（`user_quota_policies`，`scope_type=team`、`scope_id=部门ID`）并写一条 `user_token_allocation_logs` 审计。
2. **Given** 团队额度已配置，**When** 该团队成员发起对话，**Then** `get_quota_summary` 的 `remainingPoints` 包含团队层计算（团队剩余 = 团队总额度 − 当前成员周期用量之和）。
3. **Given** 团队剩余为 0 而租户/用户层仍有剩余，**When** 成员发起对话，**Then** 请求被拒（`QuotaExceededError`）且错误信息指明超限层为团队。
4. **Given** 某部门从未配置团队额度，**When** 其成员发起对话，**Then** 行为与现状完全一致（该层不参与扣减）。

---

### User Story 2 - 配置项目级额度（自定义分组 + 成员）并生效 (Priority: P1)

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

某用户同时受团队策略、项目策略、租户策略、用户策略约束时，系统对四个已配置层分别计算剩余，最终可用剩余取各层最小；任一层剩余 ≤ 0 即拒绝请求（fail-closed）。用户命中多个团队/项目策略时（如兼任多个项目），该层取最严者。

**Why this priority**: 这是本特性的核心语义——三层配置如果各算各的（逐层独立），就会出现"每层都没超但总量爆了"或"最严层失效"的漏洞；取最小是现有双层语义的自然扩展，也是 001 门禁消费端（`remainingPoints`）唯一能无缝对接的形状。

**Independent Test**: 单测构造四层策略（team=1000/project=2000/user=3000/org=5000），分别注入各层周期用量，断言 `remainingPoints` 等于手算的四层取小；再把团队用量推到 1000，断言 `assert_quota_available` 抛错且信息含"团队"。

**Acceptance Scenarios**:

1. **Given** 四层策略均已配置且用量已知，**When** 查询/消费配额，**Then** `remainingPoints = max(0, min(各层 total − used))`，与手算一致。
2. **Given** 任一已配置层 remaining ≤ 0，**When** 发起对话，**Then** 拒绝，错误信息指明具体超限层（团队/项目/租户/用户）。
3. **Given** 用户同时属于两个项目组（均有策略），**When** 计算，**Then** 项目层取两个策略中 remaining 较小者（最严），再与团队/租户/用户层取小。
4. **Given** 租户被标记 `points_unlimited`（020 不限额短路），**When** 查询，**Then** 维持现有短路（直接返回 unlimited），不计算三层（与 `quota_policy.py` L183-197 行为一致）。

---

### User Story 4 - 超限与接近阈值时触发告警 (Priority: P2)

当任一层的剩余跌破 0（超限拒绝）或跌破阈值比例（默认 20%）时，系统记录一条 quota 类异常事件（008 异常枚举口径），进入审计与驾驶舱异常统计；管理员可在驾驶舱质量看板看到该类异常并下钻到租户/层/策略。

**Why this priority**: 文章的"异常实时告警"是三级配额的运营闭环——只有限额没有告警，超支永远后知后觉。但 008 明确不实现推送通道，本特性只把告警事件接进既有异常枚举与展示口径，优先级因此低于限额语义本身。

**Independent Test**: 构造团队层 remaining = total × 15%（< 20%），触发一次调用，断言产生一条可审计的 quota 接近告警事件且 `ANOMALY_STATUSES` 口径能统计到；再把 remaining 打到 0，断言超限告警事件与拒绝动作同时发生。

**Acceptance Scenarios**:

1. **Given** 某层 remaining 跌破阈值比例（默认 20%，可配），**When** 该层被消费（查询/扣减路径），**Then** 产生一条"接近阈值"告警事件（含 tenant/scope_type/scope_id/比例）。
2. **Given** 某层 remaining ≤ 0，**When** 请求被拒，**Then** 同时产生一条"超限"告警事件；同一租户同一层同一周期内不重复刷量（去重）。
3. **Given** 告警事件已产生，**When** 管理员查看驾驶舱质量看板异常统计，**Then** quota 类异常计入异常口径（`ANOMALY_STATUSES` 扩展后）且可下钻。
4. **Given** 本特性范围内，**When** 检查代码，**Then** 无任何新推送通道（IM/邮件/webhook）代码。

---

### User Story 5 - 既有 org/user 两层行为零回归 (Priority: P2)

未配置任何团队/项目策略的存量租户，其配额行为（含 unlimited 短路、个人空间赠送额度、用户临时追加 override、双层取小数值）与改造前逐字段一致；001 配额门禁层与既有配额测试全绿。

**Why this priority**: 配额是计费相邻链路，任何静默漂移都是生产事故；三层扩展必须证明"没配就是没变"，这是企业生产就绪的底线（宪法 II）。

**Independent Test**: 回归测试对同一 fixture 对比改造前后 `get_quota_summary` 输出（JSON 序列化相等）；`services/admin-api` 与 `services/chat-api` 既有配额相关测试（如 `tests/test_setup_quota.py`）全绿；`git diff` 断言 `governance/layers/quota.py` 零改动。

**Acceptance Scenarios**:

1. **Given** 存量租户无任何 team/project 策略记录，**When** 走完整查询/扣减/拒绝路径，**Then** 输出与改造前逐字段一致（含 `orgRemainingPoints`、`resetAt`、`status` 等）。
2. **Given** 用户有 `user_quota_overrides` 临时追加，**When** 计算，**Then** override 仍只作用于 user 层（不穿透团队/项目层），数值与现状一致。
3. **Given** 001 配额门禁层代码，**When** 对比改造前后，**Then** 零 diff，`default_credit_checker` 自动获得三层语义而无需修改。

---

### Edge Cases

- **用户同属多个部门/多个项目**：层内取最严（最小 remaining），层间再取小；不因多归属而放宽或重复扣减。
- **成员中途换部门/移出项目**：按**当前归属**解析策略；历史用量不随人迁移（周期窗口内团队/项目用量 = 当前成员用量之和），周期重置后自然恢复——这是明确的运营口径，写入管理端说明。
- **部门节点被删除**：其团队策略即时失效（按 unlimited 处理）并记审计，不阻断该部门遗留成员的调用。
- **策略 period 与租户 period 不一致**：各层按各自 `period_window` 计量（与现有 org/user 分层窗口语义一致），不强行统一。
- **项目分组与桌面 Code projects 端点混淆**：新集合独立命名（`quota_projects`）、API 入口独立，docstring 明示与桌面 Code 工作区项目的区别。
- **新层查询异常（DB 抖动）**：该层按 unlimited 跳过并记日志，不阻断主链路——与 `governance/layers/quota.py` L46-49"unreadable quota row must not block"的既有口径同源；不得因新层引入新的全量拒绝面。
- **个人空间（space_type=personal）**：团队/项目层不适用（成员关系属企业空间），维持个人空间现有分支。
- **策略 status=disabled**：该层视为未配置（不参与取小），与 org/user 层"策略未启用即拒"的既有区别保持——hmm wait. Existing: `status != "active"` → summary status=disabled → assert raises. For team/project layers, what if the team policy exists but is disabled? Simplest consistent: 该层不参与（视同未配置），避免"团队策略停用却阻断全租户"的过度连锁。写进 FR-006 or edge case. I'll put it in FR-006.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 支持 `scope_type ∈ {org, user, team, project}` 四层配额策略；team/project 策略 MUST 存于既有 `user_quota_policies` 集合（其 `(tenant_id, scope_type, scope_id)` 结构天然支持；集合名历史遗留不改，避免数据迁移）。
- **FR-002**: 团队层 MUST 以 `org_units` 部门树节点为 `scope_id`，成员关系 MUST 复用 `end_user_org_relations`（直接成员口径，不做子树自动聚合）。
- **FR-003**: 项目层 MUST 使用新建轻量分组实体（集合 `quota_projects`，成员以内嵌数组维护），MUST 与桌面 Code `projects` 端点语义隔离（命名、入口、docstring 三处区分）。
- **FR-004**: `get_quota_summary` MUST 对每个已配置层分别计算剩余，总结算 `remainingPoints = max(0, min(各已配置层 remaining))`，并在返回值中给出分层明细与 `limitingScope`（当前最严层）。
- **FR-005**: 任一已配置层 remaining ≤ 0 时 `assert_quota_available` MUST 拒绝（`QuotaExceededError`），错误信息 MUST 指明超限层（团队/项目/租户/用户）。
- **FR-006**: 未配置（无记录）或 `status != "active"` 的层 MUST 视为 unlimited、不参与取小；延续 020 decision 12 的默认不限额语义。
- **FR-007**: 用户命中多个团队/项目策略时，该层 MUST 取所有命中策略中 remaining 的最小者（最严）。
- **FR-008**: 管理端 MUST 在既有流量分配页（`apps/admin-web/src/views/organizations/TrafficAllocationsPage.vue`，路由 `/organizations/traffic?open=quota`）提供团队额度配置（部门树选择 + 额度/周期）与项目分组 CRUD（名称/成员/额度）入口，与既有 org/user 配置同级。
- **FR-009**: 团队/项目策略的创建与变更 MUST 写 `user_token_allocation_logs`（复用既有集合，`action` 字段区分 setup_team/setup_project/update 等），保证可审计。
- **FR-010**: 超限（remaining ≤ 0）与接近阈值（remaining < 阈值比例，默认 20%，租户可配）MUST 产生 quota 类告警事件，复用 008 异常枚举口径（`ANOMALY_STATUSES` 扩展）与审计落点；同租户同层同周期 MUST 去重。
- **FR-011**: 本特性 MUST NOT 新建任何告警推送通道（复用 008 驾驶舱展示口径 + 审计查询）。
- **FR-012**: 未配置任何团队/项目策略时，`get_quota_summary` 输出 MUST 与改造前逐字段一致；001 配额门禁层（`governance/layers/quota.py`）MUST NOT 被修改，其既有测试全绿。

### Key Entities

- **TeamQuotaPolicy**：`user_quota_policies` 中 `scope_type="team"`、`scope_id=<org_unit_id>` 的策略文档（额度/周期/状态/优先级），成员来自 `end_user_org_relations`。
- **ProjectGroup**（新增）：项目自定义分组，`{tenant_id, name, note, member_user_ids[], status, created_at, updated_at}`，与桌面 Code 工作区项目无关。
- **ProjectQuotaPolicy**：`user_quota_policies` 中 `scope_type="project"`、`scope_id=<project_id>` 的策略文档。
- **QuotaSummary（扩展）**：既有返回结构新增 `teamRemainingPoints` / `projectRemainingPoints` / `limitingScope` 等分层明细字段；未配置层对应字段缺省（不回填哨兵值，延续 FR-037"明确标识而非算术哨兵"精神）。
- **QuotaAlertEvent**：quota 类异常事件 `{tenant_id, scope_type, scope_id, kind: exceeded|approaching, ratio, at}`，进 008 异常枚举口径与审计。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 三层（加租户/用户共四层）策略同时生效时，`remainingPoints` 等于各层取小的手算值（单测覆盖 team/project/user/org 组合矩阵）。
- **SC-002**: 任一单层超限即拒，错误信息 100% 指明超限层；001 门禁消费端无需改动即获得该语义。
- **SC-003**: 零团队/项目策略的租户，`get_quota_summary` 输出与改造前逐字段相等（等价回归测试），既有 `test_setup_quota.py` 等配额测试全绿。
- **SC-004**: 超限与 20% 接近阈值各产生一条可审计告警事件，`ANOMALY_STATUSES` 口径可统计，无重复刷量；无任何新推送通道代码（grep 断言）。
- **SC-005**: `git diff` 断言 `governance/layers/quota.py` 与 001/020 既有配额测试零改动、全绿。

## Assumptions

- 每个租户已有部门树（020 建租户时建根组织，FR-005），`end_user_org_relations` 是用户-部门关系的现成来源。
- 团队/项目层用量 = **当前成员**在各自周期窗口内的用量之和；成员中途变动不追溯历史归属（运营口径写入管理端说明文案）。
- token 计量继续走 `token_usage_logs`；035（成本归集）落地后与本特性共用同一计量源，但本特性不依赖 035（只需计量、不需要成本金额）。
- 告警消费方为 008 驾驶舱与审计查询；IM/邮件/ webhook 推送不在范围（008 Non-Goal）。
- 项目分组成员由租户管理员在管理端手工维护，不与 IM/SSO 组织自动同步（YAGNI，需要时后续）。
- admin-api 与 chat-api 两份 `quota_policy.py` 保持行为同步修改（现状即为同名副本，本特性不打破该格局）。

## 跨特性关系（被依赖方视角，双向声明）

- **与 001（gatekeeper-governance）**：001 配额层（`services/admin-api/app/governance/layers/quota.py` `default_credit_checker`）复用 020 配额体系读 `get_quota_summary`——本特性扩展该 summary 的层级语义，001 的消费点（`remainingPoints`）**自动获得三层限额而代码零改动**；本特性不改变门禁链末端位置与 fail-closed 语义，001 spec 中的配额层描述继续成立。
- **与 008（ops-dashboard）**：告警口径复用 008 异常枚举（`services/admin-api/app/api/dashboard_metrics.py:34` `ANOMALY_STATUSES`）与质量看板异常统计/下钻；008"不实现告警推送"的 Non-Goal 不变，本特性不新建推送通道。
- **与 020（platform-multi-tenancy）**：配额体系归属 020（org/user 两级 + decision 12 unlimited 默认 + FR-035~038 不限额口径）；本特性是 020 配额体系的**层级扩展**，集合结构、默认值语义、个人空间分支均延续 020，不回退。
- **与 035（成本归集补维，未来 spec）**：035 的成本归集与本特性共用 token 计量数据源（`token_usage_logs`）；两特性独立演进、互不阻塞——本特性产出"限额管控"，035 产出"花了多少钱"，消费方不同。

## Non-Goals

- 不新建告警推送通道（IM/邮件/webhook）——复用 008 展示口径 + 审计落点。
- 不修改 001 门禁层代码与门禁链结构（只扩展其数据源）。
- 不做部门子树自动聚合限额（团队 = 部门节点直接成员；子树聚合留待后续需求）。
- 不做配额购买/计费/充值/透支（仅用量限额）。
- 不做团队/项目级的用户二次分配（`user_quota_overrides` 仍只作用于 user 层）。
- 不做跨租户团队/项目共享，不做个人空间的团队/项目层。
- 不改 `user_quota_policies` 集合名、不做存量数据迁移。
