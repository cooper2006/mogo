# LLM provider 超时

> 告警：`MogoLlmErrorRateHigh`（P1）/ `MogoLatencyP99High`（P1）
> 关联场景：对话无响应、回复截断、流式输出卡住

## 1. 症状

- `mogo_chat_llm_calls_total{status="error"}` 增速上升，错误率 > 1%；
- chat-api 日志出现 `TimeoutError` / `httpx.ReadTimeout` / `ConnectTimeout`；
- 用户侧：发送消息后长时间无首 token，或最终报「服务繁忙」；
- P99 延迟 > 3s（流式接口首 token 延迟可能更高）。

[只读排查]

```bash
# 错误率与耗时（Prometheus）
curl -s 'http://127.0.0.1:9090/api/v1/query?query=sum(rate(mogo_chat_llm_calls_total{status="error"}[5m]))/sum(rate(mogo_chat_llm_calls_total[5m]))'
curl -s 'http://127.0.0.1:9090/api/v1/query?query=histogram_quantile(0.99,sum by(le)(rate(mogo_chat_llm_request_duration_seconds_bucket[5m])))'

docker compose logs --tail=300 chat-api | grep -iE "timeout|timed out|provider|failover" | tail -40
```

## 2. 影响

- 对话能力降级（多数请求 5xx 或长时间挂起）；
- 若流式请求已开始输出，可能出现**半截回复**，前端需按 `finish_reason` 兜底；
- token 已计费但无有效产出 → 用户投诉与成本浪费。

## 3. 根因（按概率排序）

1. **provider 侧限流（429）/ 过载（503）** — 错误集中在单一 provider，
   `status` label 分布明显偏斜。
2. **网络链路问题** — 出口 DNS 解析、代理、TLS 握手超时；`httpx.ConnectTimeout` 为主。
3. **本侧超时配置过紧** — FR-22 三层超时（入口 30s > 下游 10s > 单次 LLM/DB 5s）。
   若单次 LLM 超时被调到低于 provider 的 P99，会人为制造超时。
4. **007 failover 未生效或误判** — 007 的 `llm/resilience/failover.py` 只应把
   429/5xx/超时判为可重试（FR-23）；401/403 必须立即失败、不重试、不 failover
   （否则会拿坏凭据在多个 provider 上连环失败）。
5. **流式连接被中间层切断** — nginx gateway 的 `proxy_read_timeout` 小于流式时长。

## 4. 恢复步骤

```bash
# A. 单一 provider 故障 → 切备用 provider（配置项，不改代码）
grep -n "LLM_PROVIDER\|LLM_FALLBACK" .env
# 修改后仅重启 chat-api，避免影响 admin-api
docker compose up -d --no-deps -u chat-api

# B. 全 provider 超时 → 先确认出口网络
docker compose exec chat-api python - <<'PY'
import httpx
r = httpx.get("https://api.deepseek.com", timeout=5)
print(r.status_code)
PY

# C. 网关超时 → 调整 nginx 流式超时（会改状态）
grep -n "proxy_read_timeout\|proxy_buffering" deploy/nginx/nginx.conf
```

**禁止**：不要在故障期间「重试次数调大 + 超时调长」当解法——会把入口请求
拖过 30s 预算，雪崩到网关。

## 5. 验证

```bash
curl -s 'http://127.0.0.1:9090/api/v1/query?query=sum(rate(mogo_chat_llm_calls_total{status="error"}[5m]))/sum(rate(mogo_chat_llm_calls_total[5m]))'
# 期望回落到 < 1%；同时确认 P99 回落
curl -s http://127.0.0.1:9093/api/v2/alerts | head -c 500
```

## 6. 事后复盘模板

```markdown
### 复盘：LLM provider 超时（YYYY-MM-DD）
- 发现 / 恢复时间，总时长，影响的会话数：
- provider 维度：哪个 provider、错误码分布（429/503/timeout 各多少）：
- failover 是否按预期切换？切换耗时？是否误重试了 401/403：
- 超时层级是否被穿透（入口 30s 是否被打满）：
- 成本影响：失败请求的 token 消耗估算：
- 改进项：
  - [ ] provider 健康度指标加入 dashboard
  - [ ] 流式首 token 超时单独设阈值
  - [ ] 降级文案与前端重试策略对齐
```
