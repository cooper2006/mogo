# quickstart — 可观测性与韧性栈启用与验证（023）

> 本文回答一个问题：**把 023 的日志 / 追踪 / 指标 / 告警 / 容错 / 恢复跑起来，最少几步？**
> 全景见 [docs/observability/architecture.md](docs/observability/architecture.md)；
> SLO 见 [docs/observability/slo-definition.md](docs/observability/slo-definition.md)；
> 看板见 [docs/observability/monitoring-dashboard.md](docs/observability/monitoring-dashboard.md)。

## 0. 前置条件

| 项 | 要求 |
|---|---|
| Docker | docker + docker compose v2（`docker compose version` 能返回版本号） |
| 三个服务 | gateway / chat-api / admin-api / document-api 已 `up -d` |
| 磁盘 | 日志保留期与备份 30 天，按 `deploy/loki/loki.yaml` 与 `scripts/backup/lib.sh` 的保留策略预估 |
| 口令 | `MOGO_BACKUP_PASSPHRASE`（备份加密用；不设则备份直接失败） |

## 1. 起监控栈（observability profile）

```bash
docker compose --profile observability up -d
# 检查六个组件
docker compose ps
```

组件端口（compose 内网络互访，host 侧按需映射）：

| 组件 | 端口 | 健康检查 |
|---|---|---|
| otel-collector | 4317/4318 | `docker compose ps otel-collector` |
| prometheus | 9090 | `curl -s http://127.0.0.1:9090/-/ready` |
| loki | 3100 | `curl -s http://127.0.0.1:3100/ready` |
| tempo | 3200 | `curl -s http://127.0.0.1:3200/api/echo` |
| alertmanager | 9093 | `curl -s http://127.0.0.1:9093/-/ready` |
| grafana | 3000 | `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/api/health` |

任一项不通 → **先修环境**，不要往下走。

## 2. 启用三个服务

```bash
docker compose up -d gateway chat-api admin-api document-api
```

- 日志：服务用 structlog 输出 JSON（含 `trace_id`/`tenant_id`/`user_id`），由 compose 的
  loki driver 或文件采集进 Loki。**验证**：Loki 里能按 `service_name` 查到行。
- 追踪：OTel SDK 输出到 otel-collector，扇出到 Tempo/Prometheus。
  **验证**：Tempo 里能看到 `mogo_gateway` 起头的 trace。
- 指标：`prometheus_client` 暴露 `/metrics`，Prometheus 抓取。
  **验证**：`curl http://127.0.0.1:9090/api/v1/query?query=mogo_http_requests_total`
  返回非空序列。
- 告警：`deploy/prometheus/rules/{slo_recording.yml,alert-rules.yml}` 由 Prometheus 加载，
  Alertmanager 按 `deploy/alertmanager/` 路由到 IM/邮件。
- 韧性：`services/common/dependency_guard.py` 提供超时层级 / 熔断 / 重试 /
  连接池隔离；`services/common/observability_base.py` 提供 `/health`、`/ready` 与
  熔断/限流指标注册。

## 3. 验证：四个信号与三剧本

**快速自检**（不需要额外环境）：

```bash
curl -s http://127.0.0.1:8080/health    # {"status":"alive"}
curl -s http://127.0.0.1:8080/ready     # dependencies.mongodb/redis/llm 全 ok
curl -s http://127.0.0.1:8080/metrics | grep -c '^mogo_'   # 业务指标非 0
```

**端到端剧本**（T116/T117/T118，必须真的跑）：

```bash
# 全链路追踪验证：一次请求 → 日志/追踪/指标/规则
bash scripts/verify_e2e_observability.sh

# 端到端韧性验证：停 Mongo → 熔断 → 快速失败 → 告警 → 看板
bash scripts/drill/inject_dependency_fault.sh --prometheus-url http://127.0.0.1:9090 \
  --alertmanager-url http://127.0.0.1:9093 --grafana-url http://127.0.0.1:3000

# 端到端恢复验证：备份 → 恢复 → 一致性 → 切换
bash scripts/drill/full_recovery_drill.sh --api-url http://127.0.0.1:8000
```

报告落在 `artifacts/observability/`（可用 `--report-dir` 改）。

**退出码语义（重要）**：`0` 通过 · `1` 断言失败 · `2` 环境不具备。
`2` 意味着这一步**没跑成**，不能当作通过；CI 里请标 `skipped` 而不是绿。

**行为测试**（不需要真实环境，验证剧本本身的断言有效）：

```bash
bash scripts/test_verify_e2e_observability.sh
bash scripts/test_inject_dependency_fault.sh
bash scripts/test_full_recovery_drill.sh
```

## 4. 常见失败对照

| 现象 | 原因 | 处理 |
|---|---|---|
| 剧本返回 `2` 并提示「环境不具备」 | 缺 Loki/Tempo/Prometheus/Alertmanager 之一，或 `docker` 不可用 | 回 §1 检查组件健康；不要改断言 |
| `/ready` 的 `dependencies.mongodb` 转 `false` | Mongo 抖动或被停 | 看 `mogo_circuit_breaker_state{state="open"}` 是否打开；`docker compose start mongo` 后等熔断复位 |
| Loki 按 trace_id 查不到日志 | 采样或日志驱动未接 | 先确认 `curl /ready` 带 `traceparent` 时 Loki 有行；再查 compose 的日志 driver |
| 熔断不打开、每次请求都等满超时 | 超时包在熔断器**外面**（CancelledError 不计失败） | 确认 `services/common/dependency_guard.py` 中 breaker 在内、超时在外 |
| 告警没触发 | 规则未加载、`for` 未到、或通知链未通 | `curl http://127.0.0.1:9090/api/v1/rules` 看 mogo 分组；`curl http://127.0.0.1:9093/api/v2/alerts` |

## 5. 上线自检清单

```bash
curl -s http://127.0.0.1:8080/health
curl -s http://127.0.0.1:8080/ready
curl -s http://127.0.0.1:8080/metrics | grep -c '^mogo_'
bash scripts/verify_e2e_observability.sh          # 全链路
bash scripts/drill/inject_dependency_fault.sh     # 韧性（故障注入）
bash scripts/drill/full_recovery_drill.sh         # 恢复（备份→恢复→切换）
```
