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
- 成本预测 → 基于近 N 期趋势
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
- FR-2: 成本看板展示 Token 总量、模型占比、部门/智能体分摊、成本预测
- FR-3: 使用看板展示调用量、活跃用户、Skill/检索频次，支持时间筛选
- FR-4: 质量看板展示成功率、响应时长 P50/P95、异常率、人工介入率
- FR-5: 趋势看板展示环比/同比、瓶颈识别（成本/时长 top）
- FR-6: 成本按调用记录聚合，合计与总量一致
- FR-7: 数据按租户隔离，访问受管理员权限约束
- FR-8: 数据源与特性 007 计量上报、analytics token-usage 端点对齐
- FR-9: 空租户返回 0 指标与空态引导
- FR-10: 异常可下钻到具体请求（定位）

## Non-Goals
- 不实现实时流式监控（本期为周期性聚合）
- 不实现跨租户成本对比（数据隔离）
- 不实现告警推送（告警属独立能力）
- 不改变既有 dashboard/analytics 端点的返回契约（向后兼容扩展）
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
