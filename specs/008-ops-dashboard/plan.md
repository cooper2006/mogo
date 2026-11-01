# Implementation Plan: Operations Data Dashboard (Four-Dimension)

**Branch**: `008-ops-dashboard` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 缺口新特性。在既有 `admin-api/dashboard` + `analytics` 之上扩展四维看板（成本/使用/质量/趋势），复用现有聚合端点与 token_usage 数据源。

## Summary

现状 `dashboard.py` 已有 `_billing`（成本/billing）、`_usage_metrics`（使用）、`_assets`（资产）、`_todos`、`_format_recent_activity`；`analytics.py` 已有 `/token-usage`（含 groupBy + 部门/模型/stage 筛选）与详情端点。本特性补齐"质量"（成功率/响应时长 P50/P95/异常率/人工介入率）与"趋势"（环比同比/瓶颈识别）两个缺失维度，并把四维统一到前端 DashboardPage。

## Technical Context

**Language/Version**: Python 3.13（admin-api）+ TypeScript/Vue（admin-web）

**Primary Dependencies**: MongoDB 聚合管道 + 既有 token_usage_logs / 运行状态集合 + 前端既有图表组件

**Storage**: 复用 token_usage_logs + 运行状态数据（无新增表，趋势用聚合计算）

**Testing**: pytest（聚合查询单测 + P50/P95 计算单测 + 前端看板渲染测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 既有模块扩展 + 前端看板

## 现有实现事实（contract 依据）

- `admin-api/api/routes/dashboard.py`：`_cost`（按 MODEL_PRICES 计算 token 成本）、`_billing`、`_usage_metrics`、`_assets`、`_todos`、`_format_recent_activity`、`GET /overview`
- `admin-api/api/routes/analytics.py`：`GET /token-usage`（groupBy=user_request + 部门/模型/stage 筛选 + offset/limit）、`GET /token-usage/{request_id}`、`/chat-history`
- 前端：`apps/admin-web/src/views/dashboard/DashboardPage.vue` + `views/analytics/AnalyticsPage.vue`

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：可观测维度补全 |
| III. Security | 通过：数据按租户隔离 + 管理员权限 |
| IV. i18n | 通过：看板文案本地化 |
| V. Observability | 通过：本特性即生产可观测刚需 |

## Project Structure

```text
services/admin-api/app/api/routes/
├── dashboard.py       # 既有 overview + 新增质量/趋势聚合
└── analytics.py       # 既有 token-usage + 新增质量指标聚合
apps/admin-web/src/views/dashboard/
├── DashboardPage.vue  # 既有 + 扩展四维看板
└── (新增 quality/trend 子组件)
```

## Open Questions（已 clarify 消解）
- OQ-1 人工介入率：**= 需人工审批调用数/总调用数**；`approval_pending` 复用 001/004 审批机制（`approval_events`）。
- OQ-2 P50/P95 数据源：**从 `token_usage_logs.duration_ms` 聚合**（`_duration_ms` 已实现，用 Mongo `$percentile`）。
- OQ-3 瓶颈识别：**首期简单 top-N（按成本/时长排序 top 5），不做统计显著性**。
- OQ-4 前端组织：**在既有 `DashboardPage.vue` 内新增"运营驾驶舱"标签页（非独立路由），复用既有框架与本地化**。

## 下一步
OQ 已 clarify 消解。`/speckit-checklist`（008 补需求质量门禁）→ `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement` → `/speckit-converge`。
