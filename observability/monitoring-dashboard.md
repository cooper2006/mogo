# 监控看板配置指南（023 · US3）

> 面板定义在 `deploy/grafana/provisioning/dashboards/`，数据源在
> `deploy/grafana/provisioning/datasources/datasources.yml`。全部通过 provisioning
> 自动加载，**没有需要手点的步骤**——手点出来的看板在重建环境时会丢。

## 1. 四个看板各管什么

| 看板 | uid | 面板 | 什么时候看 |
|---|---|---|---|
| **黄金四信号** | `mogo-gold-signals` | 4 | 每天扫一眼；四信号是"服务健不健康"的最小充分集 |
| **SLO 总览** | `mogo-slo-overview` | 8 | 周会/复盘；回答"预算还剩多少、哪个 SLO 在流血" |
| **业务指标** | `mogo-business-metrics` | 8 | 产品侧异常（"没人用了"和"挂了"要区分开） |
| **排障看板** | `mogo-troubleshooting` | 10 | 告警来了第一站；四层下钻到具体路由与 trace |

入口：`http://localhost:3001/d/<uid>`（地址由 `GRAFANA_*` 配置决定）。

## 2. 黄金四信号（`mogo-gold-signals`）

| 面板 | 指标 | 读法 |
|---|---|---|
| Traffic (requests/s) | `sum(rate(mogo_http_requests_total[1m]))` | 突降先怀疑"没流量"（LB/网关/证书），而不是"服务变好了" |
| Latency P99 (s) | `histogram_quantile(0.99, ...)` | P99 抬升但 QPS 不变 ⇒ 单点变慢；两者同时升 ⇒ 容量问题 |
| Error Rate | `errors / requests` | 与 SLO 用**同一个**记录规则口径，不要另算 |
| Saturation (inflight) | inflight 并发 | 这是"还能不能接活"的唯一信号；打满后延迟会跳变而非线性上升 |

只看这四个能覆盖绝大多数故障的**发现**；定位要靠排障看板。

## 3. SLO 总览（`mogo-slo-overview`）

8 个面板两两成对（实际值 vs 目标）：可用性错误率/目标、LLM 错误率/目标、
P99/目标、燃烧率/预算剩余。

读法要点：

- **燃烧率 > 1 就是在流血**；> 14.4 是 P0（见 [slo-definition.md](slo-definition.md) §3）；
- **预算剩余**是把 30 天窗口折算的近似值（记录规则里按 5m 速率外推），
  它适合看趋势，不适合当法务级账单；
- 目标线（`mogo:slo:availability:target` 等）是**记录规则**而非面板硬编码，
  改目标只改一处。

## 4. 排障看板（`mogo-troubleshooting`）：四层下钻

```
第 1 层 服务概览      哪个服务坏（按 service 的请求/错误/延迟）
   ↓ 选一个服务
第 2 层 依赖健康      inflight 是否打满、LLM provider 错误率与 P95
   ↓ 看是"外部依赖慢"还是"自己慢"
第 3 层 热点路由      按 path_template 的错误率与 P99 —— 具体哪个接口
   ↓ 拿到 trace_id
第 4 层 Trace 下钻    把 trace_id 填进变量框 → 点链接跳 Tempo
```

**为什么按 `path_template` 而不是 `path`**：`/sessions/123/messages` 这种路径直方图
会炸成无限多序列（高基数），把 Prometheus 打爆。模板化后每个路由一条序列。

**变量 `trace_id`（textbox）**：从日志或告警里复制 `trace_id` 填进去，第 4 层面板
就会生成指向 Tempo 的链接。这是"指标 → 追踪"的桥，不需要人工拼 URL。

## 5. 业务指标（`mogo-business-metrics`）

LLM Calls Rate / Tokens Used Rate / Messages Sent / Active Sessions /
Doc Parse Requests / Admin Sessions / LLM Latency / Doc Parse Latency。

用途是区分**三种"看起来都掉零"**：

| 现象 | 指标特征 | 常见原因 |
|---|---|---|
| 全站不可用 | 请求速率同时掉，错误率或 `up` 异常 | 网关/证书/LB |
| 只有 LLM 不可用 | 请求还在，LLM calls 掉、错误率升 | provider 故障（见预案 §2） |
| 真的没人用 | 请求与错误都正常下降 | 产品/运营，不是故障 |

## 6. 数据源与 provisioning

```yaml
# deploy/grafana/provisioning/datasources/datasources.yml（要点）
- name: Prometheus   type: prometheus   url: http://prometheus:9090
- name: Loki         type: loki         url: http://loki:3100
- name: Tempo        type: tempo        url: http://tempo:3200
```

三条原则：

1. **看板里不写死数据源 uid**，用 `${DS_*}` 或默认数据源，换环境不用改 JSON；
2. **时间段默认 `now-6h`**，不要 `now-30d`：长窗口面板首次加载会拖慢整个 Grafana；
3. **面板命名带单位**（`P99 (s)`、`(req/s)`），同一个数字带错单位比没有还糟。

## 7. 加一个新面板的检查清单

- [ ] 查询基于**记录规则**或低基数指标（带 `le`/`service`/`path_template` 标签）
- [ ] 不用 `irate` 做长窗口（只有最后两点，长窗口会骗人）
- [ ] 阈值线写进面板 JSON（可视化），但**告警逻辑只在 `alert-rules.yml`**
- [ ] 确认 JSON 能 `json.load` 且 uid 唯一
- [ ] `python -m pytest deploy/tests -q -k grafana` 通过

## 8. 验证

```bash
# 面板 JSON 合法性 + uid 唯一 + 关键面板存在
python3 - <<'PY'
import json, pathlib
seen = set()
for f in pathlib.Path("deploy/grafana/provisioning/dashboards").glob("*.json"):
    d = json.loads(f.read_text())
    assert d["uid"] not in seen, f"uid 重复：{d['uid']}"
    seen.add(d["uid"])
    print(f"{f.name:22} {d['uid']:26} panels={len(d.get('panels') or [])}")
PY

# 数据源是否 provisioning 成功（容器内）
curl -s -u admin:admin http://localhost:3001/api/datasources | python3 -m json.tool | grep '"name"'
```

**端到端下钻剧本**（Phase 8，T117）把「看板可下钻」从「文件存在」升级为「真能查到」：

```bash
bash scripts/drill/inject_dependency_fault.sh --grafana-url http://localhost:3000
```

剧本会请求 `GET /api/dashboards/uid/mogo-troubleshooting`，期望 `200`；同时把排障动线
跑一遍——故障注入后从「依赖健康」层看到 `mogo_circuit_breaker_state{dependency=...,state="open"}=1`，
再按 trace 进入具体 span、按 `trace_id` 反查日志。任一环断了，剧本以 `1` 退出。

`scripts/testlib/fake_fault_env.py` 提供不带 Grafana 的替身，用于在 CI 里验证剧本
「缺 Grafana 时标 `skip` 而不是假通过」的行为。
