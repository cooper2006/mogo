# SLO 定义与错误预算（023 · US3）

> 规则实现：`deploy/prometheus/rules/slo_recording.yml`（记录规则）与
> `deploy/prometheus/rules/alert-rules.yml`（燃烧率告警）。本文说明**口径与决策**，
> 改目标必须同时改这两份 YAML 与本文。
>
> 灾备侧的 RTO/RPO 不在这里，见 [rto-rpo.md](rto-rpo.md)。

## 1. SLI：先把「怎么算」定死

| SLI | 计算式（PromQL 口径） | 分母的边界（容易搞错） |
|---|---|---|
| 可用性 | `sum(rate(mogo_http_errors_total[5m])) / sum(rate(mogo_http_requests_total[5m]))` | 只统计**服务端 5xx**；4xx 是客户端错误，不计入不可用（否则攻击者可以随便把 SLO 打穿） |
| 延迟 P99 | `histogram_quantile(0.99, sum(rate(mogo_http_request_duration_seconds_bucket[5m])) by (le))` | 按全部请求算，不按成功请求算——慢的 5xx 也是用户感知到的坏体验 |
| LLM 错误率 | `sum(rate(mogo_chat_llm_calls_total{status="error"}[5m])) / sum(rate(mogo_chat_llm_calls_total[5m]))` | 以**调用次数**为分母而非请求数；一次请求可能触发多次 LLM 调用 |

三条 SLI 都已落成记录规则（`mogo:slo:availability:error_rate`、`mogo:slo:latency:p99_seconds`、
`mogo:slo:llm:error_rate`），看板与告警只引用记录规则，不各自写一遍表达式——
**同一条 SLI 有两个实现，迟早会给出两个数字**。

## 2. SLO 目标

| SLO | 目标 | 30 天错误预算 | 换算成不可用时间（月） |
|---|---|---|---|
| 可用性 | **99.9%** | 0.1% | **约 43 分钟** |
| 延迟 P99 | **< 3s** | 1% 的请求可超 3s | 约 21.6 分钟等效 |
| LLM 错误率 | **< 1%** | 1% 调用失败 | 不直接映射为用户不可用 |

为什么是 99.9% 而不是 99.99%：99.99% 的月预算是 4.3 分钟，一次发布回滚就吃光，
团队会被迫在大半夜做无价值的救火。**SLO 必须定在团队能兑现的水平**，
否则它退化成"永远红着的看板"。

## 3. 错误预算与燃烧率

燃烧率 burn rate = 实际错误率 / 预算错误率。可用性预算错误率 = 0.1%，
所以 `burn_rate = error_rate / 0.001`（记录规则 `mogo:slo:availability:burn_rate`）。

| 燃烧率 | 含义 | 1 小时消耗的月预算 | 告警 |
|---|---|---|---|
| 1 | 正好 30 天烧完 | 0.14% | 无（这是"正常用完预算"的速度） |
| 6 | 5 天烧完 | 0.83% | `MogoAvailabilityBurnRateMedium`（P1，15m） |
| 14.4 | 约 50 小时烧完 | 2% | `MogoAvailabilityBurnRateFast`（P0，2m） |

**多窗口多燃烧率**（fast 1h/5m、medium 6h/30m、slow 3d/6h）的意义：短窗口灵敏但吵，
长窗口稳但迟钝；两者**同时**超阈值才告警，能挡住毛刺又能抓住持续劣化。
只用短窗口会被瞬时抖动打爆手机，只用长窗口会让 P0 迟到半小时。

## 4. 告警与 SLO 的对应关系

| 告警 | 类型 | 触发条件 | 值班动作 |
|---|---|---|---|
| `MogoAvailabilityBurnRateFast` | 症状（P0） | 5m 与 1h 均 > 14.4x | 立刻看排障看板，按 `high_error_rate.md` 走 |
| `MogoAvailabilityBurnRateMedium` | 症状（P1） | 30m 与 6h 均 > 6x | 当班内定位根因 |
| `MogoAvailabilityBurnRateSlow` | 症状（P1） | 6h 与 3d 均 > 1x | 排进迭代，查"慢性漏血" |
| `MogoLatencyP99High` | 症状（P1） | P99 > 3s 持续 | 看 trace 找慢跳 |
| `MogoLlmErrorRateHigh` | 症状（P1） | LLM 错误率 > 1% | 查 provider 熔断/额度 |
| `MogoServiceScrapeDown` | 直接（P0） | `up == 0` | 服务可能已死，先确认进程 |
| `MogoServiceNotReady` | 直接（P0） | `probe_success == 0` | **定义就绪**：需 blackbox-exporter，见 §6 |
| `MogoHost{Cpu,Memory,High}` / `MogoHostDiskLow` | 资源（P2） | 阈值 | **定义就绪**：需 node-exporter，见 §6 |

原则：**P0/P1 只报"用户正在受苦"**（症状类），资源类一律 P2。资源告警进 P0 会导致
"CPU 高但用户无感"的告警抢占真正的故障处理时间。

## 5. 抑制与分级路由

- 抑制规则 3 条（`deploy/alertmanager/`）：ScrapeDown 抑制同服务派生的症状告警；
  上游不可用抑制下游依赖告警；维护窗口抑制全部。
- 路由分级：P0 → IM + 电话式升级（@值班 + 15 分钟未响应升级）、P1 → IM + 邮件、
  P2 → 仅 IM（工作时段）。
- 每条 P0/P1 的 `annotations` 必须带 `runbook_url`（指向 `docs/runbooks/` 真实文件）、
  `dashboard_url`、`trace_url`——这三者是"点开就能干活"的最低要求。

## 6. 已知缺口（如实标注，不假装已具备）

| 缺口 | 影响 | 现状 |
|---|---|---|
| 未部署 node-exporter | `MogoHost{Cpu,Memory,High}`、`MogoHostDiskLow` 不会产生序列 | 规则**定义就绪**，接入即生效；当前不会误报 |
| 未部署 blackbox-exporter | `MogoServiceNotReady` 无数据 | 同上；现在真正生效的可用性信号是 `MogoServiceScrapeDown`（`up == 0`） |
| 无真实 Alertmanager 环境（T074/T075） | 通知链路未端到端验证 | 已做静态校验（18 项告警配置测试），真实投递待环境 |

缺口不影响「指标 + 记录规则 + 燃烧率告警」这条主链路可用；但任何 SLO 报告都要说明
"资源类告警尚未生效"，否则会误以为监控已全覆盖。

## 7. SLO 违背（budget exhausted）怎么办

1. **冻结功能发布**，只允许修稳定性/可观测性的改动，直到预算恢复到正；
2. 复盘必须回答「哪类错误、从哪个服务、从什么时候开始」，用记录规则而不是翻日志；
3. 若预算因**预期内**事件耗尽（如大促压测），提前记录「预算豁免窗口」，
   并在复盘里说明豁免理由——事后补票不算。

## 8. 验证

```bash
# 记录规则语法（有 promtool 时）
promtool check rules deploy/prometheus/rules/slo_recording.yml

# 静态回归（无需 Prometheus 环境）
python -m pytest deploy/tests/test_alerting_us4.py -q

# 运行时抽查：记录规则是否产出序列
curl -s 'http://localhost:9090/api/v1/query?query=mogo:slo:availability:error_rate' | python3 -m json.tool
```

**端到端剧本**（Phase 8，T116/T117）不只是查指标，还把「记录规则是否真的烧出告警」打通：

```bash
# 全链路验证：规则已加载（期望 ≥10 条 Mogo 告警规则）且 SLO 记录规则有值
bash scripts/verify_e2e_observability.sh
# 故障注入验证：熔断打开 → 快速失败 → 告警 firing
bash scripts/drill/inject_dependency_fault.sh
```

剧本把 SLO 与告警的接线当成**可执行断言**而不是口头约定：`MogoServiceNotReady`、
`MogoCriticalPathErrorRateSpike` 这些规则必须在故障注入后真的出现在 Alertmanager 里，
否则视为失败（退出码 `1`）。环境不具备时返回 `2`，同样不算通过。
