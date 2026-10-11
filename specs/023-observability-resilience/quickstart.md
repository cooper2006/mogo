# Quickstart: Observability & Resilience Hardening (023)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md)

本文件说明如何**启用并验证**可观测性与韧性加固基础设施。

---

## 1. 前置条件

### 基础设施依赖

- **Python 3.13**（三个服务统一）
- **Docker + Docker Compose**（部署编排）
- **MongoDB 6.0+**（业务数据 + 备份）
- **Redis 7.0+**（缓存 + 队列）
- **LLM Provider 凭据**（Azure OpenAI / OpenAI 等，007 已配置）

### 新增依赖（Python）

```bash
# 三个服务同步安装
pip install structlog>=24.1.0 \
            opentelemetry-api>=1.25.0 \
            opentelemetry-sdk>=1.25.0 \
            opentelemetry-exporter-otlp>=1.25.0 \
            prometheus-client>=0.20.0 \
            pybreaker>=1.1.0 \
            tenacity>=8.3.0
```

### 新增依赖（Docker Compose 服务）

```yaml
# deploy/docker-compose.yml 新增服务
- prometheus:9090           # 指标抓取与存储
- grafana:3000              # 可视化 + 排障看板
- alertmanager:9093         # 告警路由
- otel-collector:4317/4318  # OTLP 接收
- jaeger:16686/14268        # 或 tempo（追踪存储）
- loki:3100                 # 可选（日志存储）
```

### 密钥与配置

- **备份加密密钥**：`MONGO_BACKUP_KEY`（AES-256，从密钥管理系统读取，不进代码仓库）
- **告警通知**：IM webhook URL（钉钉/飞书/企业微信）、SMTP 邮件配置
- **对象存储凭据**（备份异地存储）：`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET`、`S3_ENDPOINT`
- **OpenTelemetry 采样率**：`OTEL_SAMPLER_PROBABILITY=0.1`（生产默认 10%）

---

## 2. 启用步骤

### 2.1 US1 — 结构化日志与健康检查

**启用步骤**:
1. 修改 `services/admin-api/app/main.py`、`services/chat-api/app/main.py`、`services/document-parser/app/main.py`，接入 structlog
2. 注册 `/health` 与 `/ready` 端点
3. 配置环境变量 `LOG_LEVEL=INFO`（生产）或 `LOG_LEVEL=DEBUG`（调试）

**验证命令**:
```bash
# 检查 /health 端点（存活）
curl -s http://localhost:8000/health | jq .
# 期望: {"status": "alive", "service": "admin-api", "ts": "..."}

# 检查 /ready 端点（就绪，含依赖检查）
curl -s http://localhost:8000/ready | jq .
# 期望: {"status": "ready", "dependencies": {"mongodb": "ok", "redis": "ok", "llm": "ok"}}
# 或:   {"status": "not_ready", "dependencies": {"mongodb": "unreachable", ...}}

# 检查日志格式（JSON）
docker logs <container> --tail 1 | jq .
# 期望: {"ts": "...", "level": "info", "service": "admin-api", "message": "...", "trace_id": "...", "span_id": "...", "tenant_id": "...", "user_id": "..."}

# 运行时切换日志级别
curl -X POST http://localhost:8000/admin/log-level -H "Content-Type: application/json" -d '{"level": "DEBUG"}'
docker logs <container> --tail 1 | jq .level
# 期望: "debug"
```

### 2.2 US2 — 分布式追踪

**启用步骤**:
1. 在三个服务中初始化 OpenTelemetry SDK（`init_tracing()`）
2. 注册 FastAPI Instrumentor 与 HTTPX Instrumentor
3. 配置 `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`
4. 配置采样率 `OTEL_SAMPLER_PROBABILITY=0.1`

**验证命令**:
```bash
# 触发一次请求，获取 trace_id
TRACE_ID=$(curl -s http://localhost:8000/api/test -D - | grep -i trace-id | tr -d '\r' | cut -d' ' -f2)
echo "Trace ID: $TRACE_ID"

# 查询追踪后端
curl -s http://localhost:16686/api/traces/$TRACE_ID | jq .
# 期望: 返回完整调用链（HTTP server span → 下游 HTTP client span → DB span → LLM span）

# 验证日志含 trace_id
docker logs <container> --tail 100 | jq 'select(.trace_id != null)'
# 期望: 日志条目含 trace_id 字段
```

### 2.3 US3 — 指标与 SLO

**启用步骤**:
1. 在三个服务中初始化 Prometheus client（`init_metrics()`）
2. 注册黄金四信号 + 业务指标
3. 配置 Prometheus 抓取（`deploy/prometheus/prometheus.yml`）
4. 配置 SLO 定义（`services/common/slo.py`）与 recording rule

**验证命令**:
```bash
# 抓取 /metrics 端点
curl -s http://localhost:8000/metrics | grep "http_request_duration_seconds" | head
# 期望: 返回 HTTP 请求延迟 histogram 数据

# 查询黄金四信号
curl -s http://localhost:9090/api/v1/query --data-urlencode 'query=sum(rate(http_requests_total{service="admin-api"}[5m]))' | jq .
# 期望: 返回请求流量（QPS）

# 查询 SLO 错误预算
curl -s http://localhost:9090/api/v1/query --data-urlencode 'query=error_budget_remaining_ratio{service="chat-api"}' | jq .
# 期望: 返回错误预算剩余比例（0-1）
```

### 2.4 US4 — 告警与排障

**启用步骤**:
1. 配置 Alertmanager（`deploy/alertmanager/alertmanager.yml`）
2. 配置告警规则（`deploy/prometheus/alert-rules.yml`）
3. 配置通知模板（含 Runbook 链接、Grafana 面板链接、Trace 查询链接）
4. 创建 Runbook 文档（`docs/runbooks/`）

**验证命令**:
```bash
# 触发 SLO 违约告警（模拟高错误率）
curl -X POST http://localhost:9093/api/v1/alerts -H "Content-Type: application/json" -d '[
  {"labels": {"alertname": "SLOBurnRate", "severity": "P0", "service": "chat-api"},
   "annotations": {"summary": "SLO 违约：错误预算消耗速度超阈值"}}
]'
# 期望: Alertmanager 触发告警，发送 IM + 邮件通知

# 验证告警分级路由
curl -s http://localhost:9093/api/v1/alerts | jq '.[].labels.severity'
# 期望: P0/P1/P2 分别路由到不同通知渠道

# 验证静默
curl -X POST http://localhost:9093/api/v2/silences -H "Content-Type: application/json" -d '{
  "matchers": [{"name": "alertname", "value": "SLOBurnRate", "isRegex": false}],
  "startsAt": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
  "endsAt": "'"$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%SZ)"'",
  "createdBy": "test",
  "comment": "维护窗口静默"
}'
# 期望: 静默生效，维护窗口内告警不触发
```

### 2.5 US5 — 容错与弹性

**启用步骤**:
1. 在 `services/common/dependency_guard.py` 中实现熔断器、超时、限流、背压
2. 用 CircuitBreaker + TimeoutGuard + ConnectionPool 包装 MongoDB/Redis/LLM 客户端
3. 配置熔断阈值（默认 5 次连续失败）、超时层级（30s/10s/5s）、重试参数（1.5s/30s/±10%/3 次）
4. 注册 RateLimiter + BackpressureGuard 中间件

**验证命令**:
```bash
# 模拟 MongoDB 连续失败，触发熔断
for i in {1..6}; do
  curl -s http://localhost:8000/api/test | jq .
done
# 期望: 前 5 次正常返回，第 6 次开始熔断打开，返回快速失败响应

# 检查熔断器状态
curl -s http://localhost:8000/metrics | grep "circuit_breaker_state"
# 期望: circuit_breaker_state{dependency="mongodb",state="open"} 1

# 验证超时层级递减
time curl -s --max-time 30 http://localhost:8000/api/slow-test
# 期望: 下游调用 10s 超时后返回，不占用 30s

# 验证重试退避
curl -s http://localhost:8000/api/retry-test | jq .
# 期望: 可重试错误（429/5xx）按退避间隔重试 3 次，不可重试（401/403）立即失败

# 验证背压
for i in {1..1500}; do
  curl -s http://localhost:8000/api/async-task &
done
wait
# 期望: 队列深度超过 1000 后返回 429，不崩溃
```

### 2.6 US6 — 恢复与灾备

**启用步骤**:
1. 配置备份脚本（`scripts/backup/backup_mongo.sh`）与 cron
2. 配置加密密钥（`MONGO_BACKUP_KEY`）与对象存储凭据
3. 配置备份保留策略（30 天本地 + 90 天异地）
4. 配置跨 AZ 部署（`deploy/docker-compose.prod.yml`）
5. 配置 Liveness/Readiness 探针与 restart policy

**验证命令**:
```bash
# 执行备份
./scripts/backup/backup_mongo.sh
ls -la backups/
# 期望: 生成加密备份文件（.gz.gpg）

# 执行恢复演练
./scripts/drill/drill_recovery.sh --backup-file backups/mongo-$(date +%Y%m%d).gz.gpg --target-instance test-mongo
./scripts/drill/drill_recovery.sh --verify --target-instance test-mongo
# 期望: 恢复成功，数据一致性校验通过

# 验证保留策略
./scripts/backup/rotate_backups.sh
ls -la backups/local/ backups/remote/
# 期望: 本地保留 30 天，异地保留 90 天，过期自动清理

# 模拟宿主机宕机（跨 AZ 故障转移）
docker stop chat-api-1
sleep 30
curl -s http://localhost:8000/health | jq .
# 期望: 请求自动切换到 chat-api-2 副本，返回存活状态（RTO ≤ 30min）

# 验证 RTO/RPO 实测记录
cat docs/observability/rto-rpo.md
# 期望: 记录演练时间线、RTO/RPO 实测值、数据丢失窗口
```

---

## 3. 验证清单

### US1 — 结构化日志与健康检查

| # | 验证项 | 期望 |
|---|---|---|
| 1 | 日志格式 | JSON，字段稳定（ts/level/service/message/trace_id/span_id/tenant_id/user_id） |
| 2 | LOG_LEVEL 切换 | 运行时生效，无需重启 |
| 3 | ERROR 日志上下文 | 含完整堆栈、请求路径、用户标识、租户标识、下游耗时 |
| 4 | /health 端点 | 返回进程存活状态（不检查依赖） |
| 5 | /ready 端点 | 依赖可达返回 200，不可达返回 503 |
| 6 | 启动自检 | 依赖不可达不退出，/ready 返回 503 |

### US2 — 分布式追踪

| # | 验证项 | 期望 |
|---|---|---|
| 1 | 完整调用链 | admin-api → chat-api → document-parser → LLM provider 可还原 |
| 2 | 日志-追踪互跳 | 日志含 trace_id，可跳转追踪后端 |
| 3 | 异步任务追踪 | 异步任务 trace_id 与触发请求一致 |
| 4 | traceparent 注入 | 下游 HTTP 调用自动注入 W3C traceparent header |
| 5 | 采样率 | 可配（默认 10%，调试 100%） |

### US3 — 指标与 SLO

| # | 验证项 | 期望 |
|---|---|---|
| 1 | 黄金四信号 | /metrics 可查询延迟、流量、错误率、饱和度 |
| 2 | 业务指标 | 会话/消息/LLM/token/文档解析数按维度聚合 |
| 3 | 维度基数受控 | 高基数 label 哈希化，单指标 label 组合 ≤ 10000 |
| 4 | SLO 定义 | 可用性 99.9%、延迟 P99 < 3s、LLM 错误率 < 1% |
| 5 | 错误预算 | 数值可查，消耗速度可查 |

### US4 — 告警与排障

| # | 验证项 | 期望 |
|---|---|---|
| 1 | SLO 违约告警 | 触发 P0 告警，触达 IM + 邮件（≤ 5min） |
| 2 | 告警分级 | P0/P1/P2 分级路由，P0 电话/弹窗升级 |
| 3 | 静默/抑制 | 维护窗口生效，同一根因去重 |
| 4 | 通知含排障入口 | Runbook 链接 + Grafana 面板 + Trace 查询 |
| 5 | Runbook 覆盖 | ≥ 5 个高频场景（MongoDB/LLM/Redis/队列/证书） |
| 6 | 排障看板 | 服务 → 依赖 → 单个慢请求 span 逐层下钻 |

### US5 — 容错与弹性

| # | 验证项 | 期望 |
|---|---|---|
| 1 | 熔断器 | 连续失败 5 次触发熔断，半开试探成功关闭/失败重新打开 |
| 2 | 超时层级递减 | 入口 30s > 下游 10s > 单次 5s，超时后资源释放 |
| 3 | 重试退避 | 可重试错误（429/5xx/超时）退避 3 次，不可重试（401/403）不重试 |
| 4 | 资源池隔离 | 关键依赖独立连接池 |
| 5 | 背压 | 队列深度 > 1000 返回 429，不崩溃 |

### US6 — 恢复与灾备

| # | 验证项 | 期望 |
|---|---|---|
| 1 | 自动备份 | mongodump 定时执行，AES-256 加密，上传异地 |
| 2 | 保留策略 | 30 天本地 + 90 天异地，过期自动清理 |
| 3 | 恢复演练 | 从备份恢复，数据一致性校验通过 |
| 4 | 跨 AZ 故障转移 | 宿主机宕机后服务自动切换（RTO ≤ 30min） |
| 5 | RTO/RPO 实测 | 演练记录含实测值（RTO ≤ 30min、RPO ≤ 15min） |
| 6 | 预案文档化 | ≥ 5 个场景，每场景含预案 + 恢复步骤 |

---

## 4. 监控看板配置

### 4.1 平台概览面板（`platform-overview.json`）

**位置**: `deploy/grafana/provisioning/dashboards/platform-overview.json`

**内容**:
- 平台可用性（SLO 错误预算剩余比例）
- 请求延迟分布（P50/P95/P99）
- 错误率趋势（按服务）
- 业务指标趋势（会话数、消息数、LLM 调用数、token 用量）
- 活跃告警数（按级别 P0/P1/P2）

### 4.2 黄金四信号面板（`gold-signals.json`）

**位置**: `deploy/grafana/provisioning/dashboards/gold-signals.json`

**内容**:
- 延迟：请求延迟 histogram（按服务、路径、状态码）
- 流量：QPS（按服务、路径）
- 错误率：错误率百分比（按服务、下游依赖）
- 饱和度：连接池使用率、队列深度、GC 停顿时间

### 4.3 SLO 面板（`slo-overview.json`）

**位置**: `deploy/grafana/provisioning/dashboards/slo-overview.json`

**内容**:
- SLO 达标状态（红/黄/绿）
- 错误预算消耗趋势（burn rate）
- 错误预算剩余比例与预计耗尽时间
- 历史 SLO 违约记录

### 4.4 排障看板（`troubleshooting.json`）

**位置**: `deploy/grafana/provisioning/dashboards/troubleshooting.json`

**内容**:
- 服务概览（健康状态、延迟、错误率）
- 依赖健康（MongoDB、Redis、LLM provider 状态）
- 熔断器状态（打开/半开/关闭）
- 单个慢请求下钻（Trace 查询、Span 详情）
- 相关日志查询（含 trace_id 过滤）

### 4.5 业务指标面板（`business-metrics.json`）

**位置**: `deploy/grafana/provisioning/dashboards/business-metrics.json`

**内容**:
- 会话创建数（按租户、智能体）
- 消息发送数（按租户、智能体）
- LLM 调用数与 token 用量（按供应商、模型、租户）
- 文档解析数与解析耗时（按文档类型）

### 4.6 告警历史面板（`alert-history.json`）

**位置**: `deploy/grafana/provisioning/dashboards/alert-history.json`

**内容**:
- 告警触发历史（按级别、服务、告警名）
- 告警响应时间（触发 → 确认 → 恢复）
- 告警 MTTA/MTTR（平均触发到确认/恢复时间）

---

## 5. 故障注入演练（可选）

### 5.1 MongoDB 不可达

```bash
# 注入故障
./scripts/chaos/inject_db_failure.sh --target mongo --duration 300
# 验证
curl -s http://localhost:8000/ready | jq .dependencies.mongodb
# 期望: "unreachable"，熔断器打开
# 恢复
./scripts/chaos/inject_db_failure.sh --target mongo --revert
```

### 5.2 LLM Provider 超时

```bash
# 注入故障
./scripts/chaos/inject_llm_timeout.sh --target openai --delay 30
# 验证
curl -s http://localhost:8000/api/chat | jq .
# 期望: 返回降级响应或明确错误（不超时）
# 恢复
./scripts/chaos/inject_llm_timeout.sh --target openai --revert
```

### 5.3 Redis 抖动

```bash
# 注入故障
./scripts/chaos/inject_redis_stall.sh --target redis --stall-ms 5000
# 验证
curl -s http://localhost:8000/metrics | grep "redis_circuit_breaker_state"
# 期望: 熔断器打开
# 恢复
./scripts/chaos/inject_redis_stall.sh --target redis --revert
```

---

## 6. 完整启用流程（一次性）

```bash
# 1. 安装依赖
pip install -r services/admin-api/requirements.txt
pip install -r services/chat-api/requirements.txt
pip install -r services/document-parser/requirements.txt

# 2. 启动可观测性基础设施
docker compose -f deploy/docker-compose.yml up -d prometheus grafana alertmanager otel-collector jaeger

# 3. 配置备份
export MONGO_BACKUP_KEY=$(cat /secure/path/to/backup.key)
export S3_ACCESS_KEY=xxx
export S3_SECRET_KEY=xxx
export S3_BUCKET=movo-backups
export S3_ENDPOINT=https://s3.example.com
cron install scripts/backup/backup_mongo.sh

# 4. 配置告警通知
# 编辑 deploy/alertmanager/alertmanager.yml，配置 IM webhook 与 SMTP

# 5. 启动业务服务
docker compose -f deploy/docker-compose.yml up -d admin-api chat-api document-parser

# 6. 验证全链路
curl -s http://localhost:8000/health | jq .           # 存活检查
curl -s http://localhost:8000/ready | jq .            # 就绪检查
curl -s http://localhost:8000/metrics | head          # 指标暴露
curl -s http://localhost:16686/                        # 追踪后端
curl -s http://localhost:3000/                         # Grafana
curl -s http://localhost:9093/                          # Alertmanager
```

---

## 7. 常见问题

**Q1: 日志级别切换后多久生效？**
A: 立即生效（structlog 动态读取配置），无需重启进程。

**Q2: 如何临时提高追踪采样率？**
A: 修改环境变量 `OTEL_SAMPLER_PROBABILITY=1.0` 并重启服务，或配置 `OTEL_SAMPLER` 为 `always_on`。

**Q3: Prometheus 内存占用过高怎么办？**
A: 检查高基数 label（user_id/session_id/path 参数），确保已哈希化或降级为枚举桶；调整 `tsdb.retention.time`（默认 15 天）。

**Q4: 告警风暴如何处理？**
A: 配置 Alertmanager 分组规则（`group_by` + `group_wait` + `group_interval`），配置抑制规则（`inhibit_rules`），配置静默窗口（`silences`）。

**Q5: 备份恢复后数据不一致怎么办？**
A: 检查备份完整性（checksum）、恢复步骤是否正确、MongoDB 版本是否一致；参考 `docs/runbooks/mongodb_unreachable.md` 的恢复步骤。

---

## 8. 下一步

1. 执行 `/speckit-clarify` 消解 OQ-1 至 OQ-8（默认参数、库选型、SLO/RTO 目标值）
2. 执行 `/speckit-checklist` 生成需求质量门禁
3. 按 [tasks.md](./tasks.md) 顺序实施
4. 每完成一个 US，对照本文件的验证清单验证
5. 全部完成后，对照 spec.md 的 Success Criteria 最终验收
