# mogo 排障手册（Runbook）索引

> 023 observability-resilience · US4 告警与排障（T067）
>
> 本目录是**故障处置的唯一事实来源**。告警通知里的 `Runbook` 链接指向这里，
> 值班同学按「对应场景 → 症状 → 根因 → 恢复步骤」执行，不要在 IM 里口头传
> 处置步骤（下次没人找得到）。

## 1. 从告警到 Runbook 的映射

| 告警名 | 级别 | Runbook |
|---|---|---|
| `MogoAvailabilityBurnRateFast` | P0 | [high_error_rate.md](high_error_rate.md) |
| `MogoAvailabilityBurnRateMedium` | P1 | [high_error_rate.md](high_error_rate.md) |
| `MogoAvailabilityBurnRateSlow` | P1 | [high_error_rate.md](high_error_rate.md) |
| `MogoCriticalPathErrorRateSpike` | P1 | [high_error_rate.md](high_error_rate.md) |
| `MogoServiceScrapeDown` | P0 | [service_not_ready.md](service_not_ready.md) |
| `MogoServiceNotReady` | P0 | [service_not_ready.md](service_not_ready.md) |
| `MogoLatencyP99High` | P1 | [latency_regression.md](latency_regression.md) |
| `MogoLlmErrorRateHigh` | P1 | [llm_timeout.md](llm_timeout.md) |
| `MogoHostCpuHigh` / `MogoHostMemoryHigh` / `MogoHostDiskLow` | P2 | 见本文 §5 |

故障场景清单（FR-19 要求 ≥5 个，当前 8 个）：

| 场景 | 文档 | 主要关联告警 |
|---|---|---|
| MongoDB 不可达 | [mongodb_unreachable.md](mongodb_unreachable.md) | `MogoServiceNotReady`、`MogoAvailabilityBurnRateFast` |
| LLM provider 超时 | [llm_timeout.md](llm_timeout.md) | `MogoLlmErrorRateHigh`、`MogoLatencyP99High` |
| Redis 抖动 / 阻塞 | [redis_stall.md](redis_stall.md) | `MogoLatencyP99High`、`MogoServiceNotReady` |
| 队列积压 | [queue_backlog.md](queue_backlog.md) | `MogoLatencyP99High`、`MogoServiceNotReady` |
| 证书过期 | [certificate_expired.md](certificate_expired.md) | 无专属规则（监控盲区，见该文 §改进项） |
| 错误率升高 | [high_error_rate.md](high_error_rate.md) | `MogoAvailabilityBurnRate*`、`MogoCriticalPathErrorRateSpike` |
| 延迟劣化 | [latency_regression.md](latency_regression.md) | `MogoLatencyP99High` |
| 服务不就绪 | [service_not_ready.md](service_not_ready.md) | `MogoServiceNotReady`、`MogoServiceScrapeDown` |

## 2. 分级与响应时限（FR-17）

| 级别 | 触达方式 | 响应时限 | 说明 |
|---|---|---|---|
| P0 | IM + 邮件并发，10s 首发，30min 重复 | **≤ 5min** | 用户可见故障或 SLO 快速违约；电话/语音为 Non-Goal（OQ-5），靠双渠道高频重复替代 |
| P1 | IM + 邮件，30s 首发，2h 重复 | **≤ 15min** | 症状明显但未全面不可用 |
| P2 | 不发通知，仅 Alertmanager UI 记录 | **≤ 4h** | 资源阈值等参考信息 |

## 3. 通知里的三个排障入口（FR-18）

每条告警文案固定带三个链接，由 `deploy/alertmanager/templates/mogo.tmpl` 渲染：

1. **Runbook** — 本文或具体场景文档，给处置步骤；
2. **Grafana 面板** — 默认 `mogo-troubleshooting`（服务概览 → 依赖健康 → 慢请求 span 逐层下钻）；
3. **Trace 查询** — 带 `var-trace_id` 参数的排障面板，定位到单条请求链路。

日志侧用 Loki：从 span 里的 `trace_id` 反查日志（Grafana → Explore → Loki →
`{service="chat-api"} | json | trace_id="<id>"`）。

## 4. 静默与抑制

**静默（Silence）** = 计划维护期间压掉预期内的告警，是运行时对象，**不写进配置文件**：

```bash
# 维护窗口（示例：给 chat-api 压 2 小时）
amtool silence add \
  --alertmanager.url=http://localhost:9093 \
  --duration=2h \
  --comment="release-2026.10.25 灰度维护" \
  'service="chat-api"'

# 查看 / 删除
amtool silence query --alertmanager.url=http://localhost:9093
amtool silence expire <silence-id> --alertmanager.url=http://localhost:9093
```

规矩：

- 静默必须带 `--comment` 写明原因与关联发布单，**禁止无注释的长期静默**；
- 静默到期不会自动复查，维护结束请显式 `expire`；
- 确认是**误报**时，正确做法是调 `deploy/prometheus/rules/alert-rules.yml` 的阈值，
  而不是长期静默掩盖。

**抑制（Inhibit）** = 同一根因只打扰一次，配置在 `deploy/alertmanager/alertmanager.yml`
的 `inhibit_rules`，当前三条：

| 源告警 | 被抑制 | 匹配维度 |
|---|---|---|
| 任一 P0 | 同服务同组件的 P1/P2 | `service`, `component` |
| `MogoServiceNotReady` | 同服务 P1/P2 | `service` |
| `MogoServiceScrapeDown` | 同服务的燃烧率/延迟派生告警 | `service` |

## 5. 资源阈值 P2 告警

`MogoHostCpuHigh` / `MogoHostMemoryHigh` / `MogoHostDiskLow` 按 FR-16 **降级为 P2
仅记录**：CPU 95% 本身不是故障，用户可见症状才报警。

按 P2 处理（4h 内）：

1. 先确认是否已有 P0/P1 症状告警同时存在 —— 有的话资源指标只是根因线索，优先处置症状；
2. 无症状时：看 `mogo-gold-signals` 面板确认是否真的吃满，核对是否有异常进程；
3. 磁盘 < 15% 优先清理：容器日志、`prometheus-data` / `loki-data` 卷增长；
4. **如实说明**：`node_*` 指标来自 node-exporter，当前 compose **未部署**该服务，
   这三条规则处于「定义就绪」状态，接入后自动生效（见 `alert-rules.yml` 文件头）。

## 6. Runbook 写作规范

每个场景文档必须包含 5 节（FR-19），缺一不可：

1. **症状** — 看到什么现象/哪条告警，含可直接复制的查询；
2. **影响** — 影响哪些用户面能力，是否影响计费/数据一致性；
3. **根因** — 按概率排序的候选原因 + 每条的判别方法；
4. **恢复步骤** — 可执行命令，标注 `[只读排查]` / `[会改状态]`；
5. **事后复盘模板** — 时间线、根因、影响面、改进项与负责人。

新增场景请同时在本文 §1 的映射表登记，否则告警里的链接会成为死链。
