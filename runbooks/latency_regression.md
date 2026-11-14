# 延迟劣化

> 告警：`MogoLatencyP99High`（P1，P99 > 3s 持续 10m）/ `MogoSloErrorBudgetFastBurn`（P1）
> 关联场景：页面加载慢、接口超时、流式对话首 token 慢

## 1. 症状

- `mogo_http_request_duration_seconds` P99 > 3s（SLO 目标），P50 可能正常；
- 连接数堆积（`mogo_http_inflight_requests` 持续高位）而 CPU 不高 → 典型等下游；
- 用户侧：操作「能用但很慢」，容易在批量场景下演变为超时失败。

[只读排查]

```bash
# 哪个服务/路由的 P99 变差了
curl -s 'http://127.0.0.1:9090/api/v1/query?query=histogram_quantile(0.99,sum by(service,path_template,le)(rate(mogo_http_request_duration_seconds_bucket[5m])))' | head -c 1000

# 积压与并发
curl -s 'http://127.0.0.1:9090/api/v1/query?query=sum by(service)(mogo_http_inflight_requests)' | head -c 500

# 容器资源
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}'
docker compose logs --tail=200 chat-api | grep -iE "slow|took [0-9]+\.?[0-9]*s" | tail -20
```

## 2. 影响

- 延迟 SLO（P99 < 3s）被消耗，即使错误率正常也会烧预算；
- 慢请求占用连接与工作线程，**容易连锁升级为错误率故障**；
- 流式对话体验劣化（首 token 慢比整体慢更被感知）。

## 3. 根因（按概率排序）

1. **下游慢** — MongoDB 慢查询、Redis 抖动、LLM provider 变慢。分别见对应 runbook。
2. **连接池过小 / 排队** — 应用并发上升但池上限不变，请求在池前排队（CPU 不高）。
3. **N+1 查询或全表扫描** — 单接口 P99 高但 QPS 低，看 MongoDB `slowms`。
4. **资源争抢** — 同宿主机上其他容器（含 Prometheus 自身）吃满 CPU/IO。
5. **GC / 大对象** — Python 侧单次请求处理超大 payload（文档预览、长会话历史）。
6. **网关层限速** — nginx `limit_req` 误伤正常流量（表现为排队而非 503）。

## 4. 恢复步骤

```bash
# A. 下游慢 → 转对应 runbook

# B. 池/并发不足 → 临时调大（会改状态，需评估下游承受力）
docker compose exec chat-api printenv | grep -i "POOL\|WORKER\|CONCURRENCY"

# C. 单接口热点 → 网关侧临时限流该路由，保护整体
grep -n "limit_req" deploy/nginx/nginx.conf

# D. 扩容（需确认无状态、可水平扩展）
docker compose up -d --scale chat-api=2 chat-api
```

**禁止**：不要在没定位到慢在哪一段时直接扩机器——若瓶颈是 DB，扩容只会放大压力。

## 5. 验证

```bash
curl -s 'http://127.0.0.1:9090/api/v1/query?query=histogram_quantile(0.99,sum by(le)(rate(mogo_http_request_duration_seconds_bucket[5m])))'
curl -s 'http://127.0.0.1:9090/api/v1/query?query=mogo:slo:latency:p99_seconds'
# 期望 P99 < 3.0 且持续 10m
```

## 6. 事后复盘模板

```markdown
### 复盘：延迟劣化（YYYY-MM-DD）
- 发现 / 恢复时间，P99 峰值与回落值：
- 慢在哪一段（入口 / 应用 / DB / LLM / 网关排队）？证据：
- 是否已影响错误率（是否发生超时转 5xx）：
- 改进项：
  - [ ] 慢查询索引补齐（列出具体 collection + 查询）
  - [ ] 连接池与下游容量联动配置
  - [ ] 首 token 延迟单独设指标与阈值
```
