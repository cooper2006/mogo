# 可观测性与韧性架构（023 全景）

> 本文是 023 的**总图**：一条请求怎么变成日志/追踪/指标/告警，故障怎么被定位，
> 灾难怎么被恢复。细节各归其位：
> [SLO 定义](slo-definition.md) · [看板指南](monitoring-dashboard.md) ·
> [RTO/RPO](rto-rpo.md) · [灾难恢复预案](../runbooks/disaster-recovery.md)。

## 1. 全景

```
                           ┌─────────────── 应用层（三个服务） ───────────────┐
  用户/客户端 ──HTTPS──▶ gateway ──▶ chat-api / admin-api / document-api
                                     │  ├─ structlog（JSON，注入 trace_id/tenant_id/user_id）
                                     │  ├─ OTel SDK（FastAPI/httpx/motor/redis/Celery 自动埋点）
                                     │  ├─ prometheus_client（黄金四信号 + 业务指标）
                                     │  ├─ /health /ready（存活 vs 就绪分离）
                                     │  └─ 韧性层（重试/熔断/超时/池/限流/背压）
                                     └───────────────┬──────────────┘
                                                     │ OTLP / scrape / stdout
                        ┌────────────────────────────┼────────────────────────────┐
                        ▼                            ▼                            ▼
                 otel-collector                 prometheus                   loki / tempo
                 （批量/脱敏/扇出）            （抓取 + 记录规则 +        （日志聚合 / 追踪存储）
                        │                      告警规则）
                        ├──────────▶ tempo            │
                        └──────────▶ prometheus       ▼
                                                 alertmanager ──▶ IM / 邮件（P0/P1/P2 分级路由）
                        └──────────▶ loki            │
                                                     ▼
                                                  grafana（4 个看板：黄金信号 / SLO / 业务 / 排障）
```

对应目录（全部可版本化，没有「手点出来的配置」）：

| 组件 | 位置 |
|---|---|
| 抓取与规则 | `deploy/prometheus/prometheus.yml`、`deploy/prometheus/rules/{slo_recording.yml,alert-rules.yml}` |
| 告警路由与模板 | `deploy/alertmanager/`（含 `templates/`） |
| 日志 | `deploy/loki/loki.yaml` |
| 追踪 | `deploy/tempo/tempo.yaml` |
| 采集扇出 | `deploy/otel-collector/config.yaml` |
| 看板 | `deploy/grafana/provisioning/dashboards/{gold-signals,slo-overview,business-metrics,troubleshooting}.json` |
| 探针 | `deploy/probes/{readiness.sh,liveness.sh}` |
| 备份/恢复/演练 | `scripts/backup/`、`scripts/drill/` |

## 2. 三类信号的分工（不要互相替代）

| 信号 | 回答什么问题 | 保留期与成本 | 典型入口 |
|---|---|---|---|
| **指标**（Prometheus） | 「有没有问题、问题多大」——聚合、可告警、便宜 | 长（15 天–1 年） | 告警、看板、SLO |
| **追踪**（Tempo） | 「慢在哪一跳、错在哪个服务」——单请求全链路 | 短（数天）、按采样 | 排障看板 → trace → span |
| **日志**（Loki） | 「具体发生了什么、参数是什么」——精确事实 | 中（7–30 天）、体积大 | 按 trace_id 反查日志 |

排障的标准动线是 **告警 → 看板（哪个服务/哪位面）→ 指标（何时开始）→ trace（哪一跳）→ 日志（为什么）**。
跳步的代价：直接翻日志会在高基数里迷路；看 trace 而不看指标会误判「偶发」为「普遍」。

## 3. 一条请求的全链路（trace 结构）

```
gateway（HTTP server span）
└─ chat-api（HTTP server span，携带 traceparent）
   ├─ mongodb（client span，经 motor 自动埋点，service=mongodb）
   ├─ redis（client span）
   ├─ LLM provider（client span，属性含 provider/model/tokens；HTTP 出站由 httpx 埋点）
   └─ Celery 任务派发（trace_id 通过消息头传播，worker 侧续接同一 trace）
```

可验证的事实：日志里的 `trace_id` 与 trace 后端查到的 trace 一致（同一个 `traceparent`），
因此「日志 ↔ 追踪」可以双向跳转，不需要靠时间戳猜。

**采样**：默认父级采样（parent-based）+ 低比例根采样；LLM 调用可在 `LLM span` 上单独
标注，便于在追踪后端按「是否有 LLM span」筛选慢请求。采样率调低只影响追踪完整性，
不影响指标与告警。

## 4. 探针与生命周期的分工

| 探针 | 查什么 | 失败后果 | 不查什么 |
|---|---|---|---|
| **liveness**（`deploy/probes/liveness.sh`） | 进程是否还能响应 `/health` | 容器**重启** | **刻意不查 Mongo/Redis/LLM**——依赖抖动导致重启只会把故障放大成雪崩 |
| **readiness**（`deploy/probes/readiness.sh`） | `/ready` 的 `dependencies` 是否全 `ok` | 从负载均衡**摘除**（不重启） | 不判断业务是否成功 |

这条分工是 023 最容易搞错的地方：把依赖检查放进 liveness ⇒ 数据库抖一下，所有副本
同时重启 ⇒ 冷启动期间全部不可用。**依赖问题用摘流量（readiness）+ 降级回答，
不用重启回答。**

## 5. 韧性层（Phase 6）

每一层都能单独失效，且失效是**可见的**（有指标/日志），不是静默：

| 机制 | 位置 | 触发时的表现 |
|---|---|---|
| 超时层级 | `services/common/dependency_guard.py`（`TimeoutHierarchy`） | 入口 30s > 下游 10s > 单次 5s；倒挂配置回退到安全默认并告警 |
| 熔断（同步/异步） | 同上（`call_with_breaker` / `call_with_breaker_async`） | OPEN 时**快速失败**（毫秒级）而不是等超时；HALF_OPEN 放探测流量 |
| 重试 | 同上（`retry` / `retry_async`） | 指数退避 + 抖动；只对幂等/可重试错误重试 |
| 连接池隔离 | `services/chat-api/app/llm/providers/pools.py`、`services/{chat-api,admin-api}/app/core/resilience.py` | 每个 LLM provider 独立池；Mongo/Redis 各自登记池上限，一个下游打满不会抢占另一个 |
| 限流 | 租户级（Redis 计数） | 超限返回 429 + `Retry-After` |
| 背压 | 纯 ASGI 中间件 | 队列/并发达上限时 429 快速拒绝，而不是把请求堆到超时 |
| 降级 | 各能力的 fallback 分支 | 返回明确的「稍后重试」，而非 30s 后 5xx |

**异步熔断为什么自己写**：pybreaker 1.4.1 的 `call_async()` 依赖 tornado，本仓库没有该
依赖，直接调用会 `NameError: name 'gen' is not defined`。因此 `dependency_guard` 用状态机
原语（`_handle_error` / `_handle_success` / `half_open()`）自行驱动，语义与 pybreaker 一致。

**超时为什么必须包在熔断器内部**：若 `asyncio.wait_for` 包在熔断器外面，超时抛出的
`CancelledError` 不会计入失败，于是「挂死的依赖永远不会熔断」——每次请求都要等满超时，
表现为请求卡死。正确顺序是 breaker 在内、超时在外（breaker 看到的是超时异常本身）。

## 6. 恢复层（Phase 7）

```
backup_mongo.sh（*/15 oplog / 每日全量）
  └─ mongodump → AES-256 → .enc + .sha256 + .json 清单（明文摘要 + 逐集合文档数）
        ├─ 本地 backups/（30 天）
        └─ 异地（MOGO_BACKUP_OFFSITE_DIR / rclone，90 天）
              └─ drill_recovery.sh（每周）→ 恢复到演练库 → 抽样比对 → RTO/RPO 报告
                    └─ restore_mongo.sh（真实恢复路径，与演练同一条代码路径）
```

关键设计：**演练路径 = 真实恢复路径**。演练若走一条「更简单的捷径」，真正出事时那条
捷径不存在（演练库是空的、源库是停的），RTO 数字就是假的。

## 7. 故障域与隔离边界

| 故障域 | 影响范围 | 隔离手段 |
|---|---|---|
| 单个 LLM provider | 该 provider 的请求 | 独立连接池 + 独立熔断器 + 备用 provider |
| MongoDB | 全部读写 | 熔断快速失败 → readiness 摘流量 → 降级回答 |
| Redis | 锁/限流/缓存 | 同上；Redis 全丢可从空重建（见预案 §7） |
| 单个应用副本 | 该副本的在途请求 | `replicas: 2` + `max_replicas_per_node: 1` + readiness |
| 单个 AZ / 宿主机 | 该 AZ 全部容器 | 跨 AZ 副本 + `restart_policy: any` + VIP/LB |
| 备份介质 | 灾备能力 | 异地副本 + 口令与备份分离存放 |

## 8. 上线自检清单

- [ ] `curl /health` 返回 `alive`；`curl /ready` 的 `dependencies` 全 `ok`
- [ ] `curl /metrics` 有 `mogo_http_requests_total`；Prometheus target 全部 `UP`
- [ ] 一次请求后，Loki 能按 `trace_id` 查到日志、Tempo 能查到同一 trace
- [ ] 手动触发一条告警（例如把阈值调到 0）→ Alertmanager → IM 收到 → 恢复阈值
- [ ] 4 个 Grafana 看板都能加载（数据源自动 provisioning，无手动步骤）
- [ ] `bash scripts/backup/backup_mongo.sh --mode full` 产出 `.enc/.sha256/.json` 三件套
- [ ] `bash scripts/backup/restore_mongo.sh --archive <最新> --consistency-only` 通过
- [ ] `mongo-backup` 容器 healthy（`.last-success` 在 2 小时内）
- [ ] （每次演练前）`bash scripts/verify_e2e_observability.sh` 与 `bash scripts/drill/inject_dependency_fault.sh`
      均以 `0` 退出；若退出码是 `2`（环境不具备），先修环境，**不要把它当成通过**
- [ ] 跨 AZ 环境：`docker service ls` 全部 N/N；`deploy/probes/readiness.sh` 在容器内可执行

## 9. 端到端验证（Phase 8）

三条脚本链路，把前面的每个环节**真的跑一遍**（不是「配置在就算齐了」）：

| 剧本 | 验证什么 | 关键断言 | 退出码语义 |
|---|---|---|---|
| `scripts/verify_e2e_observability.sh`（T116） | 一次真实请求贯穿三信号 | 注入 `traceparent` → Loki 按 trace_id 查到日志 / Tempo 查到同一 trace / `mogo_http_requests_total` 增长 / `mogo:slo:availability:error_rate` 有值 / mogo 告警规则组 ≥10 条 | `0` 通过 · `1` 断言失败 · `2` 环境不具备 |
| `scripts/drill/inject_dependency_fault.sh`（T117） | 故障注入 → 熔断 → 快速失败 → 告警 → 看板 | 真停 `mongo` → `/ready` 转非 2xx → 5 次请求全 5xx 且 ≤1s → `mogo_circuit_breaker_state{dependency="mongodb",state="open"}=1` → Alertmanager 有 `Mogo*` 告警 → `uid=mogo-troubleshooting` 可读 → 恢复后 `state="closed"=1` | 同上 |
| `scripts/drill/full_recovery_drill.sh`（T118） | 备份 → 恢复 → 校验 → 切换 | 调**生产同款** `backup_mongo.sh --mode full` → 取最新归档 → `drill_recovery.sh` 恢复演练 + 抽样比对 → 报告记录 RTO/RPO → `--api-url` 就绪探针 | 同上 |

**失败语义是一条硬约定**：`2` 表示「这一步没跑成」，不能算通过。CI 里要么把该步标
`skipped`、要么让它红——把 `2` 归一成绿，演练就白做了。三个剧本都配了行为测试
（`scripts/test_verify_e2e_observability.sh`、`scripts/test_inject_dependency_fault.sh`、
`scripts/test_full_recovery_drill.sh`），它们用假后端（`scripts/testlib/`）把「该过的时候过、
该失败的时候失败」都断言了一遍，防止剧本退化成「永远返回 0」的装饰脚本。

故障注入链路（一次 Mongo 故障的全过程）：

```
docker compose stop mongo
  └─ readiness 探针：/ready 的 dependencies.mongodb 转 false → 摘流量（不重启）
       └─ 熔断器：连续失败达阈值 → OPEN → 后续请求毫秒级快速失败（不等超时）
            └─ 指标：mogo_circuit_breaker_state{state="open"}=1
                 └─ 告警：MogoCriticalPathErrorRateSpike（P1）→ Alertmanager → IM
                      └─ 排障动线：告警 → mogo-troubleshooting（依赖健康层）
                           → mogo_circuit_breaker_state → trace → 按 trace_id 查日志
```
