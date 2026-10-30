# Feature Specification: 成本归集补维（部门/Agent/项目 + 单条成本透出）

**Feature Branch**: `035-cost-attribution`

**Created**: 2026-10-23

**Status**: Draft（2026-10-30 按五维修订）

**Input**: User description: "008 驾驶舱成本维当前只按 model_name 分组，部门/Agent 归集是诚实占位（departmentAttribution.available=False），空间/业务线维度不存在；多维聚合库函数 attribute_cost / aggregate_usage 已写好但零生产调用方。补部门/Agent/空间/业务线四个归集维度，把库函数接入 dashboard 生产调用，单次调用下钻透出单条成本金额。"

> **设计来源**：本规约落地《MOGO × 企业 Agent OS 整合方案》§4.4「成本归集补维」（文章六维归集：企业/空间/应用/模型/业务线/用户）。
>
> **性质说明**：这是**补数据源 + 接线的补维特性**（全新特性，代码尚未开工，任务清单全部未勾选）——008 的诚实占位纪律（无数据源时显式标注而非填零）是本特性的继承基线；两个多维聚合库函数（`dashboard_metrics.attribute_cost`、`metering.aggregate_usage`）已写好但零生产调用方，本特性把它们接入 `dashboard.py` 生产调用。
>
> **变更记录（2026-10-30，同步代码整改）**：①**业务线维度取消**——`is_business_line` 全仓只有读方没有写方，读取分支退化成单桶「企业总部」且 `available=True`（假数据），维度数 6 → 5；②**「空间」维度更名为「项目」**——`TokenUsageRecord.workspace_id` 改名 `project_id`，口径见 `Decisions/ADR-8-统一项目概念-项目即工作目录.md`（项目 = 工作目录，web 会话落默认项目 `"default"`）；③**「企业」维度更名为「租户」**——该段本就读 `tenant_id`，`enterpriseAttribution` → `tenantAttribution`（维度保留，它是对账锚点）。三项的核实证据与改动清单见 `review-2026-10-30-dimension-source-audit.md` §4 与 §7.1。

## 定位（一句话）

给 008 驾驶舱的成本维补齐三个归集维度（部门/Agent/项目），使成本归集覆盖到"租户 / 用户 / 部门 / Agent / 项目"五段——核心动作是**补数据源**（`TokenUsageRecord` 增加 `agent_id` 及归属链路、`project_id` 归属、部门经 `end_user_org_relations` 反查）与**接库函数**（`attribute_cost`/`aggregate_usage` 接入 `dashboard.py::_cost_section()` 替换诚实占位），同时让单次调用下钻透出单条成本金额，无数据源的维度延续 008 诚实占位纪律显式标注。

## 已定决策（2026-10-23 拍板；2026-10-30 第 2、3 项修订）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | `agent_id` 埋点位置与归属链路 | `TokenUsageRecord` 新增 `agent_id` 字段；埋点在 `instrumented_client.py::_submit_record`——从 `output_spec`（含 `get_request_context()` 动态上下文，`factory.py:72-76` 已合并）读 `agent_id`，与现有 `node_id`/`tenant_id`/`user_id` 同机制，零新管道。归属链路：**Agent → Skill → 资产**——记录同时携带 `skill_id`（有则填），Agent 维度聚合时经 018 能力资产注册表把 agent/skill 解析到资产名（无资产登记时回落 agent 原始 ID） | `token_usage/models.py` + `instrumented_client.py` 记录构造处 |
| 2 | 项目维度数据来源（原「空间」） | **项目 = 工作目录（`workspace_id`）**，记录字段名统一为 **`project_id`**：code 会话取会话绑定的 `workspace_id`，web 会话（无本地目录）取保留值 `"default"`（默认项目）。**不新建项目表**——服务端项目记录复用 `desktop_projects`（改名为 `projects`），本地目录路径永不上云。~~原口径"与 017 记忆 scope、021 `mogo://` 同源"作废~~：017 的 workspace scope 声明存在但空转（`is_workspace_member` 全仓只有测试传 True），021 的 `mogo://` 是上下文地址而非归集主体，二者都不能作为项目维度的语义依据 | `token_usage/models.py` 新字段 + `output_spec` 读取 |
| 3 | ~~业务线维度数据来源~~ **（已取消）** | **业务线维度取消**。原设计"业务线 = 部门树扩展"依赖 `org_units.is_business_line`，但该字段**没有任何写入方**（`column_map.py` 列映射、`directory.py` 部门创建/更新 payload、`ensure_root_department` 都没有它），读取侧"回落最高可见祖先"的实现必然返回根节点 → 恒为单桶「企业总部」且 `available=True`。产品上组织维度只有部门树一层，需要"业务线视角"时用部门树的某个子树即可。部门维度本身（008 FR-2 既有承诺）仍经 `end_user_org_relations` 反查——**仅计数**，不伪造分摊算法 | 见 review §4.3 删除清单 |
| 4 | 单条成本透出的计价口径 | **复用 007 pricing**：`token_usage_logs.cost_estimate_usd` 已由 `instrumented_client.py:209` 写入（007 T019，token × 008 `MODEL_PRICES` 单价）；下钻透出优先取该字段，缺失时（历史行）按 `analytics.py:325-332` 既有 `MODEL_PRICES` + `DEFAULT_PRICE` 兜底计算，保证单条金额与汇总对账一致 | `analytics.py` 详情/列表 + `dashboard.py` |
| 5 | 无数据源维度的占位规则 | **延续 008 诚实占位纪律**：某维度无数据源（如某租户从未埋 `agent_id`）时，该维度返回 `available: False` + `reason`（说明缺什么、谁补齐），**不填零、不伪造数值**；有数据源的维度正常聚合。`reconciles` 对账自检保持绿（五个归集段各自与总量对账，浮点容差沿用 `COST_TOLERANCE`） | `dashboard.py::_cost_section` 各 dimension 段 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - TokenUsageRecord 补 agent_id 与归属链路埋点（Priority: P1）

chat-api 的 LLM 调用记录（`token_usage_logs`）新增 `agent_id`（及 `skill_id`、`project_id`）字段：Agent 运行时把当前 Agent/Skill/项目标识经 `output_spec`/请求上下文传入，`InstrumentedLLMClient._submit_record` 写入记录。此后每次 LLM 调用都知道"是谁花的钱、花在哪个项目上"。

**Why this priority**: 这是三个新维度的**唯一数据源底座**——`dashboard.py:674` 的诚实占位原文即"agent_id 无数据源（TokenUsageRecord 缺字段）"。不补字段，dashboard 侧无从聚合；掩码/下钻都无从谈起。优先于所有消费侧改造。

**Independent Test**: 用 fake output_spec/请求上下文构造一次 `InstrumentedLLMClient.ainvoke`（fake 内层 client），断言落库记录含 `agent_id="agent-a"`、`skill_id="skill-b"`、`project_id="ws-1"`；不传时字段为空串且不影响记录落库（向后兼容）。

**Acceptance Scenarios**:

1. **Given** 请求上下文含 `agent_id=agent-a`，**When** 一次 LLM 调用完成落库，**Then** `token_usage_logs` 该行 `agent_id == "agent-a"`。
2. **Given** Agent 经 Skill 执行且 output_spec 携带 `skill_id`，**When** 落库，**Then** `skill_id` 非空，且可经 018 资产注册表解析到资产名（解析不到时回落原始 ID，不报错）。
3. **Given** 历史调用方不传 agent_id/skill_id/project_id，**When** 落库，**Then** 三字段为空串，记录结构与字段总数不变（既有消费方零影响）。
4. **Given** 一次 DAG 编排内多节点调用（`node_id` 不同、`agent_id` 相同），**When** 落库，**Then** 各行 `agent_id` 一致、`node_id` 各自独立——Agent 维度能把多节点成本归并到一个 Agent。

---

### User Story 2 - 驾驶舱成本 section 五段归集（Priority: P1）

admin-web 运营驾驶舱成本 tab 在原有模型/用户/租户维度之外，新增部门、Agent、项目三个分组（共 5 个归集段，模型分组沿用 008 既有 `build_cost_section`）；`_cost_section()` 接入 `attribute_cost`（admin-api 库函数）与 `aggregate_usage`（chat-api 库函数，admin-api 侧等价聚合或经共享逻辑）做多维分组；每个维度标注 `available` 与 `reason`，无数据源不填零。

**Why this priority**: 这是整合方案 §4.4 的**正文目标**与 008 FR-2 的既有承诺（"按部门/智能体分摊 → 可下钻"）的兑付——`dashboard.py:713-716` 的诚实占位从"待补齐"变为"已补齐"。与 US1 共同构成特性 MVP。

**Independent Test**: fake DB 预置含 `agent_id`/`user_id`（关联 `end_user_org_relations`→`org_units`）/`project_id` 的多行 usage；调 `dashboard._cost_section(db, tenant)`，断言：`departmentAttribution.available == True` 且含部门桶、`agentAttribution` 含 agent 桶、`projectAttribution` 口径正确；再构造无 agent_id 的数据，断言对应维度 `available == False` + reason 非空、且 `reconciles` 仍为 True。

**Acceptance Scenarios**:

1. **Given** 近 24h usage 行带 `agent_id`/`user_id`/`project_id` 且用户有部门关系，**When** 调 `/overview`，**Then** 成本 section 含 department/agent/project 三个新归集段（连同既有 user/enterprise 共 5 段），各段 `calls`/`tokens`/`cost` 分桶合计与 `totalCost` 对账一致（`reconciles` 绿）。
2. **Given** 某租户 usage 行全部无 `agent_id`，**When** 调 `/overview`，**Then** `agentAttribution.available == False` 且 `reason` 说明"TokenUsageRecord.agent_id 无数据"，其余维度正常。
3. **Given** 用户无部门关系（`end_user_org_relations` 无行），**When** 部门维度聚合，**Then** 该用户成本归 `未分配` 桶，不猜部门。
4. **Given** 一次 web 会话（无本地目录）的调用，**When** 项目维度聚合，**Then** 该成本落 `"default"` 默认项目桶，**不落 `未分配`**——每个会话都有 `project_id`，项目维度不应出现 `未分配` 桶。
5. **Given** 五段各自分组，**When** 逐维对账，**Then** 每维分桶成本合计 = `totalCost`（容差内）——分组不丢行、不重行。

---

### User Story 3 - 单次调用下钻含单条成本金额（Priority: P2）

analytics 的 token 用量下钻（`groupBy=user_request|session` 列表与 `GET /token-usage/{request_id}` 详情）透出单条成本金额：列表行新增 `costUsd`（取 `cost_estimate_usd`，缺失按定价兜底），详情返回增加 `costUsd`、`modelName`、token 分解等既有字段，使"某一次请求到底花了多少钱"可回答。

**Why this priority**: 这是文章"单次调用可下钻"要求的直接兑现，也是 008 FR-10（异常可下钻到请求）的成本侧补全。优先级 P2：它消费 US1 埋好的数据但不阻塞五段归集主体；先有维度汇总、再有单条下钻，符合由粗到细的交付顺序。

**Independent Test**: fake DB 预置带 `cost_estimate_usd=0.0123` 与不带（历史行）的两类 usage 行；调 `GET /analytics/token-usage?groupBy=user_request` 与 `GET /analytics/token-usage/{request_id}`，断言列表行与详情均含 `costUsd`（前者 0.0123、后者按 `MODEL_PRICES` 兜底计算值），且详情含 `modelName`。

**Acceptance Scenarios**:

1. **Given** 一行 `cost_estimate_usd=0.0123` 的 usage 记录，**When** 进入下钻列表/详情，**Then** `costUsd == 0.0123`（直接透出埋点值）。
2. **Given** 一行历史记录无 `cost_estimate_usd`，**When** 下钻，**Then** `costUsd` 按 `MODEL_PRICES`/`DEFAULT_PRICE` 兜底计算（口径与 `analytics.py:325-353` 汇总计算一致），不为 null、不为 0 冒充。
3. **Given** 单请求下钻（一个 user_request 多条 LLM 调用），**When** 查看，**Then** 每条调用各自带 `costUsd`，且列表行 `costUsd` 之和与该请求在成本 section 中的占比自洽。
4. **Given** 无权限的跨租户 request_id，**When** 请求详情，**Then** 403（沿用 `analytics.py:456-457` 既有租户隔离，不因新增字段放宽）。

---

### User Story 4 - 对账自检与诚实占位纪律回归（Priority: P2）

五段归集上线后，成本 section 的 `reconciles` 自检保持绿；空维度显式标注；既有 008 相关测试（`test_dashboard_routes.py::test_cost_section_is_wired_and_reconciles`、`test_dashboard_selfcheck.py`）与新测试共同守住"不伪造数值"纪律。

**Why this priority**: 008 的立身之本是"诚实看板"（`dashboard.py:673-676` 注释原文：deliberately not fabricated）。补维最容易翻车的就是"为了维度好看而填零/猜数"——本故事把纪律固化为测试与验收，优先于任何锦上添花。

**Independent Test**: 跑 admin-api 既有 dashboard 测试全绿 + 新增"空维度不伪造"用例（无 agent_id/无部门关系/无 project_id 三种空数据场景下，对应维度 available=False 且 reason 非空、reconciles=True、无 0 值桶冒充）。

**Acceptance Scenarios**:

1. **Given** 五段数据齐备，**When** 任一维分组，**Then** `reconciles` 为 True（分组合计 = 总量，容差内）。
2. **Given** 某维度完全无数据源，**When** 返回，**Then** 该段 `available: False` + `reason`，且不出现该维度的 0 值分桶列表（空列表 + 标注，而非伪造一行 0）。
3. **Given** 既有 `test_dashboard_routes.py:149-193` 的断言（含 `departmentAttribution.available is False` 的历史场景），**When** 数据源补齐后测试更新，**Then** 新断言覆盖"有数据源时 available=True"与"无数据源时 available=False"两种场景，纪律不丢。

---

### Edge Cases

- **历史数据无 agent_id**：`agent_id` 埋点上线前的存量 `token_usage_logs` 行无该字段。Agent 维度对这些行归 `未分配`（与 `attribute_cost` 既有 `未分配` 兜底一致，`dashboard_metrics.py:310`），不回填、不猜；维度 `reason` 注明"含埋点前历史数据"。
- **agent_id 与 node_id 的关系**：DAG 编排一次运行含多节点 LLM 调用（`node_id` 不同）。agent 维度按 `agent_id` 归并（多节点→一个 Agent 桶），`node_id` 维度保持既有语义（`aggregate_usage` 的 agent 分支已含 `node_id` 回落，`metering.py:59`）——两者不互相覆盖。
- **一用户多部门**：`end_user_org_relations` 理论上可多行。部门反查按主部门（首行/最新行）计，`reason` 注明口径；不把一次调用重复计入多个部门（防双计破坏对账）。
- **项目维度不产生 `未分配`**：与其它维度不同，项目维度有兜底（web 会话 = 默认项目 `"default"`），因此只要有调用记录，项目段 `available` 恒为 True。若出现 `未分配` 桶，说明 `project_id` 写入链路坏了（埋点或回填缺失），应作为数据质量告警而非正常空态。
- **`project_id` 单一来源**：记录只写 `project_id` 一个字段（不再有 `workspace_id` 与之并存）。code 会话取会话绑定的 `workspace_id` 值，web 会话取 `"default"`；迁移期读侧兼容 `project_id or workspace_id or "default"`，写入只写 `project_id`。
- **成本字段精度**：`cost_estimate_usd` 为 float；分桶求和沿用 `round(..., 6)`（`dashboard_metrics.py:319`）与 `COST_TOLERANCE` 对账容差，五段各自对账而非跨维相加（不同维度的同一行成本在各维各出现一次是设计使然，不与总量混算）。
- **空租户**：无任何 usage 行时各维度空态（008 FR-9 既有纪律），`reconciles` 对空总量为 True，不报错。
- **单条成本与汇总的一致性**：下钻 `costUsd` 与 dashboard 汇总必须同源（都经 007 pricing / `MODEL_PRICES`），防止"汇总 1.2、下钻合计 1.5"的对账穿帮；汇总侧优先用埋点 `cost_estimate_usd`（与 `metering.py:78`、`dashboard_usage.py:55` 既有口径一致）。
- **跨租户读取**：所有新维度查询沿用 `tenant_match`/租户隔离（008 FR-7），部门反查带 tenant_id 条件（`analytics.py:120-123` 既有范式）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `TokenUsageRecord`（`services/chat-api/app/token_usage/models.py`）MUST 新增 `agent_id`、`skill_id`、`project_id` 三个字段（默认空串），既有字段与默认值不变。~~原 `workspace_id` 字段~~按 ADR-8 D0 统一命名为 `project_id`（该字段上线后恒空、无消费方，改名零成本）。
- **FR-002**: 埋点 MUST 落在 `services/chat-api/app/llm/instrumented_client.py::_submit_record` 的记录构造处：从 `output_spec`（含 `get_request_context()` 合并，`factory.py:72-76`）读取 `agent_id`/`skill_id`/`project_id`，与既有 `tenant_id`/`user_id`/`node_id` 同机制写入。`project_id` 由 DSH 网关按 `sessionId` 反查 `agent_kernel_bindings.source_workspace_id` 得到、缺省 `"default"`，**不信任客户端在请求体里上报的 workspace_id**。
- **FR-003**: Agent 运行时调用链 MUST 把当前 Agent/Skill 标识传入请求上下文或 output_spec（或复用既有 Agent 执行处已设置的上下文键）；不新增独立埋点管道。
- **FR-004**: Agent 维度聚合 MUST 支持归属链路解析：Agent/Skill 经 018 能力资产注册表解析资产名（解析不到回落原始 ID），`skill_id` 随记录携带供链路还原。
- **FR-005**: `dashboard.py::_cost_section()` MUST 接入 `dashboard_metrics.attribute_cost`（admin-api 库函数）做部门/项目归集，接入等价于 `metering.aggregate_usage` 的多维聚合做 Agent 归集（admin-api 侧按同口径实现或共享逻辑），替换现有仅按 `model_name` 的单一分组。
- **FR-006**: 部门维度 MUST 经 `end_user_org_relations` → `org_units` 反查（仅计数口径：调用数/用户数/成本按部门分桶），无部门关系归 `未分配`；反查带租户隔离。
- **FR-007**: 项目维度 MUST 按记录 `project_id` 分桶；`project_id` 为空的记录（埋点前历史行）归 `未分配` 并在 reason 注明"埋点前历史数据"，新会话 MUST NOT 出现空 `project_id`（web 会话兜底 `"default"`）。~~业务线维度取消~~：不再有 `business_line` 归集段、不再读 `org_units.is_business_line`、不再有回落祖先逻辑。
- **FR-008**: analytics 下钻（`GET /analytics/token-usage` 列表行与 `GET /analytics/token-usage/{request_id}` 详情）MUST 透出单条成本 `costUsd`：优先 `cost_estimate_usd` 埋点值，缺失按既有 `MODEL_PRICES` + `DEFAULT_PRICE` 兜底计算（口径与 `analytics.py:325-353` 汇总计算一致）。
- **FR-009**: 无数据源的维度 MUST 显式返回 `available: False` + `reason`（说明缺什么数据源），MUST NOT 填零、MUST NOT 伪造分桶；有数据源的维度 MUST 正常聚合。
- **FR-010**: 成本 section 的 `reconciles` 对账自检 MUST 保持绿（各维分桶合计与 `totalCost` 一致，容差沿用 `COST_TOLERANCE`）；单条 `costUsd` 与汇总 MUST 同源同口径。
- **FR-011**: 全部新查询 MUST 按租户隔离（008 FR-7 口径），跨租户请求拒绝（403）。
- **FR-012**: 埋点字段缺失的存量数据 MUST 归 `未分配` 兜底，不阻塞聚合、不回填历史。

### Key Entities

- **TokenUsageRecord（扩展）**: `token_usage_logs` 行模型，新增 `agent_id`/`skill_id`/`project_id`；`cost_estimate_usd`（007 T019 已写入）是单条成本透出的主数据源。
- **成本归集维度（五段）**: 租户（`tenant_id`，既有，原称"企业"）/ 用户（`user_id`，既有）/ 部门（`end_user_org_relations` 反查，本特性接线）/ Agent（`agent_id` + 018 资产链路，本特性补数据源）/ 项目（`project_id`，本特性补数据源）。模型分组（`model_name`）由 008 的 `build_cost_section` 单独给出，不在这 5 段内。~~业务线~~已取消（2026-10-30）。
- **attribute_cost**（复用，`dashboard_metrics.py:297-320`）: 任意维度成本归集库函数（`未分配` 兜底 + 按成本降序）——已写好零生产调用方，本特性接入。
- **aggregate_usage**（复用，`metering.py:39-83`）: provider/model/tenant/agent 四维聚合纯函数——已写好仅测试引用，本特性以等价口径接入 admin-api 侧 Agent 归集。
- **org_units / end_user_org_relations**（复用）: 部门树（`parent_id`/`path_ids`）与用户部门关系，部门维的反查源（不再承载业务线语义）。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 五段均可分组聚合——成本 section 返回租户/用户/部门/Agent/项目五个归集段（外加 008 既有模型分组），每维分桶合计与 `totalCost` 对账一致（`reconciles` 绿）。租户段恒为单桶（值 = `totalCost`），作为对账锚点。
- **SC-002**: 单次调用可下钻且含单条成本金额——下钻列表行与详情均含 `costUsd`（埋点值或定价兜底），且与汇总同源（汇总 1.2 时下钻合计 1.2，容差内）。
- **SC-003**: 对账自检保持绿——`reconciles` 在五段齐备/部分缺失/空租户三种场景下均为 True，既有 `test_dashboard_routes.py`/`test_dashboard_selfcheck.py` 相关用例全绿。
- **SC-004**: 空维度不伪造数值——无数据源维度 100% 返回 `available: False` + `reason`，响应中无该维度的 0 值分桶冒充（测试断言三种空场景）。**业务线维度不得以任何形式回归**（不返回空桶、不返回单桶"企业总部"）。
- **SC-005**: 埋点向后兼容——不传 `agent_id`/`skill_id`/`project_id` 的调用方记录结构与既有消费方零影响（既有 token_usage 相关测试全绿）。
- **SC-006**: 归集口径可解释——每个维度在 API 响应中携带口径说明（数据源字段/回退规则），运营查看时无需读代码即可理解"这个数怎么来的"。

## Assumptions

- 假设 008 的 dashboard 结构与诚实占位纪律是既定基线（已代码级核实：`dashboard.py:665-717` `_cost_section` + `departmentAttribution` 诚实声明；`test_dashboard_routes.py:149-193` 有对应断言），本特性在其上演进而非重建。
- 假设 `cost_estimate_usd` 已由 007 链路稳定写入（已核实：`instrumented_client.py:209`、`token_usage/models.py:36`），单条成本透出以它为主源、定价表兜底只为历史行。
- 假设 `attribute_cost`/`aggregate_usage` 两个库函数签名与语义稳定（已代码级核实，均有测试覆盖），接入不改变其 pure 函数契约。
- 假设 Agent 运行时（orchestration/dsh_runtime）能在 LLM 调用前后把 agent/skill 标识放入请求上下文——`get_request_context()` 机制（`infrastructure/request_context.py`）与 `factory.py:72-76` 的合并逻辑已就绪，Agent 执行处只需 merge 对应键（或 output_spec 已携带）。
- 假设 018 能力资产注册表可按 agent/skill ID 反查资产名（资产注册是 018 既有能力）；查不到时回落原始 ID 不报错。
- 假设 `org_units` 含 `path_ids` 祖先链（已核实：`ontology_permission.py:153` 使用该字段做组织含下级展开），部门维度只做单部门反查，不沿祖先链派生新维度。

## 跨特性关系

- **与 008-ops-dashboard（直接扩展对象）**：008 的四维驾驶舱成本维（US2/FR-2/FR-6）是本特性的**受管基线**——`_cost_section()` 的既有结构（模型分组 + 对账 + 预测 + 诚实占位）原样保留，本特性只做"补维 + 替换占位 + 补下钻"。反向声明：008 的诚实占位纪律（无数据源显式标注）被本特性继承为验收项（FR-009/SC-004）；008 既有端点契约向后兼容扩展（新增字段与维度段，不改既有字段语义）。
- **与 007-llm-gateway-resilience（计量来源）**：007 的计量上报（`cost_estimate_usd`、`token_usage_logs` 写入、`resilience_events`）是本特性的数据源；本特性不改 007 写入链路，只新增记录字段的填充。反向声明：007 的 failover/降级字段已在记录中（008 FR-8 消费），本特性的新字段与其共存于同一记录，互不覆盖。
- **与 018-capability-asset-registration（归属链路）**：018 的资产注册表是 Agent→Skill→资产归属解析的查找源（FR-004）。反向声明：018 不感知本特性；若 018 后续调整资产 ID 体系，本特性的归属解析需同步（回落机制保证不中断）。
- **与 042（三级配额，已实现/整合方案 §4.11）**：042 的项目级配额消耗计量与本特性**共用同一数据源**（`token_usage_logs` + 归属链路）。本特性只做关系声明——**不在本特性实现配额**（Non-Goals）；反向声明：042 的"项目"直接复用本特性的 `project_id` 埋点与五段归集，不再维护独立的 `quota_projects` 成员语义（按 ADR-8 D0 收敛）。
- **与 ADR-8（项目概念的唯一依据）**：项目 = 工作目录（`workspace_id`），默认项目 `"default"`，`desktop_projects` 改名 `projects`。~~原"空间维度与 017 记忆 scope / 021 `mogo://` 语义同源"的说法作废~~：017 的 workspace scope 声明存在但空转，021 的 `mogo://` 是上下文地址而非归集主体，二者都不能作为项目维度的语义依据。

## 判定口径补充（2026-10-23，/speckit-checklist 回填；2026-10-30 修订）

- ~~**R-1 业务线标记的维护**~~ **（已作废，2026-10-30）**：`org_units.is_business_line` 从未有写入路径，业务线维度取消。原 R-1 声称"经既有组织单元写入路径维护"与代码不符（`column_map.py`、`directory.py` payload、`ensure_root_department` 均无该字段）。**后续不得重新引入该字段。**
- ~~**R-2 业务线回落判据**~~ **（已作废，2026-10-30）**：原"沿 `path_ids` 取第一个 `is_business_line` 祖先、无标记回落最高可见祖先"的实现必然返回根节点，导致恒为单桶「企业总部」且 `available=True`（假数据，违反 FR-009）。删除清单见 `review-2026-10-30-dimension-source-audit.md` §4.3。
- **R-3 Agent 归属链路（首期简化，与 FR-004 有偏差）**：首期 Agent 维度的桶键直接取记录的 `agent_id`（为空时回退 `node_id`），**不做 018 能力资产注册表的名称解析**——资产名解析需要跨服务读资产表且要处理改名后的历史一致性，留待 036/018 侧提供映射后增强。`skill_id` 随记录携带，供后续链路还原；文档与 reason 文案如实说明"未登记回落原始能力引用 ID"。
- **R-4 部门维度用户数口径**：用户数 = 窗口内该部门桶下**去重 `user_id`** 计数；`user_id` 为空的行只计入调用数与成本，不计入用户数；不做跨期去重（每次查询按 24h 窗口现算）。
- **R-5 `未分配` 桶计入对账**：`未分配` 是**真实桶**，参与该维度的 `items` 合计与 `reconciles` 校验；因为 `attribute_cost` 对所有行分桶（含未分配），各维分桶合计恒等于窗口内 `totalCost`，对账容差沿用 `COST_TOLERANCE`。
- **R-6 项目维度取值口径**：记录只有一个字段 `project_id`——code 会话取会话绑定的 `workspace_id`，web 会话取保留值 `"default"`，埋点前历史行为空串归 `未分配`。迁移期读侧兼容 `project_id or workspace_id or "default"`，**写入只写 `project_id`**；reason 文案统一称"项目"，不再出现"空间/workspace"两个口径。
- **R-7 单条 `costUsd` 的计价时点**：以**写入时埋点值** `cost_estimate_usd` 为准（007 T019 口径）；仅当该字段缺失（历史行）时用查询时的 `MODEL_PRICES` + `DEFAULT_PRICE` 兜底计算。因此价目表事后调整**不影响**已有行金额，历史行兜底值可能与当日重算值存在差异，属预期；文档不做"按现价重算"承诺。
- **R-8 `available` 判定**：窗口内**无任何调用记录** → `available: False` + reason（"近 24h 内无调用记录"）；有记录但该维度**全部落入 `未分配`** → `available: False` + reason（"全部调用缺失该维度数据源"）；只要有**至少一行**带真实维度值 → `available: True`（reason 为 `None`），部分未分配不影响可用性判定。
- **R-9 维度键名与返回结构**：五个归集段固定为 `departmentAttribution` / `agentAttribution` / `projectAttribution` / `userAttribution` / `tenantAttribution`（~~`businessLineAttribution` 已删除~~，~~`spaceAttribution` 更名为 `projectAttribution`~~，~~`enterpriseAttribution` 更名为 `tenantAttribution`~~）；每项结构 `{dimension, available, reason|null, note, items[]}`，`items[]` 元素 `{key, dimension, calls, tokens, cost}`（按 `cost` 降序，cost 保留 6 位小数）。008 既有 `models` / `reconciles` / `forecast` 字段**原样保留**，新维度为**追加**（响应只增不改；删除 `businessLineAttribution`、改名 `spaceAttribution`→`projectAttribution` 与 `enterpriseAttribution`→`tenantAttribution` 属破坏性变更，需同步改前端 `DashboardPage.vue` 与测试）。
- **R-10 价目同源**：汇总与单条金额共用同一套 `MODEL_PRICES` + `DEFAULT_PRICE`（008）作为兜底源；`cost_estimate_usd` 是 007 写入的快照值。两者单价若漂移，以"快照优先、兜底统一"为口径，`reconciles` 只校验**同一响应内**的分桶合计与总和，不跨快照与实时值对账。
- **R-11 018 资产表读取侧**：首期**不由 admin-api 读取 018 资产表**（见 R-3），所有维度归集只读 `token_usage_logs` + `end_user_org_relations` + `org_units` 三张集合；因此 dashboard 归集无跨服务调用、无额外延迟。
- **R-12 与 036 的边界**：035 只提供"成本按维归集"的读接口；036 可信评级若要消费成本，必须复用本特性的 `attribute_cost`/维度结构，**不得自行再写一套归集**（本特性不实现任何降级/评级逻辑）。
- **R-13 跨租户隔离落点**：所有反查都带 `tenant_id` 过滤——`token_usage_logs` 匹配含 `tenant_id`；`end_user_org_relations` 查询为 `{"tenant_id": ..., "user_id": {"$in": [...]}}`；`org_units` 经关系表解析出的 `org_id` 集合加载（不跨租户扫描）。跨租户请求由既有 008 鉴权层拒绝（403），本特性不新增鉴权分支。
- **R-14 存量不回填的运营闭环**：存量记录缺 `agent_id`/`project_id` 一律归 `未分配`、不回填历史（FR-012）；为区分"没数据"与"埋点坏了"，每个维度返回 `reason`/`note` 文案说明缺什么数据源，运维据此判断补救路径（补埋点后新数据自动进入正确桶）。首期不做一次性回填脚本。**例外**：`chat_sessions.project_id` 与 `token_usage_logs.project_id` 按 ADR-8 D4 做**全量回填**（回填的是会话→项目归属，不是调用记录的维度字段）。
- **R-15 归集窗口与行数上限**：归集窗口与 008 成本 section 一致为**近 24h**；单次归集最多读取 **50000** 行（`DIMENSION_ROW_LIMIT`，内存分桶，不额外下发聚合管道），超限按窗口内前 50000 行计算，属已知取舍。

## Non-Goals

- 不实现三级配额（项目级配额属整合方案 §4.11 / 042，只做关系声明与数据源共用预留）。
- 不新建计量管线或新集合——`token_usage_logs` 与 007 写入链路原样复用，只加字段。
- 不改变 008 既有端点契约的既有字段语义（向后兼容扩展：新增维度段与下钻字段；删除 `businessLineAttribution` 是唯一例外，需同步前端）。
- 不实现模型分层路由（整合方案 §4.9，另需立项）——虽然路由决策影响成本，但归集只记录不路由。
- 不做前端大改——admin-web 驾驶舱成本 tab 消费新维度段（展示扩展），交互范式沿用 008。
- 不回填历史数据的 agent_id（无来源可回填；归 `未分配` 并在 reason 注明）。
- 不实现跨租户成本对比（008 Non-Goals 既有纪律保持）。
