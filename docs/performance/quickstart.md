# 026 T055 — 性能优化快速上手（Quickstart）

> 目标：**30 分钟内**完成性能基线启用、主要子域优化验证与首轮压测。
> 所有命令在仓库根目录（`/Users/cooper/mogo`）执行。
>
> 说明：根目录 `quickstart.md` 属 023 特性（可观测性与韧性栈启用），
> 本文聚焦 **026 性能专项**（基线 / 缓存 / 数据库 / 压测 / 容量），两者互补不重叠。

## 1. 前置检查（2 分钟）

```bash
# 环境自检：Python ≥ 3.10、Redis、MongoDB 可达
python3 --version
redis-cli ping            # 期望 PONG
# mongosh --eval "db.runCommand({ping:1})"   # 期望 {ok:1}

# 起依赖（Docker 方式，按需）
docker compose up -d redis mongo
```

## 2. 启用性能基线（5 分钟）

```bash
# 2.1 基线与预算
cat benchmarks/perf_baselines/baselines.yaml      # 阈值单一来源（T010）
# P95 劣化 > 20% 判回归（T011 判定器，CI 告警不阻断）

# 2.2 配置清单一致性校验（T052）
python3 tools/perf/config_loader.py --check
# 期望：环境变量覆盖 0 项；与 baselines.yaml 关键阈值一致

# 2.3 Redis 缓存容量校验（T031）
python3 tools/perf/cache_capacity_check.py
# 期望：allkeys-lru + maxmemory ≥ 256mb 合规

# 2.4 数据库访问模式扫描（T018-T021）
python3 tools/perf/db_write_scanner.py --write-report docs/pending-review/026-perf-loop-write.md
python3 tools/perf/index_advisor.py --write-report docs/pending-review/026-index-recommendations.md
```

## 3. 各子域优化步骤

### 3.1 缓存层（T024-T027）

```bash
# 命中率监控：缓存 KPI 落库 `cache_hit_rate` / `cache_stats`，目标 ≥ 0.8
# 三件套已就绪：app/cache/{manager,policies,protection}.py
# 热点数据接入（T029）后，在业务服务启动时调用：
#   manager = CacheManager.from_url(settings.REDIS_URL, default_ttl=300)
#   result = await manager.get(CacheTag.SESSION, "user:1")   # 自动防击穿/雪崩/穿透
```

### 3.2 数据库（T014-T022）

- 连接池：`MONGODB_MAX_POOL_SIZE=100 / MIN_POOL_SIZE=10 / MAX_IDLE_TIME_MS=30000`
- 慢查询：`MONGODB_SLOW_QUERY_THRESHOLD_MS=100` 自动 `explain` 落 `query_plans`
- 批量写：把循环单条 `update_one` 改为 `build_bulk_write()`（见 T020/T021）
- 预取：循环内 `find_one` 改为 `batch_prefetch.prefetch_many_async()`（见 T019）

### 3.3 韧性（FR-28）

```bash
# 限流/背压中间件已接入（T042/T043）：
#   services/common/perf_guards.py::RateLimitMiddleware / BackpressureMiddleware
# 熔断与并发池：app/core/resilience.py（T022/T026）
# 验证：
cd services/chat-api && python3 -m pytest tests/middleware/test_perf_guards.py -q   # 7 passed
```

### 3.4 可观测（T003-T013、T044）

```bash
# 指标端点：GET /metrics（prometheus）
#  - mogo_http_request_duration_seconds{method,path_template,status_class}
#  - mogo_system_cpu_usage_percent / mogo_system_memory_used_bytes
#  - mogo_system_disk_usage_percent{device} / mogo_system_loadavg_1m/5m/15m
# 黄金信号：延迟分位数 / 吞吐 / 错误率 / 饱和度 100% 可查（T051）
```

### 3.5 前端（Phase 5）

```bash
# 构建 + 预算检查（T040）
cd apps/admin-web && npx vite build && cd -
cd apps/user-web  && npx vite build && cd -
bash benchmarks/frontend_budget_check.sh
# 期望：admin ≤ 500KB gzip、user ≤ 300KB gzip（当前基线超标，需继续减负）
```

## 4. 压测命令（FR-31）

```bash
# 4.1 Locust（主）
# 对话场景，并发级别 1/10/50/100：
TARGET_HOST=http://localhost:8000 locust -f benchmarks/locust/locustfile_chat.py \
    -u 10 -r 2 --host http://localhost:8000 --headless --run-time 60s

# 文档解析（默认 8001）：
TARGET_HOST=http://localhost:8001 locust -f benchmarks/locust/locustfile_doc.py \
    -u 10 -r 2 --host http://localhost:8001 --headless --run-time 60s

# 搜索（8001）/ 鉴权（8002）：
TARGET_HOST=http://localhost:8001 locust -f benchmarks/locust/locustfile_search.py \
    -u 50 -r 5 --host http://localhost:8001 --headless --run-time 60s
TARGET_HOST=http://localhost:8002 TARGET_ADMIN_USER=benchmark TARGET_ADMIN_PASSWORD=benchmark-secret \
    locust -f benchmarks/locust/locustfile_auth.py \
    -u 50 -r 5 --host http://localhost:8002 --headless --run-time 60s

# 4.2 k6 冒烟（补充）
TARGET_HOST=http://localhost:8000 K6_VUS=10 K6_DURATION=30s k6 run benchmarks/k6/smoke.js
```

## 5. 容量与瓶颈（FR-30/FR-32）

```bash
# 容量模型：给定并发 → 实例数 / CPU / 内存（T049）
cat benchmarks/capacity_model.md        # §5 含交互式计算命令

# 瓶颈清单（T050）与静态热点：docs/pending-review/026-perf-*.md
cat benchmarks/bottleneck_report.md
```

## 6. 回归判定闭环（T057）

```bash
# 全链路：基线采集 → 预算检查 → 回归判定
# 1) PerfBaselineCollector.collect(spans)  → perf_baselines（T006）
# 2) PerfBudgetChecker.check(baseline)     → breached 列表（T009）
# 3) PerfBudgetChecker.check_regression(new, historical)  → 劣化 > 20% 判回归（T011）
# CI 中调用即打通全链路；告警不阻断（FR 语义）。
```

## 7. 常见问题

| 现象 | 处置 |
|---|---|
| `config_loader --check` 报差异 | 同步 `config/performance.yaml` 与 `baselines.yaml` 后再跑 |
| `cache_capacity_check` 报内存不足 | `redis-cli CONFIG SET maxmemory 256mb` |
| `/metrics` 缺 `mogo_system_*` | 确认 `app/main.py` 已 `register_system_metrics(get_registry(...))` |
| 前端预算超标 | 优先排查 `manualChunks` 是否生效、大依赖是否可动态 import |
| 压测返回 429/503 | 属 FR-28 预期（限流/背压），查看 `Retry-After` 与命中计数 |