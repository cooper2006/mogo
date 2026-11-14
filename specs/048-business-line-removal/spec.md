# Feature Specification: 业务线维度删除

**Feature Branch**: `048-business-line-removal`

**Created**: 2026-10-31

**Status**: Draft

**Input**: `specs/035-cost-attribution/review-2026-10-30-dimension-source-audit.md` §4（已取消的维度：业务线）与 §4.3（删除清单）。用户口径：「业务线概念我建议取消」。

> **性质**：**纯删除**。不改任何能力，只删掉一个从未有过数据源、且会产出**假数据**的维度。文档侧（035 `spec.md` / `tasks.md` / `checklists`）已于 2026-10-30 改完，本特性只负责让代码跟上文档。

## 背景（为什么是删除而不是补数据源）

035 原本要补四个维度（部门/Agent/空间/业务线），核查后发现业务线**根本不存在**：

- `is_business_line` 全仓**只有读方，没有写方**：`dashboard.py:753/838` 在读，但组织单元的写入路径（`column_map.py:387-399` 的 `org_units` 映射、`directory.py:155-163` 的 payload、`directory_repository.ensure_root_department`）都不接受这个字段。除 035 自己的测试外，没有任何地方会把它写成 `true`。
- 更糟的是**回落实现必然造假**：`_resolve_business_line`（`dashboard.py:739-763`）在找不到标记时"回落最高可见祖先"，而每个租户的组织树根节点由 `ensure_root_department` 自动创建——于是每个租户都得到**单桶「企业总部」且 `available = True`**。

这不是"缺数据"，是"输出一条看起来很真的假分桶"。008 的诚实占位（`available=false` + reason）至少不会骗人；这里的单桶会让运营以为"业务线就一个，大家都归到总部"，从而做出错误判断。**假数据比空数据更有害**，所以取消。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 驾驶舱不再出现假的业务线分桶 (Priority: P1)

运营打开驾驶舱成本段，看到的是租户/用户/部门/Agent/项目五段真实分桶，不再有一个恒等于"企业总部"的业务线单桶。

**Why this priority**: 这是唯一对用户可见的变化，也是删除的唯一动机。它同时降低了误解成本——少一栏假数据，就少一次错误归因。

**Independent Test**: 打开驾驶舱成本 tab，断言页面无「业务线」卡片；`/overview` 响应中不含 `businessLineAttribution` 键；分桶合计与 `totalCost` 仍对账（`reconciles` 绿）。

**Acceptance Scenarios**:

1. **Given** 任意租户，**When** 打开驾驶舱成本段，**Then** 只出现五段（租户/用户/部门/Agent/项目），无业务线。
2. **Given** 任意租户，**When** 请求 `/overview`，**Then** 响应中**没有** `businessLineAttribution` 字段（不是空对象，是不存在）。
3. **Given** 删除后，**When** 校验对账，**Then** 剩余五段的分桶合计仍与 `totalCost` 一致（`reconciles` 绿）——删一个维度不应影响其他维度的加总。

---

### User Story 2 - 删除不留残骸 (Priority: P2)

代码、前端、测试、文档四处一致：没有半删状态（后端删了前端还在读、或测试还在断言旧字段）。

**Why this priority**: 半删状态比不删更危险——前端读 `undefined` 会静默渲染空卡片，测试断言旧字段会让后来人以为功能还在。但它不影响用户可见结果，所以排 P2。

**Independent Test**: 全仓 `grep -rn "is_business_line\|businessLine" services/ apps/` 零命中（文档中的历史记录除外）；成本相关测试全绿；前端 `vue-tsc` 0 错误。

**Acceptance Scenarios**:

1. **Given** 删除完成，**When** 全仓检索 `businessLine` / `is_business_line`，**Then** 仅文档的历史记录章节命中（`review-...md` §4 与 035 `spec.md` 的作废说明），代码零命中。
2. **Given** 删除完成，**When** 运行成本归集测试，**Then** 全绿（原断言业务线的用例已随之删除或改判）。
3. **Given** 前端代码，**When** 检索「业务线」，**Then** 零命中（维度标签、类型定义、来源数组均已清理）。

---

### Edge Cases

- **前后端不同批发布**：后端先删字段 → 旧前端读 `undefined` 会渲染空卡片（不崩，但难看）；前端先删 → 新前端忽略多余字段（安全）。**因此发布顺序为"前端先、后端后"**，或同批。
- **外部消费方**：核查确认无第三方消费 `businessLineAttribution`（仅 admin-web 的 `DashboardPage.vue`），无兼容包袱。
- **历史数据**：`token_usage_logs` 从来没有 `is_business_line` 字段，**不需要数据迁移**；删除纯属代码层。
- **未来想重新引入业务线**：不得复用 `is_business_line` 这个名字（035 `spec.md` R-1/R-2 已声明作废）；若真要做，必须先定义写入路径与维护入口，再新增维度。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `dashboard.py` MUST 删除 `_resolve_business_line()` 整个函数（`:739-763`）。
- **FR-002**: `_resolve_org_attribution()` MUST 删除 `business_line_map` 相关分支，**保留部门归集部分不变**（`:765-812`）。
- **FR-003**: `_attribution_dimensions()` MUST 不再构造业务线段，响应 MUST NOT 含 `businessLineAttribution` 键（`:828-880` 的返回字典）。
- **FR-004**: `DashboardPage.vue` MUST 删除维度标签 `business_line: '业务线'`（`:748`）、来源数组中的 `['business_line', section.businessLineAttribution]`（`:759`）、类型定义 `businessLineAttribution`（`:421`）。
- **FR-005**: 测试 MUST 同步删除业务线相关断言与用例（`tests/test_cost_attribution_035.py:158/190-191/202-215`），其余五段断言 MUST 保留并通过。
- **FR-006**: 系统 MUST NOT 引入 `is_business_line` 字段（不补写入路径、不建维护入口）；MUST NOT 保留"待补数据源"的注释占位。
- **FR-007**: 035 文档中 §4.3 的"代码未落地"标记 MUST 在代码删除完成后更新为"已完成"，并保留删除记录（不删文档历史）。

### Key Entities

本特性不涉及实体变更。删除的字段 `businessLineAttribution` 属 008 之后 035 追加的响应字段，非既有契约；`is_business_line` 从未存在于任何集合的写入路径。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 驾驶舱成本段维度数 = **5**（租户 / 用户 / 部门 / Agent / 项目）。
- **SC-002**: `/overview` 响应中 `businessLineAttribution` 键**不存在**（`"businessLineAttribution" in resp` 为 False）。
- **SC-003**: 全仓 `grep -rn "is_business_line\|businessLine" services/ apps/` = **0 命中**。
- **SC-004**: 成本归集相关测试全绿；`reconciles` 在对账用例中为 `True`。
- **SC-005**: 前端 `grep -rn "业务线" apps/admin-web/src` = 0 命中；`vue-tsc --noEmit` 0 错误。

## Assumptions

- 无外部消费方依赖 `businessLineAttribution`（已核查：仅 admin-web 一处）。
- 无需数据迁移（该字段从未落库）。
- 前端与后端可在同一发布窗口内上线；若必须分批，前端先行。

## Non-Goals

- 不做"业务线"的替代设计（不新建 `business_unit`、不做层级标签体系）。
- 不改动其余五个维度的口径与命名（「空间」→「项目」由 046 负责，「企业」→「租户」已完成）。
- 不清理 035 文档中的历史记录（保留"当初为何判断未实现/为何取消"的证据链）。
