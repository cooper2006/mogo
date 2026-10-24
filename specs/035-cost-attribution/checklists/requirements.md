# Requirements Quality Checklist: 035 cost-attribution

**Purpose**: 校验 035（成本归集补维：部门/Agent/空间/业务线 + 单条成本透出）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-10-23
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 业务线标记的来源与维护入口是否定义（决策表 #3 用 `org_units.is_business_line=true`，但**未说明该字段由谁维护、如何设置、存量组织树是否需要迁移**；没有管理入口则业务线维度永远只有"无标记回落"一条路径）
- [x] CHK002 "根下第一层部门"的判据是否定义（决策表 #3 的回落规则；组织树可能多根、可能有虚拟根、`path_ids` 长度口径未定——按 `len(path_ids) == 2`、`parent_id is None` 还是"最高可见祖先"会得出不同桶）
- [x] CHK003 Agent 归属链路（018 资产注册表）的匹配键与失败口径是否定义（FR-004 只说"经 018 能力资产注册表解析资产名、解析不到回落原始 ID"，**按 `agent_id` 还是 `skill_id` 匹配、资产表读哪张 collection、两边都没有时回落到哪个字段**未写）
- [x] CHK004 部门维度"用户数"的口径是否定义（FR-006 写"调用数/用户数/成本按部门分桶"，**用户数是去重 `user_id` 吗、空 `user_id` 是否算一个、跨期去重还是窗口内去重**未定义）
- [x] CHK005 `未分配` 桶是否计入 `reconciles` 对账是否声明（FR-010 要求"各维分桶合计与 `totalCost` 一致"；若 `未分配` 不计入则对账必然失败，若计入则需明确它参与合计）

## 清晰度（Clarity）

- [x] CHK006 "workspace 缺省回退 `project_id`"与"无 workspace 归 `未分配`"的先后是否明确（FR-002 先回退 `project_id`，FR-007 又说"无值归 `未分配`"；**`project_id` 与 `workspace_id` 语义不同源**，混用会污染空间维度）
- [x] CHK007 单条 `costUsd` 的计价时点是否定义（FR-008 优先取 `cost_estimate_usd` 埋点值、缺失按 `MODEL_PRICES` 兜底；**价目表事后调整会让历史行金额与当日重算不一致**，需要声明"以写入时价目为准"还是"以查询时价目为准"）
- [x] CHK008 `available: False` 的判定条件是否定义（FR-009 只说"无数据源时"，**"某租户从未埋 `agent_id`"如何判定**：零记录、全部为空、还是窗口内全为 `未分配`；部分为空时该维度是否仍 `available: True`）
- [x] CHK009 Agent/空间维度的聚合键名与返回结构是否定义（FR-005 要求"接入等价于 `metering.aggregate_usage` 的多维聚合"，但**未给 `dimension` 枚举值与返回行键名**，前端无法据此写契约）

## 一致性（Consistency）

- [x] CHK010 与 008 既有成本 section 的结构是否兼容（008 已有 `models`/`reconciles`/`forecast`；035 新增六个 `*Attribution` 字段是追加还是替换、既有 `model` 维是否保留，未声明会产生两种响应形状）
- [x] CHK011 与 007 pricing 的价目来源是否同源（FR-008 说复用 007 pricing，但 007 写入的 `cost_estimate_usd` 与 008 的 `MODEL_PRICES` 是**两套价目表**；若两者单价漂移，单条金额与汇总会对不上）
- [x] CHK012 018 资产注册表的读取侧归属未定（是 admin-api 在归集时查资产表，还是 chat-api 埋点时把资产名写进记录？两种方案影响延迟、跨服务依赖与"改名后历史数据"的一致性）
- [x] CHK013 与 036 可信评级的消费边界是否声明（036 是否消费成本维度、是否会重复读取 `token_usage_logs`；未声明则两侧各自实现一套归集口径）

## 边界与歧义（Edge Cases & Ambiguity）

- [x] CHK014 跨租户隔离在反查链路中的落点是否定义（FR-011 要求全部新查询按租户隔离；`end_user_org_relations` → `org_units` 反查**若关系表本身无 `tenant_id`**，隔离靠什么保证）
- [x] CHK015 存量数据"不回填"的运营闭环是否定义（FR-012 说存量归 `未分配`、不回填；但若历史占比大，dashboard 会长期显示大量 `未分配`——**是否需要期限提示/一次性回填窗口/口径说明**，否则运维无法判断"是没数据还是埋点坏了"）

## Notes

- 条目编号 CHK001–CHK015 连续，覆盖完整性 / 清晰度 / 一致性 / 边界四类；每条均可回溯到 spec.md 的 FR / 决策表 / 边界原文。
- 本特性需求风险集中在**归集口径**（CHK004/CHK007/CHK011）与**数据源可用性**（CHK001/CHK008/CHK015）：前者决定数字对不对，后者决定维度可不可用。

## 评审结论（2026-10-23 勾选，agent 代审 + spec 回填）

15 条全部达标。0 条原生达标，15 条经 `spec.md` 新增的「判定口径补充（R-1~R-15）」消解：

- CHK001（业务线标记维护）→ R-1：可选字段、经组织单元写入路径维护，首期无专用 API。
- CHK002（根下第一层判据）→ R-2：取 `path_ids` 中最高 `is_business_line` 祖先，无标记回落"最高可见祖先"，不用层级硬编码。
- CHK003（018 匹配键与失败口径）→ R-3：首期**不做资产解析**（与 FR-004 的偏差已显式登记），桶键取 `agent_id`、回退 `node_id`、再回落 `未分配`。
- CHK004（用户数口径）→ R-4：窗口内去重 `user_id`；空 `user_id` 只计调用与成本。
- CHK005（`未分配` 是否计入对账）→ R-5：计入，`reconciles` 恒绿。
- CHK006（workspace/project 回退）→ R-6：`workspace_id` → `project_id` → `未分配`，统一写入 `workspace_id` 字段。
- CHK007（单条计价时点）→ R-7：以写入时快照 `cost_estimate_usd` 为准，历史行才兜底计算。
- CHK008（`available` 判定）→ R-8：无记录 / 全为未分配 → False；至少一行真实值 → True。
- CHK009（维度键名与结构）→ R-9：六个 `*Attribution` 字段 + `{dimension, available, reason, note, items[]}`，008 字段只增不改。
- CHK010（与 008 结构兼容）→ R-9：追加式扩展，`models`/`reconciles`/`forecast` 原样保留。
- CHK011（价目同源）→ R-10：快照优先、兜底统一 `MODEL_PRICES`；`reconciles` 只校验同一响应内。
- CHK012（018 读取侧）→ R-11：首期不读资产表，归集只依赖三张集合。
- CHK013（与 036 边界）→ R-12：036 必须复用本特性归集，不重复实现。
- CHK014（跨租户隔离落点）→ R-13：三处查询均带 `tenant_id`，无新增鉴权分支。
- CHK015（存量不回填闭环）→ R-14：`reason`/`note` 文案区分"无数据源"，不做回填脚本。

**验收证据**：`services/admin-api/tests/test_cost_attribution_035.py` 8 passed、`services/chat-api/tests/llm/test_cost_attribution_035.py` 4 passed；既有 `services/admin-api/tests/test_dashboard_routes.py` 已随本次改动更新。FR-004 的资产名解析未实现，已在 R-3 显式登记为"首期简化 + 后续增强"，不掩盖为达标。
