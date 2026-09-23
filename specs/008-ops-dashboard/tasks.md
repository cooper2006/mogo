# Tasks: Operations Data Dashboard (Four-Dimension)

**Input**: Design documents from `/specs/008-ops-dashboard/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- 人工介入率 = 需人工审批调用数 / 总调用数（`approval_pending`，复用 001/004 审批机制 `approval_events`）。
- P50/P95 从 `token_usage_logs.duration_ms` 聚合（Mongo `$percentile`）。
- 瓶颈识别 = 首期 top-N（按成本/时长排序 top 5，标注维度），不做统计显著性。
- 前端：在既有 `apps/admin-web/src/views/dashboard/DashboardPage.vue` 内新增"运营驾驶舱"标签页（非独立路由），复用既有框架 + 本地化。
- 成本预测 N = 4 期（可配置 `forecast_periods`）。

**Checklist Gate**: `checklists/requirements.md` 未勾选项构成 `/speckit-implement` 拦截门禁；本任务文件仅规划，不修改 checklist 标记。

**Organization**: 任务按用户故事分组，每组可独立实现与测试；`[P]` 标记可并行任务。数据源以既有 `admin-api/dashboard.py` + `analytics.py` + `token_usage_logs` 为基础，前端扩 `DashboardPage.vue`。

---

## Phase 1: Setup (Data Source Alignment)

**Goal**: 对齐四维看板的数据源（聚合基座），为所有故事提供统一查询入口。

- [x] T001 梳理既有数据源：确认 `dashboard.py`（_billing/_usage_metrics/_assets/_todos/_recent_activity）与 `analytics.py`（/token-usage，含 groupBy + 部门/模型/stage 筛选 + `duration_ms`）已提供的指标
- [x] T002 建立四维看板共享的聚合辅助（`dashboard.py` 扩展）：统一租户隔离过滤 + 时间窗口（含时区口径）+ 空租户 0 指标兜底（FR-9）
- [ ] T003 前端驾驶舱标签页骨架（`DashboardPage.vue` 新增 tab + `dashboardText.ts` 文案 key），复用既有图表组件

---

## Phase 2: Foundational (Blocking Prerequisites)

**Goal**: 补齐各维度缺失的聚合能力（质量/趋势当前最缺）。

- [x] T004 [P] 质量维度聚合（`dashboard.py` 或 `analytics.py` 新增）：成功率（`successRate`）+ 响应时长 P50/P95（`$percentile` on `duration_ms`）+ 异常率（失败/超时占比）
- [x] T005 [P] 人工介入率聚合：`approval_pending`（审批挂起数）/ 总调用数（复用 001/004 审批事件）
- [x] T006 [P] 趋势维度聚合（`analytics.py` 新增）：环比/同比（按周期对比）+ 瓶颈 top-N（成本/时长排序 top 5，标注 模型/工具/阶段 维度）

---

## Phase 3: User Story 1 (P1) — 总览看板（overview）

**Goal**: 总览页返回 billing + usage_metrics + assets + todos + recent_activity。
**独立测试**: 打开 overview 返回五类数据；资产数量反映真实存量；空租户 0 指标 + 空态引导。

- [x] T007 完善 `GET /overview`（`dashboard.py`）：聚合五类数据 + 资产真实存量 + 最近活动按时间倒序
- [ ] T008 US1 前端：overview 标签页渲染五类指标 + 空态引导（复用 T002 兜底）
- [x] T009 US1 测试：overview 返回完整性 + 空租户 0 指标两组 Acceptance

---

## Phase 4: User Story 2 (P1) — 成本看板（维度①）

**Goal**: Token 总量（输入/输出分离）+ 模型占比 + 部门/智能体分摊 + 成本预测。
**独立测试**: 模型成本占比合计与总量一致；按部门/智能体可下钻；预测基于近 4 期。

- [x] T010 成本聚合（`dashboard.py::_cost` + 模型占比）：Token 总量 + 各模型成本占比（合计=总量，FR-6 对账）
- [x] T011 分摊维度：按部门/智能体分摊成本（下钻，FR-2），数据源 `token_usage_logs` + `USER_ORG_REL`/`DEPARTMENT`
- [x] T012 成本预测（近 4 期趋势，`forecast_periods` 可配，FR-2 + clarify OQ-5）
- [ ] T013 US2 前端 + 测试：成本标签页（饼图/列表 + 分摊下钻 + 预测）+ 合计对账 0 差异断言

---

## Phase 5: User Story 3 (P1) — 使用看板（维度②）

**Goal**: 调用量、活跃用户（去重）、Skill/检索频次，支持时间筛选。
**独立测试**: 调用量时间序列 + 总量；活跃用户按日/周/月去重；Skill/检索按名排名。

- [ ] T014 使用指标聚合（`dashboard.py::_usage_metrics` + `analytics.py`）：调用量时间序列 + 活跃用户去重计数（去重键 = user_id，按日/周/月）
- [ ] T015 Skill/检索频次（按 Skill 名/检索类型排名）
- [ ] T016 US3 前端 + 测试：使用标签页（时间范围筛选刷新 + 去重 + 排名）三组 Acceptance

---

## Phase 6: User Story 4 (P1) — 质量看板（维度③）

**Goal**: 成功率、响应时长 P50/P95、异常率、人工介入率；异常可定位到请求。
**独立测试**: 成功率=成功/总；P50/P95 分位；异常可下钻到请求；人工介入率=审批挂起/总。

- [ ] T017 质量看板聚合（复用 T004）：成功率 + P50/P95（`$percentile`）+ 异常率（失败/超时占比）
- [ ] T018 人工介入率（复用 T005）：`approval_pending`/总调用
- [ ] T019 异常下钻到具体请求（FR-10：定位到 request_id，含脱敏 payload）
- [ ] T020 US4 前端 + 测试：质量标签页（分位 + 异常下钻 + 人工介入率）四组 Acceptance

---

## Phase 7: User Story 5 (P2) — 趋势看板（维度④）

**Goal**: 环比/同比、瓶颈识别（成本/时长 top 调用），辅助决策。
**独立测试**: 环比/同比与上一周期对比；瓶颈 top 按成本/时长排序；趋势线可视化。

- [ ] T021 趋势聚合（复用 T006）：环比/同比（按周期粒度）+ 瓶颈 top-5（成本/时长排序，标注 模型/工具/阶段）
- [ ] T022 趋势线时间序列可视化数据接口
- [ ] T023 US5 前端 + 测试：趋势标签页（环比/同比 + 瓶颈 top + 趋势线）三组 Acceptance

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T024 [P] 租户隔离自检：四维看板数据 100% 按租户隔离，无越权（FR-7 + 管理员权限约束，与 006 RBAC 口径对齐）
- [ ] T025 [P] 空租户/空数据总兜底：各维度 0 指标 + 空态引导（FR-9）
- [ ] T026 成本对账自检：模型成本合计 = Token 总量（0 差异，FR-6/Success）
- [ ] T027 写 `quickstart.md`（驾驶舱启用 + 各维度验证步骤）+ `contracts/dashboard.md`（四维看板端点契约 + 聚合口径）

---

## Dependencies

```text
Phase 1 (数据源对齐) → Phase 2 (质量/趋势聚合补齐) → 各 US
Phase 2 (T004/T005/T006) → US4(T017-020)、US5(T021-023)
US1/US2/US3 依赖 Phase 1；US4/US5 依赖 Phase 2
US1-5 → Phase 8 (Polish)
关键依赖: T004/T005/T006 被 US4/US5 复用；T002 租户隔离兜底被所有故事复用
```

## Parallel Opportunities
- T004/T005/T006（Phase 2）互不依赖，可并行
- 各 US 内前端 + 聚合 + 测试任务可按故事独立推进
- US1/US2/US3 可并行（共用 Phase 1 基座）；US4/US5 依赖 Phase 2 后并行

## MVP Scope
- **最小可交付 = Phase 1 + Phase 2 + US1 + US4**（T001–T006、T007–T009、T017–T020）：总览 + 质量两个核心维度跑通（质量是当前最缺、P0 可观测刚需）。
- 增量交付：US2（成本）→ US3（使用）→ US5（趋势）。

## Implementation Strategy
- 先补数据源基座（Phase 1/2，尤其质量/趋势缺失维度），再逐故事填充前端标签页
- 每故事完成即独立可测（Acceptance Scenarios 即测试基准）
- 复用既有 `dashboard.py`/`analytics.py`/`token_usage_logs`，不重造轮子；前端集中在 `DashboardPage.vue` 标签页

## Notes
- 本 tasks.md 为 `/speckit-tasks` 产出，含 008 的 clarify 决策（人工介入率口径、P50/P95 数据源、瓶颈 top-N、N=4、DashboardPage 标签页）。
- 实现需先通过 `checklists/requirements.md` 门禁；CHK009（数据源字段口径）需与 007 spec 双向对齐。
- 未改 services/apps 源码；本文件仅在 `specs/008-ops-dashboard/` 下。
