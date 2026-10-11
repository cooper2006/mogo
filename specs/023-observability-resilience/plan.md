# Implementation Plan: Observability & Resilience Hardening

**Branch**: `023-observability-resilience` | **Date**: 2026-10-11 | **Spec**: [spec.md](./spec.md)

**Input**: QualityForge 审计（74 个 P0/P1 缺陷）→ 从零建立生产级可观测性与韧性基础设施。改动跨越 3 个 Python 服务 + 部署编排 + 文档，属于基础设施级建设。

## Summary

在 MOVO 平台建立**可观测性四信号（日志/追踪/指标/告警）+ 容错弹性 + 恢复灾备**三位一体的基础设施：

- **日志**：structlog 输出 JSON 结构化日志到 stdout，字段稳定，含 trace_id/span_id/tenant_id/user_id
- **追踪**：OpenTelemetry SDK 实现 W3C traceparent 跨服务传播，asyncio/后台任务保留上下文
- **指标**：Prometheus client 暴露黄金四信号 + 业务指标，维度基数受控，SLO 定义 + 错误预算
- **告警**：Alertmanager + IM webhook + Grafana 排障看板 + Runbook 排障手册
- **容错**：熔断器（半开策略）+ 超时层级递减 + 重试退避（与 007 对齐）+ 资源池隔离 + 背压限流
- **恢复**：MongoDB 自动备份 + 加密 + 保留策略 + 跨 AZ 部署 + 故障转移 + RTO/RPO 实测

改动跨 `services/admin-api`、`services/chat-api`、`services/document-parser`、`deploy/`、`docs/runbooks/`、`scripts/`，影响面大但分层清晰（基础设施层 vs 业务层分离）。

## Technical Context

**Language/Version**: Python 3.13（三个服务统一）；TypeScript（前端埋点可选）

**Primary Dependencies**（新增）:
- `structlog>=24.1.0` — 结构化日志
- `opentelemetry-api>=1.25.0` / `opentelemetry-sdk>=1.25.0` / `opentelemetry-exporter-otlp>=1.25.0` — 分布式追踪
- `prometheus-client>=0.20.0` — 指标暴露
- `pybreaker>=1.1.0`（或复用 `tenacity` 熔断能力）— 熔断器
- `tenacity>=8.3.0`（既有依赖，007 已用）— 重试
- `httpx`（既有依赖）— HTTP client 重试/超时配置

**Existing Dependencies**（复用）:
- `fastapi` / `uvicorn` — 三个服务统一
- `pymongo` — MongoDB 客户端（需增加熔断包装）
- `redis` — Redis 客户端（需增加熔断包装）
- `tenacity` — 重试（007 已用）
- `bson` / `motor` — MongoDB 异步驱动

**Observability Stack**（开源，新增 Docker Compose 服务）:
- **Prometheus**（指标抓取与存储）
- **Grafana**（可视化 + 排障看板 + SLO 面板）
- **Alertmanager**（告警路由/分组/静默/抑制）
- **OpenTelemetry Collector**（追踪与日志聚合转发）
- **Jaeger** 或 **Grafana Tempo**（追踪存储与查询，二选一，待定 OQ-2）
- **Loki**（日志存储与查询，可选，若平台已有 Loki/ELK 则复用）
- **MinIO** 或对象存储客户端（备份异地存储，OQ-4 待定）

**Storage**:
- Prometheus TSDB（本地磁盘，15 天保留）
- Loki 对象存储（可选，30 天保留）
- Jaeger/Tempo（追踪存储，7 天保留）
- MongoDB（业务数据 + 备份）
- 对象存储（备份异地存储）

**Testing**:
- pytest（单测 + 集成测试）
- `pytest-asyncio`（异步测试）
- `responses` / `aioresponses`（HTTP mock）
- 故障注入脚本（`scripts/chaos/`）

**Target Platform**: 自托管 Docker Compose（首期），云原生 K8s 后续演进

**Project Type**: 基础设施级新特性（跨服务 + 部署编排 + 文档）

## Architecture

### 日志架构

```
[Python 服务] → structlog (JSON to stdout)
       ↓
[Docker 容器 stdout]
       ↓
[Filebeat / Vector] → [Loki / Elasticsearch] → [Grafana 日志面板]
```

- 日志级别运行时可调（通过 `/admin/log-level` 端点或环境变量热更新）
- 日志字段稳定：`ts` / `level` / `service` / `message` / `trace_id` / `span_id` / `tenant_id` / `user_id`
- ERROR 级日志含完整堆栈、请求路径、用户标识

### 指标架构

```
[Python 服务] → /metrics (Prometheus 格式)
       ↓
[Prometheus scrape] → [Prometheus TSDB] → [Grafana 指标面板]
       ↓
[Alertmanager] → [IM webhook / 邮件]
```

- 黄金四信号：延迟（histogram）/ 流量（counter）/ 错误率（counter）/ 饱和度（gauge）
- 业务指标：会话数、消息数、LLM 调用数、token 用量、文档解析数
- SLO 定义（Prometheus recording rule）+ 错误预算
- 维度基数受控（label 白名单 + 高基数字段哈希化）

### 追踪架构

```
[Python 服务] → OpenTelemetry SDK → OTLP Exporter
       ↓
[OpenTelemetry Collector] → [Jaeger / Tempo]
       ↓
[Grafana 追踪面板]
```

- 入口生成 trace_id，透传到所有下游调用
- 日志含 trace_id，可跳转追踪
- 异步任务保留上下文
- 采样率可配（生产 10%，调试 100%）

### 容错架构

```
[上游服务] → [熔断器] → [下游依赖]
                ↓
        [超时层级递减]
                ↓
        [重试（退避+抖动）]
                ↓
        [资源池隔离]
                ↓
        [背压/限流]
```

- 熔断器：连续失败 N 次打开 → 半开试探 → 成功关闭/失败重新打开
- 超时层级递减：入口 30s > 下游 10s > 单次操作 5s
- 重试：指数退避 + 抖动（与 007 参数对齐）
- 资源池隔离：关键依赖独立连接池
- 背压：队列深度上限 + 并发连接数限制

### 恢复架构

```
[MongoDB] → [mongodump 定时备份] → [AES-256 加密] → [本地 + 异地对象存储]
       ↓
[跨 AZ 部署] → [故障转移] → [服务自动切换]
       ↓
[RTO/RPO 实测] → [演练记录]
```

## 与现有特性的关系

| 特性 | 关系 | 说明 |
|---|---|---|
| **001（gatekeeper）**: 限流/配额策略决策 | 执行层联动 | 001 负责策略决策（工具调用次数、LLM token 用量、租户配额），本特性负责执行层限流 + 背压；本特性告警可触发 001 自动降权 |
| **007（llm-gateway-resilience）**: LLM 调用级 failover/降级/退避 | 参数对齐 | 007 已实现 LLM 调用级韧性（`llm/resilience/`），本特性不重复实现；007 退避参数（1.5s/30s/±10%/3 次）与本特性 FR-23 对齐 |
| **008（ops-dashboard）**: 运营驾驶舱 | 数据源 | 本特性是 008 的数据源（Prometheus 指标、Grafana 面板、告警历史） |
| **010（dag-orchestration）**: 节点级重试 | 分层包裹 | 010 节点重试包裹本特性依赖级重试；追踪链路贯穿 010 DAG 节点与下游调用 |
| **002-006（其他业务特性）**: 无需感知 | 中间件注入 | 业务特性无需感知本特性；入口注入 trace_id 由中间件自动处理 |

## 实施顺序

按依赖关系和独立性排序：

1. **US1（结构化日志与健康检查）** — 基础，所有后续特性依赖日志能力
2. **US2（分布式追踪）** — 依赖 US1 的 trace_id 字段约定
3. **US3（指标与 SLO）** — 可与 US2 并行，但 SLO 依赖 US1 日志能力
4. **US4（告警与排障）** — 依赖 US3 的 SLO 定义
5. **US5（容错与弹性）** — 可与 US1-4 并行（独立子域），但需 US2 的追踪能力观测熔断/重试事件
6. **US6（恢复与灾备）** — 最后实施，依赖 US1-5 全部完成（备份恢复演练需要完整可观测性）

**并行机会**：
- US1 完成后，US2/US3/US5 可并行推进
- US4 依赖 US3，但 US4 的 Runbook 文档可与 US3 并行撰写
- US6 的预案文档可与 US5 并行撰写

## 现有实现事实（contract 依据）

- `services/admin-api/app/main.py`：FastAPI 入口，需接入 structlog + OpenTelemetry + Prometheus
- `services/chat-api/app/main.py`：FastAPI 入口，需接入 structlog + OpenTelemetry + Prometheus
- `services/document-parser/app/main.py`：FastAPI 入口，需接入 structlog + OpenTelemetry + Prometheus
- `services/chat-api/app/llm/resilience/`：007 已实现的 LLM 调用级韧性（failover/降级/退避），本特性不重复
- `services/chat-api/app/config/`：配置目录（resilience.yaml 等），需扩展可观测性配置
- `deploy/docker-compose.yml`：编排文件，需新增 Prometheus / Grafana / Alertmanager / OTel Collector 服务
- `docs/`：文档目录，需新增 `runbooks/` 子目录

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过（本特性有完整 spec.md） |
| II. Production Readiness | 通过（可观测性是生产就绪的核心要素） |
| III. Security | 通过（备份加密、密钥管理、不引入商业 APM 降低攻击面） |
| IV. i18n | 通过（本特性不涉及用户可见文案） |
| V. Observability | 通过（本特性本身就是可观测性建设） |

## Project Structure（新增/修改）

```text
services/
├── admin-api/app/
│   ├── main.py                          # 修改：接入 structlog + OTel + Prometheus
│   └── observability/                   # 新增子模块
│       ├── __init__.py
│       ├── logging.py                   # structlog 配置
│       ├── metrics.py                   # Prometheus 指标定义
│       ├── tracing.py                   # OpenTelemetry 初始化
│       └── health.py                    # /health + /ready 端点
├── chat-api/app/
│   ├── main.py                          # 修改：接入 structlog + OTel + Prometheus
│   ├── observability/                   # 新增子模块（同 admin-api）
│   │   ├── __init__.py
│   │   ├── logging.py
│   │   ├── metrics.py
│   │   ├── tracing.py
│   │   └── health.py
│   └── resilience/                      # 修改：复用 007，新增熔断/限流
│       ├── circuit_breaker.py           # 新增：熔断器
│       ├── rate_limiter.py              # 新增：限流
│       └── timeout.py                   # 新增：超时层级配置
├── document-parser/app/
│   ├── main.py                          # 修改：接入 structlog + OTel + Prometheus
│   └── observability/                   # 新增子模块（同 admin-api）
└── common/                              # 新增：跨服务共享的可观测性工具
    ├── observability_base.py            # 结构化日志/追踪/指标的公共基类
    ├── dependency_guard.py              # 熔断/超时/重试的依赖包装
    └── slo.py                           # SLO 定义与错误预算计算
deploy/
├── docker-compose.yml                   # 修改：新增可观测性服务
├── docker-compose.prod.yml              # 新增：生产编排（含跨 AZ）
├── prometheus/
│   └── prometheus.yml                   # 新增：抓取配置
├── grafana/
│   └── provisioning/
│       ├── dashboards/                  # 新增：排障看板 JSON
│       └── datasources/                 # 新增：数据源配置
├── alertmanager/
│   └── alertmanager.yml                 # 新增：告警路由/静默/抑制
└── otel-collector/
    └── config.yaml                      # 新增：Collector 配置
scripts/
├── backup/
│   ├── backup_mongo.sh                  # 新增：MongoDB 备份脚本
│   └── restore_mongo.sh                 # 新增：MongoDB 恢复脚本
├── chaos/
│   ├── inject_db_failure.sh             # 新增：故障注入脚本
│   ├── inject_llm_timeout.sh            # 新增
│   └── inject_redis_stall.sh            # 新增
└── drill/
    └── drill_recovery.sh                # 新增：恢复演练脚本
docs/
├── runbooks/
│   ├── README.md                        # 新增：排障手册索引
│   ├── mongodb_unreachable.md           # 新增
│   ├── llm_timeout.md                   # 新增
│   ├── redis_stall.md                   # 新增
│   ├── queue_backlog.md                 # 新增
│   ├── certificate_expired.md           # 新增
│   └── disaster-recovery.md             # 新增：灾难恢复预案
└── observability/
    ├── architecture.md                  # 新增：可观测性架构文档
    ├── slo-definition.md                # 新增：SLO 定义与错误预算
    └── monitoring-dashboard.md          # 新增：监控看板配置指南
```

## Open Questions（待 clarify 消解）

- **OQ-1**: 日志后端选型（Loki vs ELK vs 仅 stdout + 平台采集）
- **OQ-2**: 追踪后端选型（Jaeger vs Tempo vs Zipkin）
- **OQ-3**: 熔断库选型（`pybreaker` vs `tenacity` 内置 vs 手写）
- **OQ-4**: 备份存储后端（S3 兼容对象存储 vs NFS vs 本地磁盘）
- **OQ-5**: 告警升级渠道（电话/语音 vs 强制 IM 弹窗）
- **OQ-6**: SLO 目标值（可用性 99.9% vs 99.95%、延迟 P99 < 3s vs < 5s）
- **OQ-7**: RTO/RPO 目标值（30min/15min vs 1h/30min）
- **OQ-8**: 跨 AZ 实现方式（多 Compose 实例 + LB vs 云厂商托管 vs 单宿主机模拟）

## 下一步

1. `/speckit-clarify` 消解 OQ-1 至 OQ-8
2. `/speckit-checklist` 生成需求质量门禁
3. `/speckit-tasks` 拆解实施任务（含文件路径）
4. `/speckit-analyze` 交叉验证
5. `/speckit-implement` 按 US1→US6 顺序实施
6. `/speckit-converge` 收敛验收（对照 Success Criteria）
