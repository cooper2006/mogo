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

## Open Questions
- OQ-1: 质量维度（成功率/异常率/人工介入率）的"人工介入"判定标准（是否=审批挂起数，需 clarify）
- OQ-2: 响应时长 P50/P95 是否从 token_usage_logs 的 duration_ms 聚合（现状 `_duration_ms` 已有）
- OQ-3: 趋势"瓶颈识别"是 top-N 成本/时长排序，还是需要统计显著性（首期建议简单 top-N）
- OQ-4: 前端四维是否统一在 DashboardPage 还是独立运营驾驶舱页（spec 写"扩展运营驾驶舱"，倾向独立页）

## 下一步
`/speckit-clarify` 消解 OQ → 补 research/data-model/contracts/quickstart → checklist → tasks → analyze → implement → converge。
