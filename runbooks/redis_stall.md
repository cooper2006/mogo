# Redis 抖动 / 阻塞

> 告警：`MogoLatencyP99High`（P1）/ `MogoServiceNotReady`（P0）
> 关联场景：限流计数异常、缓存击穿、任务派发延迟

## 1. 症状

- 请求延迟整体抬升但错误率不高（缓存未命中→回源 DB）；
- `/ready` 的 `dependencies.redis` 间歇性为 `false`；
- 日志出现 `redis.exceptions.TimeoutError` / `ConnectionError` / `BusyLoadingError`；
- 限流/配额判定异常：本应 429 的请求放行，或正常请求被误限。

[只读排查]

```bash
docker compose ps redis
docker compose logs --tail=200 redis | grep -iE "loading|oom|maxmemory|fork" | tail -30

# 关键：区分「网络慢」与「Redis 自己卡住」
docker compose exec redis redis-cli INFO stats | grep -E "instantaneous_ops|rejected|expired"
docker compose exec redis redis-cli --latency-history -i 1
docker compose exec redis redis-cli slowlog get 10
docker compose exec redis redis-cli INFO memory | grep -E "used_memory_human|maxmemory_human|maxmemory_policy"
```

## 2. 影响

| 依赖点 | 抖动时的表现 |
|---|---|
| 限流/配额（001 gatekeeper 执行层） | 判定失真：要么放行过量、要么误 429 |
| 会话/消息缓存 | 击穿回源，MongoDB 压力上升，延迟连带恶化 |
| 任务队列派发（document-worker） | 入队变慢，解析任务排队 |
| 短期会话状态 | 可能丢状态，用户需重试 |

## 3. 根因（按概率排序）

1. **内存打满触发淘汰/拒绝写** — `maxmemory-policy` 为 `noeviction` 时写失败并报
   `OOM command not allowed`；有淘汰策略但热点被淘汰 → 命中率骤降。
2. **RDB/AOF fork 阻塞** — `latest_fork_usec` 大（> 200ms），BGSAVE 期间主线程停顿。
   特征：延迟尖峰周期性出现，与 `rdb_bgsave_in_progress` 相关。
3. **慢命令** — `KEYS *`、大 key 的 `HGETALL`、`SMEMBERS` 打在百万级集合上；
   用 `slowlog get` 确认。
4. **网络/连接池** — 客户端连接数打满 `maxclients`，或 DNS 抖动导致重连风暴。
5. **主机资源争抢** — CPU steal 高、磁盘 IO 饱和（AOF everysec 写盘跟不上）。

## 4. 恢复步骤

```bash
# A. 内存打满 → 确认策略后扩容或清理（清理会改状态，先确认 key 归属）
docker compose exec redis redis-cli CONFIG GET maxmemory-policy
docker compose exec redis redis-cli --bigkeys          # [只读] 找大 key
# 禁止在生产直接 FLUSHALL；按前缀精确删除，例如过期会话：
# docker compose exec redis redis-cli --scan --pattern 'sess:*' | head -1000 | xargs -r -n 50 docker compose exec -T redis redis-cli DEL

# B. fork 阻塞 → 临时关闭快照（会改状态，需确认持久化策略）
docker compose exec redis redis-cli CONFIG SET save ""

# C. 连接数打满
docker compose exec redis redis-cli CONFIG GET maxclients
docker compose exec redis redis-cli INFO clients

# D. 应用侧兜底：降级为直连 DB（会放大 DB 压力，谨慎）
docker compose restart chat-api     # 只重启受影响服务，不整体重启
```

**禁止**：不要用 `KEYS *` 排查（本身就会把 Redis 打挂），用 `--scan`。

## 5. 验证

```bash
docker compose exec redis redis-cli --latency        # 期望 < 1ms
docker compose exec redis redis-cli INFO stats | grep keyspace_hits
curl -s http://127.0.0.1:8000/ready | head -c 300    # redis=true
curl -s 'http://127.0.0.1:9090/api/v1/query?query=histogram_quantile(0.99,sum by(le)(rate(mogo_http_request_duration_seconds_bucket[5m])))'
```

## 6. 事后复盘模板

```markdown
### 复盘：Redis 抖动（YYYY-MM-DD）
- 发现 / 恢复时间，总时长：
- 现象：延迟上升 / 命中率下降 / 误 429（勾选并给数字）：
- Redis 侧证据：slowlog 前 3 条、latest_fork_usec、maxmemory 使用率：
- 是否发生缓存击穿？回源后 MongoDB 负载变化：
- 改进项：
  - [ ] 大 key 治理与 key 命名规范
  - [ ] maxmemory 水位告警（当前仅 P2 记录，是否需升级）
  - [ ] 限流在 Redis 不可用时的降级策略（fail-open 还是 fail-close，需产品确认）
```
