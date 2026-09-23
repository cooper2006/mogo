# Quickstart: Operations Data Dashboard (008)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [contracts/dashboard.md](./contracts/dashboard.md)

本文件说明如何**启用并验证**运营驾驶舱。

---

## 1. 前置

- admin-api 服务运行中
- MongoDB 有 `token_usage_logs` 数据（chat-api 计量写入）
- 前端 `apps/admin-web` 可构建（pnpm）

---

## 2. 后端接口

```python
from app.api.dashboard_metrics import (
    build_cost_section, reconciles, attribute_cost, forecast_cost,
    build_quality_section, build_trend_section, bottleneck_top_n,
)

# 成本维度
section = build_cost_section([
    {"model": "gpt-5.2", "calls": 10, "prompt_tokens": 8000,
     "completion_tokens": 4345, "cost": 1.2345},
])
assert reconciles(section)                       # 对账 0 差异

# 质量维度（空租户返回 None 而非 0）
quality = build_quality_section(
    total_calls=100, failed_calls=10, anomaly_calls=15,
    approval_pending=5, p50_ms=120, p95_ms=890, avg_ms=200,
)

# 趋势维度
trend = build_trend_section(current_cost=120.0, previous_cost=100.0,
                            current_calls=220, previous_calls=200)
trend["bottlenecks"] = bottleneck_top_n(rows, dimension="model")
```

`GET /api/dashboard/overview` 返回 `quality` + `trend` 两节。

---

## 3. 验证清单

| # | 验证项 | 期望 |
|---|---|---|
| 1 | overview 返回完整性 | billing/metrics/assets/quality/trend/todos/recentActivity 齐全 |
| 2 | 空租户 | 各指标 0 或 null（不报错） |
| 3 | 成本对账 | `sum(models.cost) == totalCost`（0 差异） |
| 4 | 质量分位 | P50/P95 由 duration 计算得出 |
| 5 | 人工介入率 | = approval_pending / 总调用 |
| 6 | 瓶颈 top-5 | 按成本降序，标注模型维度 |
| 7 | 租户隔离 | 查询 match 含 `main_id` + 时间窗口 |

---

## 4. 单元测试（无需 DB）

```bash
cd services/admin-api
PYTHONPATH=. python -m pytest \
  tests/test_dashboard_metrics.py tests/test_dashboard_routes.py \
  -o asyncio_mode=auto -q
```

期望：**30 项全部通过**（24 metrics + 6 routes；含成本对账、空租户、趋势、质量、瓶颈排序、审批降级）。

---

## 5. 前端

在 `apps/admin-web/src/views/dashboard/DashboardPage.vue` 新增"运营驾驶舱"标签页，消费 `/api/dashboard/overview` 的 `quality`/`trend` 字段与新增端点；文案 key 加在 `dashboardText.ts`。

---

## 6. 说明

- P50/P95 用 Mongo `$percentile`；老版本不可用时降级为仅平均值
- 人工介入率的持久数据源在 001/004 审批；当前无持久集合时优雅降级为 0
- 时间窗口一律 UTC
