# Quickstart: Performance & Scalability Hardening (026)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md)

本文件说明如何**启用并验证**性能与扩展性加固。

---

## 1. 前置条件

### 1.1 开发环境

- Docker Compose 环境已启动（`docker compose up -d`），MongoDB + Redis 可用
- Python 3.13 + `motor`（MongoDB）+ `redis`（Redis）已安装
- Node.js 20+ + pnpm（前端）
- `locust>=2.20`（压测主工具）：`pip install locust`
- `k6`（补充压测）：`brew install k6` 或 `go install go.k6.io/k6/v2@latest`
- `lighthouse`（前端性能检测）：`npx lighthouse` 或 `brew install lighthouse`

### 1.2 性能测试环境

- **隔离环境**：性能测试应在独立环境运行，不与生产/开发共享数据
- **数据准备**：至少准备 100 个租户、1000 个会话、10000 条消息（用于压测真实场景）
- **网络环境**：本地（localhost）或同网段压测，排除网络延迟干扰

### 1.3 配置文件

- `benchmarks/perf_baselines/baselines.yaml`：性能预算定义（需 `/speckit-clarify` 确认阈值）
- `services/chat-api/app/core/db.py`：连接池配置（`maxPoolSize`/`minPoolSize`/`maxIdleTimeMS`）
- `services/chat-api/app/cache/`：缓存层配置（TTL/淘汰策略/容量上限）

---

## 2. US1 — 性能基线与度量

### 2.1 启用基线采集

```bash
# 确保 perf 中间件已接入（Phase 2 T012）
# chat-api / admin-api / document-parser 的 main.py 中注册 perf 中间件
```

### 2.2 采集基线

```bash
# 运行压测采集基线（locust）
cd benchmarks/locust
locust -f locustfile_chat.py --headless \
  --users 50 --spawn-rate 5 --run-time 60s \
  --host http://localhost:8000 \
  --csv benchmarks/perf_baselines/baseline_chat

locust -f locustfile_doc.py --headless \
  --users 50 --spawn-rate 5 --run-time 60s \
  --host http://localhost:8000 \
  --csv benchmarks/perf_baselines/baseline_doc
```

### 2.3 验证预算检查

```bash
# 检查基线是否满足预算
cd benchmarks
python -m perf_budget_check --config perf_baselines/baselines.yaml
```

期望：输出各端点 P95 实际值 vs 预算值，通过/失败状态。

### 2.4 验证 CI 回归判定

```bash
# 运行回归判定（Phase 2 T011）
cd benchmarks
python -m perf_budget_check --regression \
  --new-baseline perf_baselines/baseline_current.json \
  --old-baseline perf_baselines/baseline_previous.json
```

期望：P95 超阈值（+20%）标记为回归，退出码非 0（CI 中断）。

---

## 3. US2 — 数据库性能

### 3.1 启用 slow_query_log

```bash
# 修改 services/chat-api/app/core/db.py 或 config
export MONGODB_SLOW_QUERY_LOG_THRESHOLD_MS=100  # 默认 100ms

# 重启 chat-api
docker compose restart chat-api
```

### 3.2 查看慢查询

```bash
# 通过 MongoDB shell 查看慢查询
mongosh --eval '
  db.getSiblingDB("mogo_dev").slow_queries.find(
    { "durationMs": { $gt: 100 } },
    { "command": 1, "durationMs": 1, "collection": 1 }
  ).pretty()
'

# 或通过 API 查询（Phase 3 T015）
curl http://localhost:8000/api/admin/performance/slow-queries \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.queries[] | {collection, durationMs, command}'
```

### 3.3 验证连接池配置

```bash
# 检查连接池配置（Phase 3 T014）
curl http://localhost:8000/api/admin/performance/pool-stats \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.pool | {maxPoolSize, minPoolSize, currentSize, pending}'
```

期望：`currentSize` < `maxPoolSize` * 80%（峰值利用率合理）。

### 3.4 验证索引覆盖率

```bash
# 检查索引覆盖率（Phase 3 T018）
curl http://localhost:8000/api/admin/performance/index-coverage \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.coverage_percent'
```

期望：覆盖率 > 95%。

---

## 4. US3 — 缓存与减少冗余计算

### 4.1 启用缓存层

```bash
# 确保 cache/manager.py 已接入（Phase 4 T023）
# 热点数据（session/config/permission/token）自动接入缓存
```

### 4.2 验证缓存命中率

```bash
# 检查缓存命中率（Phase 4 T030）
curl http://localhost:8000/api/admin/performance/cache-stats \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.cache | {hitRate, totalRequests, hits, misses}'
```

期望：`hitRate` > 0.80（80%）。

### 4.3 验证穿透防护

```bash
# 测试缓存穿透（Phase 4 T025）
# 请求不存在的资源，应返回空值缓存（不打到 DB）
curl http://localhost:8000/api/sessions/nonexistent-id \
  -H "Authorization: Bearer $TOKEN"
# 期望：返回 404（或空值），DB 无对应查询
```

### 4.4 验证击穿防护

```bash
# 测试缓存击穿（Phase 4 T026）
# 并发请求同一热点键，应仅单请求重建，其他等待或返回旧值
for i in {1..20}; do
  curl http://localhost:8000/api/sessions/hot-session-id \
    -H "Authorization: Bearer $TOKEN" &
done
wait
# 期望：仅 1 次 DB 查询，其余 19 次命中缓存或等待
```

---

## 5. US4 — 前端性能

### 5.1 构建前端

```bash
# admin-web 构建
cd apps/admin-web
pnpm build

# user-web 构建
cd apps/user-web
pnpm build
```

### 5.2 验证包体积

```bash
# 检查首屏包体积（Phase 5 T035）
# admin-web: ≤ 500KB gzip
# user-web: ≤ 300KB gzip
npx vite-bundle-visualizer apps/admin-web/dist/index.html
npx vite-bundle-visualizer apps/user-web/dist/index.html
```

### 5.3 验证 Web Vitals

```bash
# Lighthouse 自动检测（Phase 5 T033）
npx lighthouse http://localhost:5173 \
  --output=json \
  --output-path=/tmp/lighthouse.json
jq '.categories.performance.score' /tmp/lighthouse.json
jq '.audits[''largest-contentful-paint''].displayValue' /tmp/lighthouse.json
jq '.audits[''total-blocking-time''].displayValue' /tmp/lighthouse.json
jq '.audits[''cumulative-layout-shift''].displayValue' /tmp/lighthouse.json
```

期望：LCP ≤ 2.5s、TTI ≤ 3.8s、CLS ≤ 0.1。

### 5.4 验证代码分割

```bash
# 检查路由级懒加载（Phase 5 T034）
# 构建后应生成多个 chunk 文件
ls apps/admin-web/dist/assets/*.js | wc -l  # 期望 > 5
# 首屏仅加载必需 chunk
grep -o 'src="[^"]*"' apps/admin-web/dist/index.html | head -10
```

### 5.5 验证虚拟列表

```bash
# 加载大数据集页面，检查仅渲染可视区 DOM 节点
# （Phase 5 T039）
# 通过浏览器 DevTools 检查：
# 1. 打开包含 > 1000 项列表的页面
# 2. Elements 面板检查列表容器子节点数
# 期望：子节点数 ≈ 可视区节点数（如 20-50），而非 1000+
```

---

## 6. US5 — 扩展性与容量规划

### 6.1 水平扩展压测

```bash
# 启动 3 个 chat-api 实例（Phase 6 T041）
docker compose up -d chat-api chat-api-2 chat-api-3

# 压测：10 并发
locust -f benchmarks/locust/locustfile_chat.py --headless \
  --users 10 --spawn-rate 2 --run-time 120s \
  --host http://localhost:8000 \
  --csv /tmp/3-replica-test

# 对比：1 实例 vs 3 实例吞吐
# 期望：3 实例吞吐 ≈ 1 实例 × 3（线性增长）
```

### 6.2 限流验证

```bash
# 验证限流（Phase 6 T042）
# 超过 1000 rps 时返回 429 + Retry-After
for i in {1..2000}; do
  curl -s -o /dev/null -w "%{http_code}\n" \
    http://localhost:8000/api/chat \
    -H "Authorization: Bearer $TOKEN" &
done
wait | sort | uniq -c
# 期望：部分请求返回 429
```

### 6.3 资源监控

```bash
# 检查 Prometheus 指标（Phase 6 T044）
curl http://localhost:8000/metrics | grep -E "^mogo_" | head -20
# 期望：CPU/内存/IO/磁盘指标可查
```

### 6.4 容量模型验证

```bash
# 读取容量模型（Phase 6 T049）
cat benchmarks/capacity_model.md

# 验证：给定 100 并发 → 预测所需实例数与资源
# 期望：容量模型可预测，与压测结果一致
```

### 6.5 压测完整场景

```bash
# 完整压测套件（Phase 6 T045-T048）
cd benchmarks/locust

# 对话场景
locust -f locustfile_chat.py --headless \
  --users 100 --spawn-rate 10 --run-time 120s \
  --host http://localhost:8000 \
  --csv results/chat

# 文档解析场景
locust -f locustfile_doc.py --headless \
  --users 50 --spawn-rate 5 --run-time 120s \
  --host http://localhost:8000 \
  --csv results/doc

# 搜索场景
locust -f locustfile_search.py --headless \
  --users 100 --spawn-rate 10 --run-time 120s \
  --host http://localhost:8000 \
  --csv results/search

# 鉴权场景
locust -f locustfile_auth.py --headless \
  --users 200 --spawn-rate 20 --run-time 60s \
  --host http://localhost:8000 \
  --csv results/auth

# k6 冒烟测试
k6 run benchmarks/k6/smoke.js \
  --out json=results/k6-smoke.json
```

---

## 7. 验证清单

| # | 验证项 | 期望 | 对应 FR |
|---|---|---|---|
| 1 | 关键端点 P95 基线 | 落库可查 | FR-1 |
| 2 | 吞吐按并发级别 | RPS/TPS 可查 | FR-2 |
| 3 | 外部依赖耗时占比 | DB/Redis/LLM/外部 API 拆分 | FR-3 |
| 4 | 性能预算 CI 检查 | 超阈值标记回归，CI 中断 | FR-4, FR-5 |
| 5 | 慢查询 < 100ms | 超阈值告警 | FR-6 |
| 6 | 索引覆盖率 | > 95% | FR-8 |
| 7 | 连接池利用率 | 峰值 ≤ 80% | FR-10 |
| 8 | 查询超时生效 | 慢查询不阻塞 | FR-9 |
| 9 | 缓存命中率 | > 80% | FR-18 |
| 10 | 缓存穿透防护 | 空值缓存生效 | FR-15 |
| 11 | 缓存击穿防护 | 单请求重建 | FR-16 |
| 12 | 缓存雪崩防护 | TTL 抖动 | FR-17 |
| 13 | 无重复计算 | 记忆化命中跳过重算 | FR-19 |
| 14 | LCP ≤ 2.5s | Core Web Vitals | FR-21 |
| 15 | 首屏包体积 ≤ 预算 | admin-web ≤ 500KB / user-web ≤ 300KB | FR-22 |
| 16 | 代码分割生效 | 路由级懒加载 | FR-22 |
| 17 | 图片优化 | WebP + 懒加载 + 响应式 | FR-24 |
| 18 | API 请求数 ≤ 目标 | 首屏 ≤ 10 | FR-25 |
| 19 | 虚拟列表 | 仅渲染可视区 | FR-26 |
| 20 | 水平扩展 | +1 实例 → 吞吐 ≈ 线性增长 | FR-27 |
| 21 | 限流生效 | > 1000 rps 返回 429 | FR-28 |
| 22 | 资源监控 | CPU/内存/IO 指标可查 | FR-29 |
| 23 | 容量模型可预测 | 并发 → 实例数/资源 | FR-30 |
| 24 | 压测覆盖关键场景 | 对话/文档/搜索/鉴权 | FR-31 |
| 25 | 瓶颈识别 | 压测报告定位端点/依赖 | FR-32 |

---

## 8. 故障排查

### 8.1 基线采集失败

```bash
# 检查 perf 中间件是否注册
grep -r "perf" services/chat-api/app/main.py
# 检查 kpi_store 是否有数据
curl http://localhost:8000/api/admin/performance/baselines \
  -H "Authorization: Bearer $TOKEN"
```

### 8.2 慢查询未记录

```bash
# 检查 slow_query_log 是否启用
grep -r "slow_query_log\|slowQueryLog" services/chat-api/app/core/
# 检查阈值配置
export MONGODB_SLOW_QUERY_LOG_THRESHOLD_MS=100
```

### 8.3 缓存未命中

```bash
# 检查 Redis 连接
docker compose exec chat-api python -c "
import redis; r = redis.Redis.from_url('redis://redis:6379'); print(r.ping())
"
# 检查缓存 key 是否存在
docker compose exec redis-cli --scan --pattern "cache:*" | head -20
```

### 8.4 前端包体积超标

```bash
# 检查构建输出
ls -lh apps/admin-web/dist/assets/
# 检查 Vite 配置
cat apps/admin-web/vite.config.ts
# 检查是否所有路由都懒加载
grep -r "import(" apps/admin-web/src/router/index.ts
```

### 8.5 压测结果异常

```bash
# 检查 locust 日志
locust -f benchmarks/locust/locustfile_chat.py --headless \
  --users 10 --run-time 30s --host http://localhost:8000 2>&1 | tee /tmp/locust.log

# 检查错误率
grep -E "FAILED|exceptions" /tmp/locust.log
```

---

## 9. 与 007 llm-gateway 联动验证

```bash
# 验证 LLM 耗时占比 + 韧性事件交叉归因
# （Phase 7 T053）
curl http://localhost:8000/api/admin/performance/external-deps \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.dependencies | {
    llm: {pct: .llm.pct, p95: .llm.p95_ms},
    db: {pct: .db.pct, p95: .db.p95_ms},
    redis: {pct: .redis.pct, p95: .redis.p95_ms}
  }'
```

期望：LLM 耗时占比可查，与 007 的 `token_usage_logs` 韧性事件（`failover_from`/`degradation_step`）可交叉归因。
