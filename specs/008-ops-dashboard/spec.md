# Feature Specification: Operations Data Dashboard (Four-Dimension)

**Feature Branch**: `008-ops-dashboard`

**Created**: 2026-07-08

**Status**: Draft

**Input**: 补齐规划文档清单 3（P0）"总览数据统计驾驶舱"：四维看板 ①成本（Token 总量、各模型占比、部门/智能体分摊、预测）②使用（调用量、活跃用户、Skill/检索频次）③质量（成功率、响应时长、异常率、人工介入率）④趋势（环比同比、瓶颈识别）。在管理后台扩展"运营驾驶舱"，复用已有运行状态数据。

## User Scenarios & Testing *(mandatory)*

用户故事按优先级排列，每个独立可交付、可测试。

### User Story 1 (P1) — 总览看板（overview）

管理员打开管理后台总览页，看到当前租户的核心指标：资产概览（模型/知识/Skill/工具数量）、使用指标（调用量、活跃用户）、成本（billing）、待办事项（todos）、最近活动。

**Acceptance Scenarios:**
- 打开 overview → 返回 billing + usage_metrics + assets + todos + recent_activity
- 资产数量 → 反映当前租户模型/知识/Skill/工具真实存量
- 最近活动 → 按时间倒序，可追溯操作
- 空租户 → 指标 0、空态引导

### User Story 2 (P1) — 成本看板（维度①）

成本看板展示 Token 总量、各模型占比、部门/智能体分摊、成本预测；成本按调用记录聚合。

**Acceptance Scenarios:**
- 展示 Token 总用量（输入/输出分离）
- 各模型成本占比 → 饼图/列表，合计与总量一致
- 按部门/智能体分摊 → 可下钻
- 成本预测 → 基于近 N 期趋势（默认 N = 4 期，可配置）
- 数据源 → 与特性 007 计量上报、analytics token-usage 端点对齐

### User Story 3 (P1) — 使用看板（维度②）

使用看板展示调用量、活跃用户、Skill 调用频次、检索频次；支持时间范围筛选。

**Acceptance Scenarios:**
- 调用量 → 时间序列 + 总量
- 活跃用户 → 去重计数，按日/周/月
- Skill/检索频次 → 按 Skill 名/检索类型排名
- 时间范围筛选 → 数据随范围刷新

### User Story 4 (P1) — 质量看板（维度③）

质量看板展示成功率、响应时长（P50/P95）、异常率、人工介入率；异常可定位到具体调用。

**Acceptance Scenarios:**
- 成功率 = 成功调用/总调用
- 响应时长 → P50/P95 分位
- 异常率 → 失败/超时占比，可下钻到请求
- 人工介入率 → 需人工审批/纠正的调用占比

### User Story 5 (P2) — 趋势看板（维度④）

趋势看板展示环比/同比变化、瓶颈识别（哪类调用最耗成本/时长）；辅助决策。

**Acceptance Scenarios:**
- 环比/同比 → 与上一周期对比
- 瓶颈识别 → 按成本/时长排序的 top 调用
- 趋势线 → 时间序列可视化

### Notes / Assumptions
- 本特性补齐规划文档清单 3（P0 生产可观测刚需），属缺口新特性
- 现有基础：
  - `admin-api/api/routes/dashboard.py`（overview：_billing/_usage_metrics/_assets/_todos/_format_recent_activity）
  - `admin-api/api/routes/analytics.py`（_token_usage/_token_usage_detail/_session_chat_history）
  - `apps/admin-web/src/views/dashboard` + `analytics`（前端看板视图）
  - 成本计算：`dashboard.py::_cost(model_name, prompt_tokens, completion_tokens)`
- 与特性 007（网关韧性）的关系：007 的用量/成本计量上报是本特性数据源
- 与特性 006（RBAC）的关系：看板数据按租户隔离，访问受管理员权限约束
- 四维看板是否全部已有实现需 clarify（现状可能是部分维度缺失）

## Functional Requirements

- FR-1: 总览页展示 billing + usage_metrics + assets + todos + recent_activity
- FR-2: 成本看板展示 Token 总量（输入/输出分离）、各模型成本占比（**合计 = Token 总量，浮点容差 0.01**）、部门/智能体分摊（**部门维度取 `USER_ORG_REL`，智能体维度取 `agent_id`**）、成本预测（**近 4 期，`forecast_periods` 可配**）
- FR-3: 使用看板展示调用量、活跃用户（**去重键 = `user_id`，按日/周/月，跨租户分开去重**）、Skill/检索频次，支持时间筛选（**时区按 UTC，跨 0 点数据归入 UTC 当日**）
- FR-4: 质量看板展示成功率（**成功调用/总调用**）、响应时长 P50/P95（**取 `token_usage_logs.duration_ms`，Mongo `$percentile` 聚合**）、异常率（**异常 = 失败 + 超时 + 限流 合并计**）、人工介入率（**= `approval_pending`/总调用，复用 001/004 审批事件**）
- FR-5: 趋势看板展示环比/同比（**周期粒度 = 日环比 + 周同比，`period` 可配**）、瓶颈识别（**首期 top-5，按成本/时长排序，标注 模型/工具/阶段 维度**）
- FR-6: 成本按调用记录聚合，合计与总量一致（**浮点容差 0.01，对账 0 差异**）
- FR-7: 数据按租户隔离，访问受管理员权限约束（**最小角色 = 006 的"全能力管理员"，与 006 RBAC 口径对齐**）
- FR-8: 数据源与特性 007 计量上报、analytics token-usage 端点对齐；**008 声明 007 写入 `token_usage_logs` 的韧性字段：`failover_from`/`failover_to`/`degradation_step`（质量看板按降档/切换归因）**
- FR-9: 空租户返回 0 指标与空态引导（**分维度空态：成本/使用/质量/趋势各自独立空态文案**）
- FR-10: 异常可下钻到具体请求（**定位到 `request_id`，含脱敏 payload——PII 按 001 策略脱敏后展示**）

## Non-Goals
- 不实现实时流式监控（本期为周期性聚合）
- 不实现跨租户成本对比（数据隔离）
- 不实现告警推送（告警属独立能力）
- 不改变既有 dashboard/analytics 端点的返回契约（向后兼容扩展）；**新增运营驾驶舱维度 = 新增端点（既有端点契约不变，新标签页消费新端点）**
- 不实现数据导出（Excel/PDF 导出）

## Success Criteria
- 四维看板（成本/使用/质量/趋势）数据 100% 可查
- 成本合计与 Token 总量一致（无对账差异）
- 租户隔离 100% 无越权数据
- 空租户 0 指标无报错
- 异常 100% 可下钻到请求

## Further Details
- 技术实现（聚合查询、分位计算、前端图表组件）由 plan.md 承载
- 与特性 007（网关韧性）的关系：计量数据源
- 现状哪些维度已实现需 clarify 后在 plan 中登记

## Clarify 记录（/speckit-clarify，2026-07-08）

### OQ-1 "人工介入率"判定标准（spec 原 OQ-1）
- **决策**：人工介入率 = 需人工审批的调用数 / 总调用数。
- **依据**：`dashboard.py::_usage_metrics` 已有 `successRate24h`（成功率）；人工介入以 `approval_pending`（审批挂起）计——复用 001/004 的审批机制（`enterprise_capabilities/tools/approval_events`）。
- **影响**：质量看板"人工介入率"取 `pending_approval_count / total_calls`。

### OQ-2 响应时长 P50/P95 数据源（spec 原 OQ-2）
- **决策**：从 `token_usage_logs` 的 `duration_ms` 聚合。
- **依据**：`dashboard.py::_duration_ms(row)` 已实现（读 `row["duration_ms"]`），`analytics.py` 已按 `duration_ms` 排序。直接 Mongo 聚合 `$percentile`。
- **影响**：质量看板 P50/P95 = `db.token_usage_logs.aggregate({$percentile: {durationMs: 50/95}})`。

### OQ-3 "瓶颈识别"算法（spec 原 OQ-3）
- **决策**：首期用简单 top-N（按 成本/时长 排序 top 5 调用），不做统计显著性检验。
- **影响**：趋势看板"瓶颈"= top-N 列表，标注维度（模型/工具/阶段）。

### OQ-4 前端页面组织（spec 原 OQ-4）
- **决策**：在既有 `apps/admin-web/src/views/dashboard/DashboardPage.vue` 内新增"运营驾驶舱"标签页（非独立路由页），复用既有 DashboardPage 框架与本地化。
- **影响**：前端改动集中在 DashboardPage.vue + dashboardText.ts 新增文案 key。

### OQ-5 成本预测周期 N（checklist CHK013 补齐，2026-07-08）
- **决策**：成本预测基于**近 4 期**（N = 4，可配置 `forecast_periods`）。
- **依据**：4 期足以捕捉周/月趋势且不过长引入陈旧数据；与趋势看板"环比/同比"窗口对齐。

