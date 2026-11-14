# 服务不就绪 / 探活失败

> 告警：`MogoServiceNotReady`（P0，`/ready` 连续 5 次非 200）/ `MogoServiceScrapeDown`（P0，`up == 0` 持续 2m）
> 关联场景：服务无法接收流量、容器反复重启、发布卡住

## 1. 症状

- `curl /ready` 非 200 或超时；`/health/live` 可能仍 200（**liveness ≠ readiness**）；
- `up{job=...}` 为 0（Prometheus 抓不到 `/metrics`）；
- `docker compose ps` 显示 `Restarting` / `unhealthy`；
- 用户侧：网关 502/503，或流量被摘除后请求落到不存在的实例。

[只读排查]

```bash
docker compose ps
docker compose logs --tail=200 <服务名>

# 区分三种失败：
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health/live    # 进程活着吗
curl -s http://127.0.0.1:8000/ready | head -c 400                            # 依赖就绪吗
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/metrics       # 抓取端点通吗

# Prometheus 侧
curl -s 'http://127.0.0.1:9090/api/v1/query?query=up{job="chat-api"}'
curl -s 'http://127.0.0.1:9090/api/v1/targets?state=active' | head -c 600
```

## 2. 影响

- 流量被摘除 → 该实例**全部能力不可用**（比单接口故障更彻底）；
- 若所有实例同时不就绪，等于全站不可用；
- 反复重启会放大依赖压力（重连风暴）。

## 3. 根因（按概率排序）

1. **依赖不就绪** — `/ready` 里 `mongodb` / `redis` 为 false。转
   `mongodb_unreachable.md` 或 `redis_stall.md`。这是最常见原因。
2. **启动自检未完成** — 服务在 lifespan 中做迁移/预热，超过探活超时。
3. **进程崩溃循环** — 启动即异常（配置缺失、端口占用、权限不足）。
   特征：日志只有启动头部就结束。
4. **端口/网络错配** — compose 端口映射变更、监听地址是 `127.0.0.1` 而非 `0.0.0.0`。
5. **`/metrics` 挂载失败** — 路由冲突导致 ASGI 启动异常（影响 `up`，但不一定影响 `/ready`）。
6. **探活配置过严** — `timeoutSeconds` 太小、`failureThreshold` 太低，偶发抖动即摘除。

## 4. 恢复步骤

```bash
# A. 依赖故障 → 转对应 runbook（最常见）

# B. 崩溃循环 → 看真实异常后修配置（不改数据）
docker compose logs --tail=80 <服务名>
docker compose restart <服务名>

# C. 单实例异常 → 重启该服务，不动其他
docker compose up -d --no-deps -u <服务名>

# D. 抓取失败但服务正常 → 检查 Prometheus targets 与网络
curl -s http://127.0.0.1:9090/api/v1/targets?state=active | python3 -m json.tool | grep -E '"health"|"lastError"' | head
```

**禁止**：不要把 `liveness` 探针也指向 `/ready`——依赖抖动会让容器被反复杀死，
把小故障放大成雪崩。

## 5. 验证

```bash
curl -s http://127.0.0.1:8000/ready | head -c 400        # 200 且各依赖 true
curl -s 'http://127.0.0.1:9090/api/v1/query?query=up{job="chat-api"}'   # 1
docker compose ps                                        # healthy
```

## 6. 事后复盘模板

```markdown
### 复盘：服务不就绪（YYYY-MM-DD）
- 发现 / 恢复时间，摘除的实例数，是否有全站影响：
- 触发原因（依赖 / 启动自检 / 崩溃 / 端口 / 探针阈值）：
- 探针设计是否合理（liveness 与 readiness 是否混用）：
- 改进项：
  - [ ] `/ready` 各依赖项独立超时，避免一个慢依赖拖垮整体判定
  - [ ] 启动预热与探活超时对齐
  - [ ] 容器 OOMKilled / 重启次数纳入告警
```
