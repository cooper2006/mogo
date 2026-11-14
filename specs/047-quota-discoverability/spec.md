# Feature Specification: 配额可发现性与跨服务口径

**Feature Branch**: `047-quota-discoverability`

**Created**: 2026-10-31

**Status**: Draft

**Input**: `specs/035-cost-attribution/review-2026-10-30-dimension-source-audit.md` §7.2（批次 A/B/C）与 §6 问题清单 P0-1/P0-2/P1-1。用户口径：「项目可以考虑有两个地方作为入口……但是都有问题」；「没有团队概念，只有项目概念，建议独立菜单」。

> **本特性不改配额引擎**。042 的三层取小、`limitingScope`、告警落库都已实现并可用；问题在于**人找不到它、深链指错地方、告警看不见**，以及两份 `quota_policy.py` 副本存在口径漂移。本特性只修"入口、指向、展示、一致性"。
>
> **B0 不在本特性**：`points_unlimited` 默认值缺陷（chat-api 缺 `, True`）已按用户决定并入 042 `tasks.md` 的 T024，本特性不重复登记。

## 背景（为什么"实现了却像没做"）

042 代码已落地（`tasks.md` 23/24），但站在管理员视角几乎不可用：

1. **入口太深**：项目额度藏在「流量分配」页筛选栏按钮 → 弹窗 → 第二个 tab，三次点击；菜单名"流量分配"与"项目"无语义关联。
2. **深链指错**：`?open=quota` 实际打开的是**租户额度**（`TrafficAllocationsPage.vue:598-604` 的 `consumeOpenQuotaQuery()` 调 `openSettings()` 而非 `openScopes()`）。`ModelsPage.vue:27/766` 的"去配置"全都指到这里。
3. **告警看不见**：后端 `/overview` 已返回 `quotaAnomalies`（`dashboard.py:967`），admin-web 全仓**零引用**，驾驶舱只渲染 `qualityAnomalies`。
4. **口径漂移**：两份 `quota_policy.py` 副本已不同（chat-api 12431B / admin-api 11152B，且 tz 一处 naive 一处 aware），无一致性测试锁死。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 从侧边栏直接进「项目管理」 (Priority: P1)

管理员登录 admin-web，侧边栏直接看到「项目管理」，点进去是项目列表（只读，项目由员工在自己机器上创建）、每个项目的用量与成本、以及项目层额度配置。不再需要先想到"流量分配"这个词。

**Why this priority**: 入口是所有其它工作的前提——深链、空态、告警卡片最终都指向这个页面。没有它，后面几项都无处可落。

**Independent Test**: 侧边栏可见「项目管理」→ 单击进入 → 页面同时展示项目列表、用量/成本、额度配置三块；页面上**没有**"新建项目"按钮、**没有**"团队"字样。

**Acceptance Scenarios**:

1. **Given** 管理员已登录，**When** 展开侧边栏，**Then** 出现独立菜单「项目管理」，与「流量分配」并列（不是其子项）。
2. **Given** 进入项目管理页，**When** 查看列表，**Then** 项目来自 `projects` 集合（046 改名后），只读；无"新建/编辑成员"入口。
3. **Given** 某项目已配额度，**When** 查看该项目行，**Then** 显示额度、周期、本期已用、剩余；未配置显示「未设置额度」而非 `0`。
4. **Given** 项目被归档（046 US2），**When** 查看列表，**Then** 归档项目折叠进「已归档」分组，不占默认视图。

---

### User Story 2 - 告警点「去配置」落到正确的视图 (Priority: P1)

管理员在驾驶舱或模型中心看到一条配额告警，点"去配置"，直接落在**对应那一层**的配置视图：项目告警落到项目配额、租户告警落到租户额度。

**Why this priority**: 深链指错比没有深链更糟——用户以为点了会到项目额度，结果看到租户额度，会直接判断"这个功能没做"。

**Independent Test**: 从项目层告警点"去配置"→ 落在项目管理页的项目配额视图；从租户层告警点"去配置"→ 落在租户额度弹窗；两次都不需要用户再找。

**Acceptance Scenarios**:

1. **Given** 一条 `scope_type = project` 的告警，**When** 点"去配置"，**Then** 落在项目配额视图（`?open=quota` 指向项目）。
2. **Given** 一条 `scope_type = org` 的告警，**When** 点"去配置"，**Then** 落在租户额度（`?open=tenant`）。
3. **Given** 深链参数非法或缺失，**When** 页面加载，**Then** 落到默认视图并提示，不白屏、不静默跳错。
4. **Given** 用户无配额管理权限，**When** 访问深链，**Then** 明确提示无权限（不展示空页面）。

---

### User Story 3 - 驾驶舱看见配额异常 (Priority: P2)

驾驶舱质量看板旁边新增「配额异常」卡片：按层（部门/项目/租户/用户）分组列出超限与接近阈值的条目，可下钻到具体策略。没有事件时显示原因说明，而不是一排 0。

**Why this priority**: 042 后端已经算好了告警，只是没展示。这是"投入最小、感知提升最大"的一项，但依赖 US1 的落点（下钻要跳到对应配置）。

**Independent Test**: 构造一条 `exceeded` 事件 → 驾驶舱出现配额异常卡片且按 scope 分组；清空事件后卡片显示 `reason`（如"本期无配额告警"），不显示 `0`。

**Acceptance Scenarios**:

1. **Given** 存在配额告警事件，**When** 打开驾驶舱，**Then** 卡片按 `scope_type` 分组展示，含层名、对象名、时间、比例。
2. **Given** 无告警事件，**When** 打开驾驶舱，**Then** 显示 `reason` 文案，**不渲染 0 条**（延续 008 诚实占位纪律）。
3. **Given** 点击某条告警，**When** 跳转，**Then** 落在对应层的配置视图（复用 US2 的深链）。

---

### User Story 4 - 空态与旧入口都能走通 (Priority: P2)

租户还没有任何项目时，页面告诉他"项目在 user-web 里选本地目录创建"并给链接；「流量分配」页上那个旧的「团队 / 项目额度」按钮改成跳转新页面，租户额度弹窗保留。

**Why this priority**: 空态不引导，用户只会认为"没有数据"；旧入口不改，两套入口长期并存会持续制造困惑。都是收尾工作，所以排 P2。

**Independent Test**: 空租户进项目管理页 → 看到引导文案 + 可点击跳转；进流量分配页 → 点旧按钮跳到项目管理页，弹窗里只剩租户额度。

**Acceptance Scenarios**:

1. **Given** 租户零项目，**When** 打开项目管理页，**Then** 显示引导文案与跳转链接（指向 user-web）。
2. **Given** 管理员在「流量分配」页，**When** 点击原「团队 / 项目额度」按钮，**Then** 跳转到项目管理页；弹窗中不再有项目 tab。
3. **Given** 同一页面，**When** 打开额度弹窗，**Then** 仍可配置**租户额度**（原"企业额度"，046/035 已改称租户）。

---

### User Story 5 - 两份副本口径一致 (Priority: P2)

同一份策略数据，在 chat-api 与 admin-api 两侧算出的配额摘要逐字段相同；时区处理语义统一，不再一处 naive 一处 aware。

**Why this priority**: 现在没有一致性测试，两份副本已开始漂移。它不产生新功能，但决定了"用户看到的剩余"和"门禁判定的剩余"是不是同一个数——不一致就是生产事故。

**Independent Test**: 同一 fixture（四层策略 + 固定用量）分别调两侧 `get_quota_summary`，JSON 序列化后逐字段相等；连续跑两次结果稳定（无 tz 抖动）。

**Acceptance Scenarios**:

1. **Given** 同一 fixture，**When** 两侧各算一次，**Then** 除时间戳格式外逐字段相等。
2. **Given** 跨日/跨月边界时刻，**When** 计算周期窗口，**Then** 两侧结果一致（tz 语义已统一）。
3. **Given** 一致性测试先跑，**When** 存在差异，**Then** 测试失败并打印差异字段（先红后绿）。

---

### Edge Cases

- **项目层与租户层告警同时存在**：卡片按层分组并列展示，不合并、不互相覆盖。
- **`quotaAnomalies.available = false`**：显示 `reason`（后端已给），前端不得用 0 兜底。
- **深链参数与用户权限不匹配**：提示无权限，不静默降级到有权限的视图（否则用户会以为看到的就是全部）。
- **旧入口被收藏为书签**：`/organizations/traffic?open=quota` 必须仍能打开（落租户额度或跳新页），不能 404。
- **归档项目仍有告警**：照常展示（告警是历史事实），但下钻到配置时提示项目已归档。
- **两侧副本一方升级一方未升级**：一致性测试是 CI 门禁，不同步就红——这是刻意设计，不允许"先合一侧"。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: admin-web MUST 新增独立菜单「项目管理」（路由 `/projects`），含项目列表（只读）、按项目的用量/成本、项目层额度配置；MUST NOT 提供"新建项目"或"编辑成员"入口（项目由员工在自己机器上创建）。
- **FR-002**: `?open=quota` MUST 落在项目配额视图；新增 `?open=tenant` MUST 落在租户额度；模型中心/驾驶舱的"去配置" MUST 按告警的 `scope_type` 分流。
- **FR-003**: 零项目时 MUST 显示引导文案与跳转链接（指向 user-web 的项目创建入口），MUST NOT 显示空表格。
- **FR-004**: 驾驶舱 MUST 新增「配额异常」卡片，消费 `/overview` 的 `quotaAnomalies`；`available = false` 时 MUST 显示 `reason`，MUST NOT 渲染 0 条。
- **FR-005**: 「流量分配」页的原「团队 / 项目额度」按钮 MUST 改为跳转项目管理页；租户额度弹窗 MUST 保留可用。
- **FR-006**: 对外文案 MUST 统一为「部门」（`TrafficAllocationsPage.vue` 按钮与 tab 名、拒绝消息、相关提示）；**机器标识符 MUST 保持不变**（`scope_type = "team"`、`teamRemainingPoints`、`setup_team`、`/traffic-allocations/teams/...`）。
- **FR-007**: 系统 MUST 提供跨服务一致性测试：同一 fixture 下 chat-api 与 admin-api 的 `get_quota_summary` 输出逐字段相等（差异时打印字段名）。
- **FR-008**: 两份 `quota_policy.py` 的时间语义 MUST 统一（全 aware 或全 naive，二选一），并在文件头 MUST 注明选择与理由。
- **FR-009**: 042 `spec.md` MUST 补「实现落点索引」，列出各 FR 的代码落点与提交号（`93428a82` 含 042 实现，提交信息误标为 032-033-034）。
- **FR-010**: 042 与本特性 MUST 与 035/046 建立双向声明：项目概念以 046 为准，042 不再维护独立的"项目分组"实体。

### Key Entities

- **QuotaAlertEvent**（既有，042 R-11）：`{tenant_id, scope_type, scope_id, kind, ratio, layer_name, period_start, at, alert_key}`；本特性只消费，不改结构。
- **QuotaAnomalies 视图**（既有，后端）：`{available, reason, byScope, items[]}`；本特性负责前端呈现。
- **Project**（046 定义）：项目列表数据源；本特性只读。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 从侧边栏进入项目配额的点击次数 = **1**（现状 3）。
- **SC-002**: 从任意告警点"去配置"，落在正确层视图的比例 = **100%**（现状 0%，全部落租户额度）。
- **SC-003**: 驾驶舱可见配额异常；`available = false` 时不出现 `0` 值渲染。
- **SC-004**: `apps/admin-web/src` 与 `services/` 的**对外文案**中"团队"零残留（grep 断言，标识符白名单见 042 `spec.md` 顶部对照表）。
- **SC-005**: 跨服务一致性测试存在且通过；人为改动一侧口径时测试必须失败（反证测试有效）。
- **SC-006**: 既有配额测试（`test_quota_three_level.py` / `test_quota_unlimited.py` / `test_setup_quota.py` / `test_governance_us4_us5.py`）全绿，零回归。

## Assumptions

- 项目由员工在 user-web 创建，管理端**不能**替员工选目录——因此项目管理页天然只读。
- 部门维度归组织管理（`/organizations`），配额页不再做部门配置 tab；部门层配额能力保留（`scope_type = "team"` 不改）。
- 042 的告警后端已可用（`quota_alert_events` + `summarize_quota_alerts`），本特性不重做。
- 一致性测试用同内容 fixture 文件，不做跨库真实数据比对。

## Non-Goals

- 不新建告警推送通道（IM/邮件/webhook）——008 Non-Goal 不变。
- 不把"按项目归属"做成配额约束（D5：配额不是关键项，默认不限额）。
- 不抽 `quota_policy` 公共包（两份副本分属两个服务，用一致性测试锁死即可）。
- 不改 `ANOMALY_STATUSES`（042 R-12 已论证 quota 告警是独立事件，不进 `token_usage_logs.status` 过滤）。
- 不改 `scope_type` 枚举值与任何既有字段名（改枚举要迁数据，收益为零）。
