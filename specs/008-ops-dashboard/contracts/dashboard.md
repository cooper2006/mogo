# Contract: Operations Data Dashboard (008)

**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [tasks.md](../tasks.md)

本契约定义运营驾驶舱四维看板的聚合口径与端点契约。实现见 `services/admin-api/app/api/dashboard_metrics.py` + `api/routes/dashboard.py`。

---

## 1. 共享口径

| 项 | 口径 |
|---|---|
| 租户隔离 | 所有查询按 `main_id` 过滤（FR-7） |
| 时间窗口 | **UTC**；跨 0 点数据归 UTC 当日 |
| 空租户 | 各指标返回 `0` / `null`，**不报错**（FR-9） |
| 数据源 | `token_usage_logs`（`start_time`/`end_time` 为 epoch ms） |

---

## 2. 四维指标契约

### 维度①成本（US2）

```json
{
  "totalTokens": 12345, "promptTokens": 8000, "completionTokens": 4345,
  "totalCost": 1.2345,
  "models": [
    {"model":"gpt-5.2","calls":10,"tokens":5000,"cost":1.0,"costShare":0.81}
  ]
}
```

- 模型占比按成本降序；`costShare = 该模型成本 / 总成本`
- **对账**：`sum(models[].cost) == totalCost`（容差 0.01，FR-6）
- 分摊：`attribute_cost(rows, dimension, dimension_of)` 按部门/智能体，无值归 `未分配`
- 预测：`forecast_cost(history, periods=4)` 近 N 期移动平均（clarify OQ-5）

### 维度②使用（US3）

调用量时间序列 + 活跃用户（**去重键 = `user_id`**，按日/周/月）+ Skill/检索频次排名。

### 维度③质量（US4）

```json
{
  "totalCalls": 100, "successRate": 90.0, "anomalyRate": 15.0,
  "manualInterventionRate": 5.0, "p50Ms": 120, "p95Ms": 890, "avgMs": 200
}
```

- 成功率 = 成功调用 / 总调用
- **异常 = `failed` + `timeout` + `error` 合并计**
- **人工介入率 = `approval_pending` / 总调用**
- P50/P95 从 `start_time`/`end_time` 内联计算 duration 后取 Mongo `$percentile`
- **空租户返回 `null`（非 0）**，避免误导

### 维度④趋势（US5）

```json
{
  "costMomPct": 20.0, "callsMomPct": 10.0, "costYoyPct": 50.0,
  "bottlenecks": [{"dimension":"model","key":"gpt-5.4","calls":10,"cost":9.0,"avgDurationMs":100}]
}
```

- 环比（Mom）/ 同比（YoY）；基线为 0 时返回 `null`
- 瓶颈 = **top-5**（按成本排序，tie 按时长），标注维度

---

## 3. 端点契约

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/dashboard/overview` | GET | 聚合 billing + metrics + assets + **quality** + **trend** + todos + recentActivity |
| `/api/analytics/token-usage` | GET | 明细（groupBy + 筛选 + `duration_ms`） |
| `/api/analytics/token-usage/{request_id}` | GET | **异常下钻到请求**（含脱敏 payload，FR-10） |

**契约边界**：新增运营驾驶舱维度 = **新增端点**，既有 `/overview` 端点仅**增量加字段**（`quality`/`trend`），不破坏旧字段。

---

## 4. 前端契约

- 在既有 `apps/admin-web/src/views/dashboard/DashboardPage.vue` **新增标签页**（非独立路由）
- 复用既有图表组件 + `dashboardText.ts` 文案 key

---

## 5. 访问控制

- 最小角色 = 006 的**全能力管理员**（`full_access_admin`）
- 数据 100% 按租户隔离
