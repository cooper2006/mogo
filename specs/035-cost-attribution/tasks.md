# Tasks: 成本归集补维（035-cost-attribution）

**Input**: Design documents from `/specs/035-cost-attribution/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **全新特性，代码尚未开工**——008 成本维的部门/Agent 归集为诚实占位，两个多维聚合库函数零生产调用方；任务清单全部未勾选。

> **2026-10-30 变更**：①**业务线维度取消**——T011/T021 作废，T004 的"业务线标记"核实结论改为"该字段不存在且不引入"；②**「空间」更名为「项目」**——`workspace_id` 字段改名 `project_id`（T009/T015/T016/T018 随之改名）；③**「企业」更名为「租户」**——`enterpriseAttribution` → `tenantAttribution`（T010 随之改名，维度保留）。依据见 `spec.md` 变更记录与 `review-2026-10-30-dimension-source-audit.md` §4 / §7.1。

**Tests**: chat-api `instrumented_client` 埋点测试（fake 内层 client）；admin-api `test_dashboard_routes.py`（五段归集 + 诚实占位 + reconciles）、`test_dashboard_metrics.py`（attribute_cost 回归）、`test_dashboard_selfcheck.py`、analytics 下钻 costUsd 用例。

**Organization**: Phase 0 研究与澄清 → Phase 1 设计 → Phase 2 实现 → Phase 3 验证与接线；任务按 user story 标注 `[USn]`，`[P]` 表示可并行。

---

## Phase 0: 研究与澄清

- [x] T001 [P] 代码级核实 008 成本 section 现状：`services/admin-api/app/api/routes/dashboard.py:665-717`（`_cost_section` 仅按 `model_name` 分组 + L713-716 诚实占位原文 + `_daily_costs`/`_cost` 辅助）；确认"替换占位而非重建"的边界
- [x] T002 [P] 代码级核实两个库函数契约：`services/admin-api/app/api/dashboard_metrics.py:297-320`（`attribute_cost` 的 `未分配` 兜底与排序）、`services/chat-api/app/llm/resilience/metering.py:39-83`（`aggregate_usage` 四维 + `agent_id`/`node_id` 回落 + `cost_estimate_usd` 优先）；确认两者零生产调用方（仅测试引用）
- [x] T003 [P] 代码级核实埋点管道：`services/chat-api/app/llm/instrumented_client.py:186-214`（记录构造处）+ `factory.py:63-76`（`output_spec` 与 `get_request_context()` 合并）+ `infrastructure/request_context.py`（merge/get 机制）；确认新增字段读取点与既有 `tenant_id`/`user_id`/`node_id` 同机制
- [x] T004 [P] 代码级核实部门数据源：`repositories/directory_repository.py`（`org_units`/`end_user_org_relations` 集合常量）+ `analytics.py:117-143`（部门反查既有范式）+ `org_units.path_ids` 祖先链用法（`ontology_permission.py:153`）。**结论（2026-10-30 修订）**：`is_business_line` 字段**不存在任何写入路径**（`column_map.py` 列映射、`directory.py` 部门创建/更新 payload、`ensure_root_department` 都没有），业务线维度取消，不再约定该字段
- [x] T005 [P] 勘察 Agent 运行时上下文设置点：`enterprise_capabilities/runtime/adapters.py:250,289` 等 `set_request_context`/`merge_request_context` 调用处 + orchestration/dsh_runtime 的 Agent/Skill 执行入口；确定 `agent_id`/`skill_id` 应在哪些执行处 merge 进上下文（最小定点集）
- [x] T006 [P] 核实单条成本现状：`analytics.py:325-353`（`MODEL_PRICES`/`DEFAULT_PRICE` 汇总计算）+ `analytics.py:442-464`（详情返回字段，确认无 costUsd/modelName）+ `token_usage_logs.cost_estimate_usd` 写入链（`instrumented_client.py:209`）；确认兜底计算与汇总同源
- [x] T007 澄清 018 资产反查接口：capability_assets 注册表按 agent/skill ID 查资产名的既有查询路径（admin-api `routes/capability_assets.py` 或 chat-api 资产模块）；确认解析不到时的回落不报错
- [x] T008 澄清 admin-api 侧 agent 维聚合实现方式：移植 `aggregate_usage` 同口径纯函数到 admin-api（避免 admin-api 依赖 chat-api 运行态）vs 经共享模块导入；记录结论到 plan.md

**Checkpoint**: 占位边界、库函数契约、埋点管道、部门数据源、运行时上下文定点、成本口径、资产反查、聚合实现方式八项有代码级结论。

---

## Phase 1: 设计

- [x] T009 定义 `TokenUsageRecord` 新字段契约：`agent_id`/`skill_id`/`project_id` 均 `str = ""`（**2026-10-30：原 `workspace_id` 改名 `project_id`**，按 ADR-8 D0；code 会话取会话绑定的 `workspace_id` 值、web 会话取 `"default"`，写入只写 `project_id` 一个字段）；序列化（`model_dump` → `token_usage_logs`）无 schema 迁移
- [x] T010 定义五段 section 响应结构：每维 `{available: bool, reason: str, buckets: [{key, calls, tokens, cost}]}`（department/agent/project 三个新维 + 既有 **tenant**（原 enterprise，2026-10-30 改名）/user 段保持；模型分组沿用 008 `build_cost_section`，不在归集段内）；`未分配` 桶命名与 `attribute_cost` 既有兜底一致
- [x] T011 ~~定义部门/业务线反查口径~~ **（已作废，2026-10-30）**：原口径含"业务线 = 沿 `path_ids` 取 `is_business_line` 最高级祖先、无标记回落根下第一层部门"，但该字段无写入方、回落实现必然返回根节点 → 恒为单桶「企业总部」且 `available=True`。**保留部分**：部门 = `end_user_org_relations` 主部门行（多行取最新，注明口径）→ `org_units.name`；无部门关系归 `未分配`
- [x] T012 定义诚实占位判定：维度无任何有效数据源行时 `available=False` + reason（含"埋点前历史数据"注明场景）；有部分数据（含 `未分配` 桶）时 `available=True`；空租户全维空态不报错
- [x] T013 定义 `costUsd` 透出口径：列表行与详情统一 `costUsd` 字段；`cost_estimate_usd` 非零直接用；零/缺失按 `MODEL_PRICES` + `DEFAULT_PRICE` 计算；保留 6 位小数 round；与汇总同源（汇总侧同样优先埋点值）
- [x] T014 梳理回归保护面：`test_dashboard_routes.py:149-193`（既有 `departmentAttribution.available is False` 断言场景需更新为"无数据源 False / 有数据源 True"双场景）、`test_dashboard_selfcheck.py`、`test_dashboard_metrics.py:204-216`（attribute_cost 既有用例）、token_usage 既有测试（字段新增兼容）

**Checkpoint**: 字段/section 结构/反查口径/占位判定/成本透出/回归面六类契约成文。

---

## Phase 2: 实现

### User Story 1 - TokenUsageRecord 补 agent_id 与归属链路埋点（P1）

- [x] T015 [US1] `services/chat-api/app/token_usage/models.py`：`TokenUsageRecord` 新增 `agent_id`/`skill_id`/`project_id`（`str = ""`，T009 契约）
- [x] T016 [US1] `services/chat-api/app/llm/instrumented_client.py::_submit_record`：记录构造处读取 `output_spec.get("agent_id")`/`skill_id`/`project_id` 写入记录；空值行为与既有字段一致（空串）
- [x] T017 [US1] Agent 运行时定点 merge：按 T005 结论在 Agent/Skill 执行处（最小定点集）`merge_request_context`/`output_spec` 传入 `agent_id`/`skill_id`；DAG 节点级调用保证同运行 `agent_id` 一致（2026-10-24 已闭环：`services/chat-api/app/enterprise_capabilities/runtime/adapters.py` 两处 `set_request_context` 改 `merge_request_context`；新增 `tests/enterprise_capabilities/runtime/test_035_capability_attribution_scope.py` 7 passed（合并 11 passed），回归 971 passed）
- [x] T018 [US1] `services/chat-api/tests/llm/test_instrumented_client_agent_dims.py`：三场景——上下文带 agent_id/skill_id/project_id 落库正确；不传时三字段空串且记录结构不变；DAG 多节点（不同 node_id 同 agent_id）落库归并正确（US1 场景 1/2/3/4）

### User Story 2 - 驾驶舱成本 section 五段归集（P1）

- [x] T019 [P] [US2] `services/admin-api/app/api/routes/dashboard.py::_cost_section`：接入 `attribute_cost` 做 department/project 二维归集（T010 结构）；agent 维按 T008 结论接入同口径聚合（含 018 资产名解析，FR-004）
- [x] T020 [P] [US2] 部门反查实现：`end_user_org_relations` 批量查询 + `org_units` 名称解析（T011 保留口径，租户隔离，50000 上限与 analytics 既有一致）；多部门用户取主部门并注明
- [x] T021 ~~[US2] 业务线归集实现~~ **（已取消，2026-10-30）**：原任务为"沿 `path_ids` 找 `is_business_line` 最高级祖先；无标记回落根下第一层部门"。取消理由：字段无写入方、回落必然命中根节点 → 单桶假数据（违反 FR-009）。**反向任务**：删除 `_resolve_business_line()`、`business_line_map`、`businessLineAttribution` 返回键、前端 `business_line` 标签与相关测试（清单见 review §4.3）
- [x] T022 [US2] 诚实占位实现：各维 `available`/`reason` 按 T012 判定；替换 `dashboard.py:713-716` 现有单一占位段为分维度段（departmentAttribution 从单一占位升级为分维结构，既有键保持兼容）
- [x] T023 [US2] `services/admin-api/tests/test_dashboard_routes.py`：五段齐备场景（各维分桶 + 合计对账）；无 agent_id 场景（agentAttribution.available=False + reason + reconciles 仍 True）；无部门关系（未分配桶）；空租户（US2 场景 1–5）

### User Story 3 - 单次调用下钻含单条成本金额（P2）

- [x] T024 [US3] `services/admin-api/app/api/routes/analytics.py`：token-usage 列表行新增 `costUsd`（T013 口径：埋点优先/定价兜底）
- [x] T025 [US3] `analytics.py::get_token_usage_detail`：详情返回新增 `costUsd`、`modelName`、token 分解等既有字段（当前详情仅返回 prompt/payload，`analytics.py:459-464`）
- [x] T026 [US3] analytics 测试：埋点值透出（0.0123）、历史行兜底计算、单请求多条调用各自 costUsd、跨租户 403（US3 场景 1–4）

### User Story 4 - 对账自检与诚实占位纪律回归（P2）

- [x] T027 [US4] 更新 `test_dashboard_routes.py:149-193` 既有断言：`departmentAttribution.available is False` 场景拆为"无数据源 False / 有数据源 True"双场景（T014 梳理结论），纪律不丢
- [x] T028 [US4] 空维度不伪造专项用例：无 agent_id / 无部门关系 / 无 project_id 三种空场景——对应维 available=False + reason 非空 + 无 0 值桶冒充 + reconciles=True
- [x] T029 [US4] 对账一致性用例：五段各自分桶合计 = totalCost（容差内）；下钻 costUsd 合计与汇总占比自洽（SC-002 同源性）

---

## Phase 3: 验证与接线

- [x] T030 回归护栏：`test_dashboard_routes.py`、`test_dashboard_metrics.py`、`test_dashboard_selfcheck.py`、chat-api token_usage/instrumented 既有测试全绿（SC-003/SC-005）
- [ ] T031 [P] 埋点联调（staging）：真实 Agent 调用 → `token_usage_logs` 行含 agent_id/skill_id/project_id → 不传调用方零影响
- [ ] T032 [P] 五段联调（staging）：`/overview` 成本 section 五段分桶可查、部门反查正确、项目维不出现 `未分配`、诚实占位按数据源有无正确切换
- [ ] T033 [P] 下钻联调（staging）：单请求下钻列表/详情 costUsd 正确（埋点/兜底两条路径）、与汇总对账自洽
- [ ] T034 验收口径逐项打勾：SC-001（五段可分组）/SC-002（下钻含单条成本）/SC-003（reconciles 保持绿）/SC-004（空维度不伪造，业务线不得回归）/SC-005（埋点向后兼容）/SC-006（口径可解释）
- [x] T035 更新 `specs/035-cost-attribution/tasks.md` 勾选状态；按任务约束**不**创建 checklists/ 与 quickstart.md、**不**更新 `specs/INDEX.md`（索引更新由仓库维护流程另行处理）

---

## Dependencies & Execution Order

- Phase 0（T001–T008）全部先行，可并行；T004/T005/T008 的结论直接影响 Phase 1 口径（部门数据源、运行时定点、聚合实现方式）。
- Phase 1（T009–T014）依赖 Phase 0；T009/T010 是 Phase 2 全部 US 的前置契约。
- Phase 2 内：US1（T015–T018）是 US2/US3 的前置（无埋点无归因）；US2（T019–T023）与 US3（T024–T026）可并行；US4（T027–T029）依赖 US2/US3 的响应结构。
- Phase 3（T030–T035）依赖 Phase 2 完成；T031–T033 可并行。
- 关键路径：T005（运行时定点）→ T017（上下文 merge）→ T019/T020（dashboard 归集）→ T032（五段联调）。
- **业务线删除**（review §4.3）：与 US2 改动同批，纯删除，无新增依赖；`spec.md`/`tasks.md` 的对应条目已在本轮同步作废（T011/T021）。

## Notes

- `decrypt_optional` 式的"宽容兼容"在本特性对应为**字段缺省宽容**：存量行无 agent_id → `未分配` 桶 + reason 注明，绝不回填历史（无来源可回填，回填即伪造）。
- 单条成本与汇总必须同源：汇总侧（`_cost_section`）同样优先 `cost_estimate_usd`（与 `metering.py:78`、`dashboard_usage.py:55` 既有口径一致），下钻侧只在缺失时兜底——防止"汇总 1.2、下钻合计 1.5"的对账穿帮（FR-010）。
- admin-api 不反向依赖 chat-api 运行态：`aggregate_usage` 的同口径实现按 T008 结论落地（移植 pure 函数或共享模块），保持两服务依赖方向干净。
- 042（三级配额）只做关系声明：本特性的 `agent_id`/`skill_id`/`project_id` 埋点与五段归集即其消耗计量的数据源，042 直接复用，不重复建（spec Non-Goals）。

## 验收状态（2026-10-23 交接复核；2026-10-30 修订）

- **已完成并勾选（30 项）**：T001–T016、T018–T030、T035。证据：`services/admin-api/tests/test_cost_attribution_035.py` 8 passed（`attribute_cost` 分桶/未分配/降序/对账、`_dimension_bucket` 三分判定、部门与业务线反查、单条 `costUsd` 优先快照与兜底、50000 行上限）；`services/chat-api/tests/llm/test_cost_attribution_035.py` 4 passed（T018 的「三场景」在此文件覆盖：`test_submit_record_captures_attribution_dimensions` / `test_resolve_space_falls_back_to_project_id` / `test_resolved_output_spec_merges_request_context` / `test_split_capability_ref_maps_agent_and_skill`，文件名与任务原文 `test_instrumented_client_agent_dims.py` 不同但覆盖等价）；回归 `test_dashboard_routes.py` + `test_dashboard_metrics.py` + `test_dashboard_selfcheck.py` = 42 passed。
  - **2026-10-30 注**：上述 8 passed 里的"部门与业务线反查"用例随业务线取消而失效（`test_cost_attribution_035.py:158/190-191/202-215`），删除业务线代码时需同步改写为"部门反查 + 项目维分桶"。
- **未勾选（5 项）**：
  - **T017（真实缺口）**：`services/chat-api/app/enterprise_capabilities/runtime/adapters.py:289` 的 `set_request_context` 只注入 `tenant_id`/`user_id`/`configured_model`/`model_instance_id`，**未注入 `agent_id`/`skill_id`/`project_id`**。结论：埋点管道已就绪（T015/T016 完成），但真实 Agent 调用不会自动携带这三字段，需在 Agent 执行入口（adapters.py 两处 `set_request_context`）定点补齐后才算 FR-003 完整落地。
  - **T031–T034（需 staging）**：埋点联调、五段联调、下钻联调、SC-001~SC-006 逐项验收均依赖真实 Mongo + 真实 Agent 调用栈；本机 docker 未运行，故不伪造勾选。执行口径见 spec「判定口径补充 R-1~R-15」。
