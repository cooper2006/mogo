# Implementation Plan: 成本归集补维（035-cost-attribution）

**Branch**: `035-cost-attribution` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/035-cost-attribution/spec.md`

**Note**: 本计划为**全新特性**——008 成本维的部门/Agent 归集是诚实占位（`dashboard.py:713-716`），两个多维聚合库函数零生产调用方；本特性补数据源 + 接库函数。代码尚未开工。设计来源：《MOGO × 企业 Agent OS 整合方案》§4.4。

## Summary

给 008 驾驶舱成本维补齐四个归集维度（部门/Agent/空间/业务线），兑付整合方案「六维归集」（企业/空间/应用/模型/业务线/用户）。三条主线：① **补数据源**——`TokenUsageRecord` 新增 `agent_id`/`skill_id`/`workspace_id`，埋点在 `instrumented_client.py::_submit_record` 从 `output_spec`（含请求上下文合并）读取，与既有 `tenant_id`/`user_id` 同机制；② **接库函数**——`dashboard_metrics.attribute_cost`（部门/业务线/空间归集）与等价于 `metering.aggregate_usage` 的 agent 维聚合接入 `dashboard.py::_cost_section()`，替换 `available=False` 诚实占位；③ **透出单条成本**——analytics 下钻列表/详情新增 `costUsd`（`cost_estimate_usd` 优先、`MODEL_PRICES` 兜底）。无数据源维度延续 008 诚实占位纪律（`available: False` + reason，不填零）。

## Technical Context

**Language/Version**: Python 3.11+（chat-api 埋点侧：asyncio + pydantic v2；admin-api 聚合侧：FastAPI + motor/pymongo）

**Primary Dependencies**: 复用既有——`app.token_usage.models.TokenUsageRecord`、`app.llm.instrumented_client`、`app.infrastructure.request_context`（`get_request_context`）、`app.api.dashboard_metrics`（`attribute_cost`/`reconciles`/`COST_TOLERANCE`）、`app.llm.resilience.metering.aggregate_usage`（口径参照）、`app.repositories.directory_repository`（`org_units`/`end_user_org_relations` 集合常量）；**不引入新依赖**。

**Storage**: MongoDB 集合 `token_usage_logs`（新增三个字段，无新集合、无索引变更刚需——`agent_id`/`workspace_id` 分组聚合走既有 24h 窗口扫描；如需索引随 Phase 2 实测补）；`org_units`/`end_user_org_relations` 只读反查。字段新增为向后兼容变更（默认空串），存量行按 `未分配` 兜底。

**Testing**: pytest——chat-api `instrumented_client` 埋点测试（fake 内层 client + output_spec/请求上下文）；admin-api `tests/test_dashboard_routes.py`（`_cost_section` 六维 + 空维度不伪造 + reconciles）、`tests/test_dashboard_metrics.py`（`attribute_cost` 既有用例保持）、`tests/test_dashboard_selfcheck.py`；analytics 下钻 `costUsd` 用例（埋点值/兜底值/403）。

**Target Platform**: Docker Compose（chat-api + admin-api + MongoDB/PanWeiDB）；`_as_utc` 已处理 PanWeiDB 时间戳 ISO 串形态（`dashboard.py:53-60`），新字段聚合不涉及时间解析新形态。

**Project Type**: web-service 后端双服务（chat-api 埋点 + admin-api 聚合），monorepo。

**Performance Goals**: `_cost_section` 现为近 24h 窗口聚合（`dashboard.py:678-679`）；新增维度 MUST 在同一窗口的已取行上做内存分桶（`attribute_cost` 是纯函数，`dashboard_usage.py` 已确立"预取行 + 纯函数分桶"范式），不新增 DB 往返；部门反查为一次 `end_user_org_relations` 批量查询 + 一次 `org_units` 批量查询（`analytics.py:117-143` 既有范式），上限 50000 行与既有一致。

**Constraints**:
- 008 既有端点契约向后兼容：`/overview` 既有字段语义不变，仅扩展 cost section 与 analytics 响应字段。
- 诚实占位纪律不可破：无数据源维度 `available: False` + reason，禁止 0 值桶冒充（FR-009）。
- 单条成本与汇总同源同口径（007 pricing / `MODEL_PRICES` + `DEFAULT_PRICE`），禁止两套计价。
- 埋点向后兼容：新字段默认空串，既有调用方与消费方零影响（SC-005）。
- 全部新查询按租户隔离（008 FR-7）。
- 不实现配额（042 关系只声明）；不回填历史 agent_id。

**Scale/Scope**: 1 个模型文件（+3 字段）+ 1 个埋点文件（记录构造处 + 运行时上下文 merge 点）+ 1 个 dashboard 文件（`_cost_section` 六维化）+ 1 个 analytics 文件（下钻透出）+ 018 资产反查一个小工具函数；约 3 个测试文件新增/扩展。零新集合、零新依赖、零既有契约破坏。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ spec/plan/tasks 三件套先行；五项已定决策（埋点位置/空间口径/业务线口径/计价口径/占位规则）在 Phase 0 前拍板，任务按 FR 收敛。
- **II. Enterprise Production Readiness**: ✅ 补的是"已写好零调用方"的库函数与"缺字段"的数据源，失败路径明确（空维度显式标注、查询按租户隔离、对账自检保持绿）；聚合走既有 24h 窗口与预取范式，无新增性能风险面。
- **III. Security and Data Protection**: ✅ 成本数据按租户隔离（403 不越权，FR-011）；新增字段不含敏感内容（ID 类标识）；下钻详情沿用既有脱敏/权限裁剪口径（008 FR-10 的 PII 脱敏展示不因新字段回退）。
- **IV. Cross-Platform and i18n**: ✅ 无新增用户可见文案刚需（维度段结构字段与 `reason` 为运营向说明，中文口径随 008 既有 i18n 机制）；`workspace_id` 口径与 017/021 既有空间语义同源，不发明平行概念。
- **V. Observability and Simplicity**: ✅ 不新增架构复杂度：三个字段 + 一处记录构造读取 + 一处聚合改造 + 一处下钻透出；库函数是既有 pure 函数的接线（YAGNI——不建新聚合框架、不做实时流、不实现配额）。

## Project Structure

### Documentation (this feature)

```text
specs/035-cost-attribution/
├── spec.md              # 特性规约（本计划引用的 spec）
├── plan.md              # 本文件
└── tasks.md             # 任务清单（全新特性，全部未勾选）
```

### Source Code (repository root)

```text
services/chat-api/
├── app/token_usage/models.py           # 【改动】TokenUsageRecord 新增 agent_id / skill_id / workspace_id（默认空串）
├── app/llm/instrumented_client.py      # 【改动】_submit_record 记录构造处读 output_spec.agent_id/skill_id/workspace_id（回退 project_id）
├── app/llm/factory.py                  # 【复用】get_llm_client 的 output_spec 合并（L72-76）已含请求上下文——零改动，仅确认键流通
├── app/infrastructure/request_context.py  # 【复用】get_request_context 机制——零改动
├── app/enterprise_capabilities/runtime/adapters.py  # 【改动，按需】Agent 执行处 merge agent_id/skill_id 到请求上下文（T005 勘察后定点）
└── tests/llm/test_instrumented_client_agent_dims.py  # 【新增】埋点三场景（传入/不传/DAG 多节点归并）

services/admin-api/
├── app/api/routes/dashboard.py         # 【改动】_cost_section 六维化：接 attribute_cost（部门/业务线/空间）+ agent 维聚合；诚实占位按维度 available/reason
├── app/api/dashboard_metrics.py        # 【复用】attribute_cost / reconciles / COST_TOLERANCE——零改动（pure 函数契约不变）
├── app/api/routes/analytics.py         # 【改动】token-usage 列表行 + 详情透出 costUsd（埋点优先/定价兜底），详情补 modelName 等既有字段
├── app/api/dashboard_usage.py          # 【复用】cost_estimate_usd 汇总口径参照（L55）——零改动
└── tests/test_dashboard_routes.py      # 【改动】_cost_section 六维 + 空维度不伪造 + reconciles 用例（更新 149-193 既有断言场景）

docs/MOGO-AgentOS整合方案.md             # 【不在本特性更新】§4.4 的对照结论随本特性落地由仓库维护流程处理
specs/INDEX.md                          # 【不在本特性更新】按任务约束保持原状
```

**Structure Decision**: 复用既有 monorepo 双服务布局与 008 的"预取行 + pure 函数分桶"聚合范式（`dashboard_usage.py` 已确立），不新增子项目、不新增集合、不新增依赖。埋点走既有 `output_spec`/请求上下文管道（`factory.py:72-76` 已合并上下文），不为归因新建传递机制；admin-api 侧 agent 维聚合按 `metering.aggregate_usage` 的同口径实现或共享（两服务同仓，Chat-api 纯函数可参照移植，避免 admin-api 反向依赖 chat-api 运行态）。

## Complexity Tracking

> 无 constitution 违规，无需复杂度论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |
