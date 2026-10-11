# Implementation Plan: Performance & Scalability Hardening

**Branch**: `026-performance-scalability` | **Date**: 2026-10-11 | **Spec**: [spec.md](./spec.md)

**Input**: 缺口新特性。QualityForge 审计发现 51 个 P0/P1 缺陷（全部 `blocked`），需建立性能基线与优化能力方能解除。技术化到既有基础设施：`infrastructure/observability`（kpi_store/spans/execution_trace）+ `core/db.py`（motor）+ Redis（session_affinity/runtime_lock 已用）+ `apps/admin-web` + `apps/user-web`（Vue3/Vite）+ `benchmarks/`（新增）。

## Summary

建立**度量→分析→优化→验证**闭环：

1. **度量**（US1）：埋点采集 → 基线落库 → 预算定义 → CI 回归检查
2. **分析**（US1 + US2 + US3）：慢查询识别、N+1 定位、缓存命中率分析、外部依赖耗时占比
3. **优化**（US2 + US3 + US4）：DB 索引/超时/连接池 + Redis 缓存/防护/失效 + 前端分包/压缩/虚拟列表
4. **验证**（US5）：水平扩展压测 + 容量模型 + 瓶颈识别 → 闭环回度量

改动集中在**既有模块的扩展**（observability/db/Redis）与**新增 benchmarks/** 目录，不改变业务逻辑、不拆微服务、不引入新中间件。

## Technical Context

**Language/Version**: Python 3.13（chat-api/admin-api/document-parser 既有栈）+ TypeScript 5.x（Vue3 前端）

**Primary Dependencies**:
- 既有：`motor`（MongoDB 异步驱动）、`redis`（Redis 客户端）、`tenacity`（已有，不新增）
- 新增：`locust>=2.20`（压测主工具）、`k6`（CLI，补充）；前端 `web-vitals` + `vue-virtual-scroller`
- 监控：`prometheus_client`（metrics exporter）

**Storage**:
- 复用 MongoDB：新增 `perf_baselines` / `slow_queries` / `query_plans` / `perf_budgets` / `perf_metrics` collections
- 复用 Redis：新增缓存层（`app/cache/`），缓存热点数据（会话/配置/权限/token）

**Testing**:
- 后端：`pytest` + `pytest-asyncio`（既有）+ `locust` 压测
- 前端：`vitest`（既有）+ `lighthouse`（Web Vitals 自动检测）
- CI：性能预算检查脚本（GitHub Actions 或等价）

**Target Platform**: 自托管 Docker Compose（既有）+ K8s（后续，首期不启用）

**Project Type**: 既有模块扩展（observability/db/cache 增强）+ 新增 benchmarks/ + 前端性能改造

## 现有实现事实（contract 依据）

- `services/chat-api/app/infrastructure/observability/kpi_store.py`：`RuntimeKPIStore` 已有计数器骨架（`checkpoint_resume_success_rate` / `mean_steps_to_success` 等），**无延迟分位数**
- `services/chat-api/app/infrastructure/observability/spans.py`：已有 span 记录，**无端点级延迟分位聚合**
- `services/chat-api/app/infrastructure/observability/execution_trace.py`：已有执行追踪，**无外部依赖耗时拆分**
- `services/chat-api/app/core/db.py`：`AsyncIOMotorClient` 已配置 `server_selection_timeout_ms` / `connect_timeout_ms` / `socket_timeout_ms`，**无 maxPoolSize / minPoolSize / maxIdleTimeMS / maxTimeMS / slow_query_log**
- `services/chat-api/app/dsh_runtime/session_affinity.py`：Redis 已用于会话亲和（`SET key value ex ttl`），**无缓存层抽象**
- `services/chat-api/app/dsh_runtime/runtime_lock.py`：Redis 已用于分布式锁（`SET NX EX` + Lua 释放），**可作为缓存击穿互斥锁参考**
- `services/chat-api/app/llm/instrumented_client.py`：LLM 调用已有计量（token/成本），**无耗时占比拆分**
- `apps/admin-web/` + `apps/user-web/`：Vue3 + Vite，**无代码分割配置 / 无虚拟列表 / 无 Web Vitals 埋点**
- `deploy/` + `docker-compose.yml`：Docker Compose 部署，**无 Prometheus / 无 CDN 配置**
- **无 `benchmarks/` 目录**（需新增）

## Architecture: 度量→分析→优化→验证闭环

```text
┌─────────────────────────────────────────────────────────────────┐
│                         度量 (US1)                                │
│  埋点 (spans/trace) → 基线采集 (perf_baselines) → 预算定义        │
│  (performance.yaml) → CI 回归检查                                │
└──────────────────────────┬──────────────────────────────────────┘
                           │ 基线数据
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                         分析 (US1+2+3)                           │
│  慢查询识别 (slow_query_log) · N+1 定位 (explain)                 │
│  缓存命中率分析 · 外部依赖耗时占比 (DB/Redis/LLM/外部 API)        │
└──────────────────────────┬──────────────────────────────────────┘
                           │ 瓶颈定位
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                         优化 (US2+3+4)                           │
│  DB: 索引 / maxTimeMS / 连接池 / bulk_write / N+1 改造            │
│  Cache: Redis 热点 / TTL / 穿透击穿雪崩防护 / 记忆化               │
│  Frontend: 分包 / 压缩 / 图片 / 虚拟列表 / API 优化                │
└──────────────────────────┬──────────────────────────────────────┘
                           │ 优化后
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                         验证 (US5)                               │
│  水平扩展压测 (locust/k6) · 容量模型 · 瓶颈报告 → 回度量基线       │
└─────────────────────────────────────────────────────────────────┘
```

**闭环机制**：优化完成后重新采集基线 → 与历史基线对比 → 回归判定（US1 FR-5）→ CI 检查生效。

## Project Structure

```text
mogo/
├── services/chat-api/app/
│   ├── core/db.py                # 既有：扩展连接池配置 + maxTimeMS + slow_query_log
│   ├── cache/                    # 新增：缓存层抽象
│   │   ├── __init__.py
│   │   ├── manager.py            # 缓存管理器（get/set/delete/lock/bloom）
│   │   ├── policies.py           # 失效策略（TTL/事件驱动/版本戳）
│   │   ├── protection.py         # 穿透/击穿/雪崩防护
│   │   └── memoize.py            # @cache_result 记忆化装饰器
│   ├── infrastructure/
│   │   └── observability/
│   │       ├── kpi_store.py      # 既有：扩展延迟分位数（P50/P95/P99）
│   │       ├── spans.py          # 既有：扩展端点级聚合
│   │       ├── execution_trace.py # 既有：扩展外部依赖耗时拆分
│   │       ├── perf_budget.py    # 新增：性能预算检查
│   │       ├── perf_baseline.py  # 新增：基线采集与回归判定
│   │       └── prometheus.py     # 新增：Prometheus exporter (/metrics)
│   └── api/middleware/perf.py    # 新增：性能中间件（延迟埋点）
├── services/admin-api/app/
│   └── api/middleware/perf.py    # 新增：同上（admin-api 也需埋点）
├── services/document-parser/app/
│   └── api/middleware/perf.py    # 新增：同上（document-parser 也需埋点）
├── apps/admin-web/
│   └── src/
│       ├── router/index.ts       # 既有：扩展路由级懒加载
│       ├── plugins/vitals.ts     # 新增：Web Vitals 埋点
│       └── composables/virtual.ts # 新增：虚拟列表 composable
├── apps/user-web/
│   └── src/
│       ├── router/index.ts       # 既有：扩展路由级懒加载
│       ├── plugins/vitals.ts     # 新增：Web Vitals 埋点
│       └── composables/virtual.ts # 新增：虚拟列表 composable
├── benchmarks/                   # 新增：压测与基线
│   ├── locust/
│   │   ├── locustfile_chat.py    # 对话场景
│   │   ├── locustfile_doc.py     # 文档解析场景
│   │   ├── locustfile_search.py  # 搜索场景
│   │   └── locustfile_auth.py    # 鉴权场景
│   ├── k6/
│   │   └── smoke.js              # 冒烟测试
│   ├── perf_baselines/           # 基线数据（YAML/JSON）
│   │   └── baselines.yaml        # 首次基线（US1 产出）
│   └── capacity_model.md         # 容量模型（US5 产出）
├── deploy/
│   └── prometheus.yaml           # 新增：Prometheus 配置（可选）
└── specs/026-performance-scalability/
    ├── spec.md
    ├── plan.md                   # 本文件
    ├── tasks.md
    └── quickstart.md
```

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：性能基线与优化是生产可用性直接收益，QualityForge 51 个 P0/P1 `blocked` 项的解除条件 |
| III. Security | 通过：不引入新中间件，不暴露新攻击面；缓存穿透/击穿防护本身是安全收益 |
| IV. i18n | 通过：不改变用户可见文案 |
| V. Observability | 通过：度量→分析→优化→验证闭环本身就是可观测性增强 |

## Open Questions（需 /speckit-clarify）

- **OQ-1 性能预算阈值**：关键端点 P95 预算（如 对话 ≤ 2s、文档解析 ≤ 5s、鉴权 ≤ 500ms）、前端包体积预算（admin-web ≤ 500KB / user-web ≤ 300KB gzip）、缓存命中率目标（80%？）、并发上限（1000 rps/实例？）——**需按实际负载场景定值**
- **OQ-2 慢查询阈值**：MongoDB `slow_query_log` 阈值默认 100ms，是否合适？按端点差异化阈值（如文档解析可放宽到 500ms）？
- **OQ-3 压测工具选择**：locust（Python 生态一致，首选）vs k6（JS 脚本更灵活，补充）——**两者都做，locust 为主**
- **OQ-4 虚拟列表库**：`vue-virtual-scroller` vs `@vueuse/virtual` vs 自实现——**需评估**
- **OQ-5 前端包体积预算**：admin-web ≤ 500KB / user-web ≤ 300KB gzip 是否合理？需基线采集后确认

## 与现有特性关系

- **与 001（gatekeeper）**：审计联动——001 的治理门禁（配额/凭据/审计）与 026 的性能门禁（基线/预算/回归）互补；001 管"谁能访问"，026 管"多快能访问"
- **与 007（llm-gateway）**：LLM 调用优化联动——007 的韧性（failover/降级/退避）影响 LLM 耗时，026 度量 LLM 耗时占比并与 007 韧性事件交叉归因
- **与 008（ops-dashboard）**：026 的基线/压测/容量/命中率数据供 008 消费可视化

## 实施顺序

**US1（基线）→ US2（DB）→ US3（缓存）→ US4（前端）→ US5（扩展性）**

US1 是其他故事的前置条件：无基线则无从度量优化收益、无从判定回归。

## 下一步

OQ 需 `/speckit-clarify` 定值。`/speckit-checklist`（026 需求质量门禁）→ `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement` → `/speckit-converge`。
