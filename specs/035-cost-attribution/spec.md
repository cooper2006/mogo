# Feature Specification: 成本归集补维（部门/Agent/空间/业务线 + 单条成本透出）

**Feature Branch**: `035-cost-attribution`

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description: "008 驾驶舱成本维当前只按 model_name 分组，部门/Agent 归集是诚实占位（departmentAttribution.available=False），空间/业务线维度不存在；多维聚合库函数 attribute_cost / aggregate_usage 已写好但零生产调用方。补部门/Agent/空间/业务线四个归集维度，把库函数接入 dashboard 生产调用，单次调用下钻透出单条成本金额。"

> **设计来源**：本规约落地《MOGO × 企业 Agent OS 整合方案》§4.4「成本归集补维」（文章六维归集：企业/空间/应用/模型/业务线/用户）。
>
> **性质说明**：这是**补数据源 + 接线的补维特性**（全新特性，代码尚未开工，任务清单全部未勾选）——008 的诚实占位纪律（无数据源时显式标注而非填零）是本特性的继承基线；两个多维聚合库函数（`dashboard_metrics.attribute_cost`、`metering.aggregate_usage`）已写好但零生产调用方，本特性把它们接入 `dashboard.py` 生产调用。

## 定位（一句话）

给 008 驾驶舱的成本维补齐四个归集维度（部门/Agent/空间/业务线），使整合方案对照的「六维归集」（企业/空间/应用/模型/业务线/用户）完整——核心动作是**补数据源**（`TokenUsageRecord` 增加 `agent_id` 及归属链路、部门经 `end_user_org_relations` 反查）与**接库函数**（`attribute_cost`/`aggregate_usage` 接入 `dashboard.py::_cost_section()` 替换诚实占位），同时让单次调用下钻透出单条成本金额，无数据源的维度延续 008 诚实占位纪律显式标注。

## 已定决策（2026-10-23，spec 撰写时拍板）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | `agent_id` 埋点位置与归属链路 | `TokenUsageRecord` 新增 `agent_id` 字段；埋点在 `instrumented_client.py::_submit_record`——从 `output_spec`（含 `get_request_context()` 动态上下文，`factory.py:72-76` 已合并）读 `agent_id`，与现有 `node_id`/`tenant_id`/`user_id` 同机制，零新管道。归属链路：**Agent → Skill → 资产**——记录同时携带 `skill_id`（有则填），Agent 维度聚合时经 018 能力资产注册表把 agent/skill 解析到资产名（无资产登记时回落 agent 原始 ID） | `token_usage/models.py` + `instrumented_client.py` 记录构造处 |
| 2 | 空间维度数据来源 | **空间 = `workspace_id`**（与 017 记忆 scope、021 `mogo://` 的 workspace 语义同源）：从 `output_spec` 读 `workspace_id`（缺省回退 `project_id`，与 `context_engine/project_memory.py:154` 的既有回退口径一致）写入记录字段；无 workspace 的调用归 `未分配`。**不新建空间表**——复用请求上下文里已有的 workspace 标识 | `token_usage/models.py` 新字段 + `output_spec` 读取 |
| 3 | 业务线维度数据来源 | **业务线 = 部门树扩展**：用户部门（`end_user_org_relations` → `org_units`）沿 `path_ids` 祖先链向上，取约定标记的业务线节点（首期口径：`org_units` 中 `is_business_line=true` 的最高级祖先；无标记时取租户根下第一层部门）。部门维度本身（008 FR-2 既有承诺）经 `end_user_org_relations` 反查——**仅计数**（有多少调用/用户归属该部门），不伪造分摊算法 | admin-api `dashboard.py::_cost_section` 新增反查逻辑 |
| 4 | 单条成本透出的计价口径 | **复用 007 pricing**：`token_usage_logs.cost_estimate_usd` 已由 `instrumented_client.py:209` 写入（007 T019，token × 008 `MODEL_PRICES` 单价）；下钻透出优先取该字段，缺失时（历史行）按 `analytics.py:325-332` 既有 `MODEL_PRICES` + `DEFAULT_PRICE` 兜底计算，保证单条金额与汇总对账一致 | `analytics.py` 详情/列表 + `dashboard.py` |
| 5 | 无数据源维度的占位规则 | **延续 008 诚实占位纪律**：某维度无数据源（如某租户从未埋 `agent_id`）时，该维度返回 `available: False` + `reason`（说明缺什么、谁补齐），**不填零、不伪造数值**；有数据源的维度正常聚合。`reconciles` 对账自检保持绿（六维分组各自与总量对账，浮点容差沿用 `COST_TOLERANCE`） | `dashboard.py::_cost_section` 各 dimension 段 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - TokenUsageRecord 补 agent_id 与归属链路埋点（Priority: P1）

chat-api 的 LLM 调用记录（`token_usage_logs`）新增 `agent_id`（及 `skill_id`、`workspace_id`）字段：Agent 运行时把当前 Agent/Skill/workspace 标识经 `output_spec`/请求上下文传入，`InstrumentedLLMClient._submit_record` 写入记录。此后每次 LLM 调用都知道"是谁花的钱"。

**Why this priority**: 这是四个新维度的**唯一数据源底座**——`dashboard.py:674` 的诚实占位原文即"agent_id 无数据源（TokenUsageRecord 缺字段）"。不补字段，dashboard 侧无从聚合；掩码/下钻都无从谈起。优先于所有消费侧改造。

**Independent Test**: 用 fake output_spec/请求上下文构造一次 `InstrumentedLLMClient.ainvoke`（fake 内层 client），断言落库记录含 `agent_id="agent-a"`、`skill_id="skill-b"`、`workspace_id="ws-1"`；不传时字段为空串且不影响记录落库（向后兼容）。

**Acceptance Scenarios**:

1. **Given** 请求上下文含 `agent_id=agent-a`，**When** 一次 LLM 调用完成落库，**Then** `token_usage_logs` 该行 `agent_id == "agent-a"`。
2. **Given** Agent 经 Skill 执行且 output_spec 携带 `skill_id`，**When** 落库，**Then** `skill_id` 非空，且可经 018 资产注册表解析到资产名（解析不到时回落原始 ID，不报错）。
3. **Given** 历史调用方不传 agent_id/skill_id/workspace_id，**When** 落库，**Then** 三字段为空串，记录结构与字段总数不变（既有消费方零影响）。
4. **Given** 一次 DAG 编排内多节点调用（`node_id` 不同、`agent_id` 相同），**When** 落库，**Then** 各行 `agent_id` 一致、`node_id` 各自独立——Agent 维度能把多节点成本归并到一个 Agent。

---

### User Story 2 - 驾驶舱成本 section 六维归集（Priority: P1）

admin-web 运营驾驶舱成本 tab 在原有模型/用户/企业维度之外，新增部门、Agent、空间、业务线四个分组；`_cost_section()` 接入 `attribute_cost`（admin-api 库函数）与 `aggregate_usage`（chat-api 库函数，admin-api 侧等价聚合或经共享逻辑）做多维分组；每个维度标注 `available` 与 `reason`，无数据源不填零。

**Why this priority**: 这是整合方案 §4.4 的**正文目标**（六维归集完整）与 008 FR-2 的既有承诺（"按部门/智能体分摊 → 可下钻"）的兑付——`dashboard.py:713-716` 的诚实占位从"待补齐"变为"已补齐"。与 US1 共同构成特性 MVP。

**Independent Test**: fake DB 预置含 `agent_id`/`user_id`（关联 `end_user_org_relations`→`org_units`）/`workspace_id` 的多行 usage；调 `dashboard._cost_section(db, tenant)`，断言：`departmentAttribution.available == True` 且含部门桶、`agentAttribution` 含 agent 桶、`spaceAttribution`/`businessLineAttribution` 口径正确；再构造无 agent_id 的数据，断言对应维度 `available == False` + reason 非空、且 `reconciles` 仍为 True。

**Acceptance Scenarios**:

1. **Given** 近 24h usage 行带 `agent_id`/`user_id`/`workspace_id` 且用户有部门关系，**When** 调 `/overview`，**Then** 成本 section 含 department/agent/space/businessLine 四个归集段，各段 `calls`/`tokens`/`cost` 分桶合计与 `totalCost` 对账一致（`reconciles` 绿）。
2. **Given** 某租户 usage 行全部无 `agent_id`，**When** 调 `/overview`，**Then** `agentAttribution.available == False` 且 `reason` 说明"TokenUsageRecord.agent_id 无数据"，其余维度正常。
3. **Given** 用户无部门关系（`end_user_org_relations` 无行），**When** 部门维度聚合，**Then** 该用户成本归 `未分配` 桶，不猜部门。
4. **Given** 部门树含业务线标记节点，**When** 业务线维度聚合，**Then** 沿 `path_ids` 归到标记祖先；无标记租户回落第一层部门并在 `reason` 注明回落口径。
5. **Given** 六维各自分组，**When** 逐维对账，**Then** 每维分桶成本合计 = `totalCost`（容差内）——分组不丢行、不重行。

---

### User Story 3 - 单次调用下钻含单条成本金额（Priority: P2）

analytics 的 token 用量下钻（`groupBy=user_request|session` 列表与 `GET /token-usage/{request_id}` 详情）透出单条成本金额：列表行新增 `costUsd`（取 `cost_estimate_usd`，缺失按定价兜底），详情返回增加 `costUsd`、`modelName`、token 分解等既有字段，使"某一次请求到底花了多少钱"可回答。

**Why this priority**: 这是文章"单次调用可下钻"要求的直接兑现，也是 008 FR-10（异常可下钻到请求）的成本侧补全。优先级 P2：它消费 US1 埋好的数据但不阻塞六维归集主体；先有维度汇总、再有单条下钻，符合由粗到细的交付顺序。

**Independent Test**: fake DB 预置带 `cost_estimate_usd=0.0123` 与不带（历史行）的两类 usage 行；调 `GET /analytics/token-usage?groupBy=user_request` 与 `GET /analytics/token-usage/{request_id}`，断言列表行与详情均含 `costUsd`（前者 0.0123、后者按 `MODEL_PRICES` 兜底计算值），且详情含 `modelName`。

**Acceptance Scenarios**:

1. **Given** 一行 `cost_estimate_usd=0.0123` 的 usage 记录，**When** 进入下钻列表/详情，**Then** `costUsd == 0.0123`（直接透出埋点值）。
2. **Given** 一行历史记录无 `cost_estimate_usd`，**When** 下钻，**Then** `costUsd` 按 `MODEL_PRICES`/`DEFAULT_PRICE` 兜底计算（口径与 `analytics.py:325-353` 汇总计算一致），不为 null、不为 0 冒充。
3. **Given** 单请求下钻（一个 user_request 多条 LLM 调用），**When** 查看，**Then** 每条调用各自带 `costUsd`，且列表行 `costUsd` 之和与该请求在成本 section 中的占比自洽。
4. **Given** 无权限的跨租户 request_id，**When** 请求详情，**Then** 403（沿用 `analytics.py:456-457` 既有租户隔离，不因新增字段放宽）。

---

### User Story 4 - 对账自检与诚实占位纪律回归（Priority: P2）

六维上线后，成本 section 的 `reconciles` 自检保持绿；空维度显式标注；既有 008 相关测试（`test_dashboard_routes.py::test_cost_section_is_wired_and_reconciles`、`test_dashboard_selfcheck.py`）与新测试共同守住"不伪造数值"纪律。

**Why this priority**: 008 的立身之本是"诚实看板"（`dashboard.py:673-676` 注释原文：deliberately not fabricated）。补维最容易翻车的就是"为了维度好看而填零/猜数"——本故事把纪律固化为测试与验收，优先于任何锦上添花。

**Independent Test**: 跑 admin-api 既有 dashboard 测试全绿 + 新增"空维度不伪造"用例（无 agent_id/无部门关系/无 workspace 三种空数据场景下，对应维度 available=False 且 reason 非空、reconciles=True、无 0 值桶冒充）。

**Acceptance Scenarios**:

1. **Given** 六维数据齐备，**When** 任一维分组，**Then** `reconciles` 为 True（分组合计 = 总量，容差内）。
2. **Given** 某维度完全无数据源，**When** 返回，**Then** 该段 `available: False` + `reason`，且不出现该维度的 0 值分桶列表（空列表 + 标注，而非伪造一行 0）。
3. **Given** 既有 `test_dashboard_routes.py:149-193` 的断言（含 `departmentAttribution.available is False` 的历史场景），**When** 数据源补齐后测试更新，**Then** 新断言覆盖"有数据源时 available=True"与"无数据源时 available=False"两种场景，纪律不丢。

---

### Edge Cases

- **历史数据无 agent_id**：`agent_id` 埋点上线前的存量 `token_usage_logs` 行无该字段。Agent 维度对这些行归 `未分配`（与 `attribute_cost` 既有 `未分配` 兜底一致，`dashboard_metrics.py:310`），不回填、不猜；维度 `reason` 注明"含埋点前历史数据"。
- **agent_id 与 node_id 的关系**：DAG 编排一次运行含多节点 LLM 调用（`node_id` 不同）。agent 维度按 `agent_id` 归并（多节点→一个 Agent 桶），`node_id` 维度保持既有语义（`aggregate_usage` 的 agent 分支已含 `node_id` 回落，`metering.py:59`）——两者不互相覆盖。
- **一用户多部门**：`end_user_org_relations` 理论上可多行。部门反查按主部门（首行/最新行）计，`reason` 注明口径；不把一次调用重复计入多个部门（防双计破坏对账）。
- **业务线标记缺失**：租户未在 `org_units` 打 `is_business_line` 标记时，业务线维度回落"根下第一层部门"并在 `reason` 注明回落口径；根下也无分层时该维度 `available=False`。
- **workspace_id 与 project_id 并存**：`output_spec` 可能两者都有（`project_memory.py:154` 的回退口径）。统一口径：`workspace_id` 优先，缺失取 `project_id`，写记录时归一到 `workspace_id` 字段。
- **成本字段精度**：`cost_estimate_usd` 为 float；分桶求和沿用 `round(..., 6)`（`dashboard_metrics.py:319`）与 `COST_TOLERANCE` 对账容差，六维各自对账而非跨维相加（不同维度的同一行成本在各维各出现一次是设计使然，不与总量混算）。
- **空租户**：无任何 usage 行时各维度空态（008 FR-9 既有纪律），`reconciles` 对空总量为 True，不报错。
- **单条成本与汇总的一致性**：下钻 `costUsd` 与 dashboard 汇总必须同源（都经 007 pricing / `MODEL_PRICES`），防止"汇总 1.2、下钻合计 1.5"的对账穿帮；汇总侧优先用埋点 `cost_estimate_usd`（与 `metering.py:78`、`dashboard_usage.py:55` 既有口径一致）。
- **跨租户读取**：所有新维度查询沿用 `tenant_match`/租户隔离（008 FR-7），部门反查带 tenant_id 条件（`analytics.py:120-123` 既有范式）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `TokenUsageRecord`（`services/chat-api/app/token_usage/models.py`）MUST 新增 `agent_id`、`skill_id`、`workspace_id` 三个字段（默认空串），既有字段与默认值不变。
- **FR-002**: 埋点 MUST 落在 `services/chat-api/app/llm/instrumented_client.py::_submit_record` 的记录构造处：从 `output_spec`（含 `get_request_context()` 合并，`factory.py:72-76`）读取 `agent_id`/`skill_id`/`workspace_id`（workspace 缺省回退 `project_id`），与既有 `tenant_id`/`user_id`/`node_id` 同机制写入。
- **FR-003**: Agent 运行时调用链 MUST 把当前 Agent/Skill 标识传入请求上下文或 output_spec（或复用既有 Agent 执行处已设置的上下文键）；不新增独立埋点管道。
- **FR-004**: Agent 维度聚合 MUST 支持归属链路解析：Agent/Skill 经 018 能力资产注册表解析资产名（解析不到回落原始 ID），`skill_id` 随记录携带供链路还原。
- **FR-005**: `dashboard.py::_cost_section()` MUST 接入 `dashboard_metrics.attribute_cost`（admin-api 库函数）做部门/业务线/空间归集，接入等价于 `metering.aggregate_usage` 的多维聚合做 Agent 归集（admin-api 侧按同口径实现或共享逻辑），替换现有仅按 `model_name` 的单一分组。
- **FR-006**: 部门维度 MUST 经 `end_user_org_relations` → `org_units` 反查（仅计数口径：调用数/用户数/成本按部门分桶），无部门关系归 `未分配`；反查带租户隔离。
- **FR-007**: 空间维度 MUST 按记录 `workspace_id` 分桶，无值归 `未分配`；业务线维度 MUST 沿 `org_units.path_ids` 归到约定标记祖先（`is_business_line` 最高级祖先，无标记回落根下第一层部门并在 reason 注明）。
- **FR-008**: analytics 下钻（`GET /analytics/token-usage` 列表行与 `GET /analytics/token-usage/{request_id}` 详情）MUST 透出单条成本 `costUsd`：优先 `cost_estimate_usd` 埋点值，缺失按既有 `MODEL_PRICES` + `DEFAULT_PRICE` 兜底计算（口径与 `analytics.py:325-353` 汇总计算一致）。
- **FR-009**: 无数据源的维度 MUST 显式返回 `available: False` + `reason`（说明缺什么数据源），MUST NOT 填零、MUST NOT 伪造分桶；有数据源的维度 MUST 正常聚合。
- **FR-010**: 成本 section 的 `reconciles` 对账自检 MUST 保持绿（各维分桶合计与 `totalCost` 一致，容差沿用 `COST_TOLERANCE`）；单条 `costUsd` 与汇总 MUST 同源同口径。
- **FR-011**: 全部新查询 MUST 按租户隔离（008 FR-7 口径），跨租户请求拒绝（403）。
- **FR-012**: 埋点字段缺失的存量数据 MUST 归 `未分配` 兜底，不阻塞聚合、不回填历史。

### Key Entities

- **TokenUsageRecord（扩展）**: `token_usage_logs` 行模型，新增 `agent_id`/`skill_id`/`workspace_id`；`cost_estimate_usd`（007 T019 已写入）是单条成本透出的主数据源。
- **成本归集维度（六维）**: 企业（`tenant_id`，既有）/ 用户（`user_id`，既有）/ 模型（`model_name`，既有）/ 部门（`end_user_org_relations` 反查，本特性接线）/ Agent（`agent_id` + 018 资产链路，本特性补数据源）/ 空间（`workspace_id`，本特性补数据源）；业务线为部门树扩展派生维。
- **attribute_cost**（复用，`dashboard_metrics.py:297-320`）: 任意维度成本归集库函数（`未分配` 兜底 + 按成本降序）——已写好零生产调用方，本特性接入。
- **aggregate_usage**（复用，`metering.py:39-83`）: provider/model/tenant/agent 四维聚合纯函数——已写好仅测试引用，本特性以等价口径接入 admin-api 侧 Agent 归集。
- **org_units / end_user_org_relations**（复用）: 部门树（`parent_id`/`path_ids`/`is_business_line` 标记）与用户部门关系，部门/业务线维的反查源。
- **诚实占位段**: `{available: bool, reason: str}` 维度元信息，008 既有纪律的载体（`dashboard.py:713-716` 原型）。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 六维均可分组聚合——成本 section 返回企业/用户/模型/部门/Agent/空间六维分桶（业务线作为部门树扩展维同场呈现），每维分桶合计与 `totalCost` 对账一致（`reconciles` 绿）。
- **SC-002**: 单次调用可下钻且含单条成本金额——下钻列表行与详情均含 `costUsd`（埋点值或定价兜底），且与汇总同源（汇总 1.2 时下钻合计 1.2，容差内）。
- **SC-003**: 对账自检保持绿——`reconciles` 在六维齐备/部分缺失/空租户三种场景下均为 True，既有 `test_dashboard_routes.py`/`test_dashboard_selfcheck.py` 相关用例全绿。
- **SC-004**: 空维度不伪造数值——无数据源维度 100% 返回 `available: False` + `reason`，响应中无该维度的 0 值分桶冒充（测试断言三种空场景）。
- **SC-005**: 埋点向后兼容——不传 `agent_id`/`skill_id`/`workspace_id` 的调用方记录结构与既有消费方零影响（既有 token_usage 相关测试全绿）。
- **SC-006**: 归集口径可解释——每个维度在 API 响应中携带口径说明（数据源字段/回退规则），运营查看时无需读代码即可理解"这个数怎么来的"。

## Assumptions

- 假设 008 的 dashboard 结构与诚实占位纪律是既定基线（已代码级核实：`dashboard.py:665-717` `_cost_section` + `departmentAttribution` 诚实声明；`test_dashboard_routes.py:149-193` 有对应断言），本特性在其上演进而非重建。
- 假设 `cost_estimate_usd` 已由 007 链路稳定写入（已核实：`instrumented_client.py:209`、`token_usage/models.py:36`），单条成本透出以它为主源、定价表兜底只为历史行。
- 假设 `attribute_cost`/`aggregate_usage` 两个库函数签名与语义稳定（已代码级核实，均有测试覆盖），接入不改变其 pure 函数契约。
- 假设 Agent 运行时（orchestration/dsh_runtime）能在 LLM 调用前后把 agent/skill 标识放入请求上下文——`get_request_context()` 机制（`infrastructure/request_context.py`）与 `factory.py:72-76` 的合并逻辑已就绪，Agent 执行处只需 merge 对应键（或 output_spec 已携带）。
- 假设 018 能力资产注册表可按 agent/skill ID 反查资产名（资产注册是 018 既有能力）；查不到时回落原始 ID 不报错。
- 假设 `org_units` 含 `path_ids` 祖先链（已核实：`ontology_permission.py:153` 使用该字段做组织含下级展开），业务线标记为首期约定字段（`is_business_line`），无标记租户走回落口径。

## 跨特性关系

- **与 008-ops-dashboard（直接扩展对象）**：008 的四维驾驶舱成本维（US2/FR-2/FR-6）是本特性的**受管基线**——`_cost_section()` 的既有结构（模型分组 + 对账 + 预测 + 诚实占位）原样保留，本特性只做"补维 + 替换占位 + 补下钻"。反向声明：008 的诚实占位纪律（无数据源显式标注）被本特性继承为验收项（FR-009/SC-004）；008 既有端点契约向后兼容扩展（新增字段与维度段，不改既有字段语义）。
- **与 007-llm-gateway-resilience（计量来源）**：007 的计量上报（`cost_estimate_usd`、`token_usage_logs` 写入、`resilience_events`）是本特性的数据源；本特性不改 007 写入链路，只新增记录字段的填充。反向声明：007 的 failover/降级字段已在记录中（008 FR-8 消费），本特性的新字段与其共存于同一记录，互不覆盖。
- **与 018-capability-asset-registration（归属链路）**：018 的资产注册表是 Agent→Skill→资产归属解析的查找源（FR-004）。反向声明：018 不感知本特性；若 018 后续调整资产 ID 体系，本特性的归属解析需同步（回落机制保证不中断）。
- **与 042（三级配额，规划中/整合方案 §4.11）**：042 的团队/项目级配额消耗计量与本特性**共用同一数据源**（`token_usage_logs` + 归属链路）。本特性只做关系声明——**不在本特性实现配额**（Non-Goals）；反向声明：042 立项时应直接复用本特性的 agent_id/skill_id/workspace_id 埋点与六维聚合，不重复建数据源。
- **与 017-three-scope-memory / 021-unified-context-address（语义同源）**：空间维度的 `workspace_id` 口径与 017 的 workspace scope、021 的 `mogo://` 地址空间同源（决策表第 2 项），不发明第二套空间标识。

## Non-Goals

- 不实现三级配额（团队/项目级配额属整合方案 §4.11 / 042，只做关系声明与数据源共用预留）。
- 不新建计量管线或新集合——`token_usage_logs` 与 007 写入链路原样复用，只加字段。
- 不改变 008 既有端点契约的既有字段语义（向后兼容扩展：新增维度段与下钻字段）。
- 不实现模型分层路由（整合方案 §4.9，另需立项）——虽然路由决策影响成本，但归集只记录不路由。
- 不做前端大改——admin-web 驾驶舱成本 tab 消费新维度段（展示扩展），交互范式沿用 008。
- 不回填历史数据的 agent_id（无来源可回填；归 `未分配` 并在 reason 注明）。
- 不实现跨租户成本对比（008 Non-Goals 既有纪律保持）。
