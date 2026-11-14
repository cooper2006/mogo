# Contract: Performance & Scalability (026)

**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [tasks.md](../tasks.md)

本契约定义性能与扩展性加固的可观测接口：**性能基线**、**预算阈值**、**缓存语义**、**压测 IO 格式**。任何实现违反契约即触发回归判定（T011）。

阈值权威源：`benchmarks/perf_baselines/baselines.yaml`（T010）；声明清单：`config/performance.yaml`（T052）。两者由 `tools/perf/config_loader.py` 做一致性校验（CI 门禁）。

**关联文档**：本文件为 026 特性级契约（含完整阈值表与压测 IO 表格）；仓库级契约另见 `contracts/performance.md`（输入→输出/预算/缓存/压测/观测/配置驱动/变更流程）。两者主题互补、阈值同源，改动需同步。

**快速上手**：特性级步骤见 `specs/026-performance-scalability/quickstart.md`（逐 US 验证）；仓库级 30 分钟启用见 `docs/performance/quickstart.md`（前置检查→启用基线→子域优化→压测→容量瓶颈→回归闭环）。

---

## 1. 组件

| 模块 | 职责 |
|---|---|
| `benchmarks/perf_baselines/baselines.yaml` | 性能基线权威源（T010），P95 延迟 / 吞吐 / 前端体积上限 |
| `config/performance.yaml` | 全配置驱动声明清单（T052），连接池/超时/缓存 TTL/限流/并发上限 |
| `tools/perf/config_loader.py` | 加载 + env 覆盖 + 与 baselines.yaml 一致性校验（`--check/--json`） |
| `services/*/app/infrastructure/observability/perf_budget.py` | 服务侧阈值加载（`PerfBudgetChecker.load_thresholds` / `threshold_for` / `global_value`） |
| `services/chat-api/app/core/db_guard.py` | 连接池 / 慢查询 / 超时 / 错误率 / 池利用率监控 |
| `services/common/perf_guards.py` | 限流（令牌桶）/ 背压 / 熔断中间件（vendored 三服务） |
| `services/common/cache_hotspots.py` | 热点数据缓存门面（session/config/permission/token） |
| `benchmarks/locust/` | 对话/文档/搜索/鉴权四场景压测 |
| `benchmarks/k6/smoke.js` | 补充冒烟（健康面 + 阈值） |
| `benchmarks/frontend_budget_check.sh` | 前端 gzip 体积预算门禁（CI 可调用） |

---

## 2. 性能基线契约（baselines.yaml，`version: "026-t010"`）

约定：所有值都是**目标上限**（超限即违反性能预算），非实测值；延迟单位 ms，吞吐单位 rps/实例，体积单位 KB（gzip 后）。P95 为服务端处理延迟（不含网络 RTT、不含 LLM 生成段）。

| 服务 | 端点 | P95 上限 (ms) |
|---|---|---|
| chat-api | `/chat/completions`、`/chat` | 2000 |
| chat-api | `/chat/cancel` | 1000 |
| chat-api | defaults | 2000 |
| chat-api | throughput | 1000 rps/实例 |
| document-parser | `/jobs/document-parse`、`/documents/parse-markdown` | 5000 |
| document-parser | throughput | 500 rps/实例 |
| admin-api | `/auth/login`、`/auth/login/select-tenant`、`/auth/me`、`/auth/logout`、`/auth/mfa/verify` | 500 |
| admin-api | defaults | 1000 |
| admin-api | throughput | 500 rps/实例 |

```yaml
frontend:
  admin-web: {bundle_gzip_max_kb: 500}   # 首屏 JS ≤ 500KB gzip
  user-web:  {bundle_gzip_max_kb: 300}   # 首屏 JS ≤ 300KB gzip
  lcp_max_s: 2.5                          # 内网基线 LCP ≤ 2.5s
cache:
  hit_rate_min: 0.8                       # 缓存命中率 ≥ 80%
```

基线口径说明：慢查询阈值 100ms（`db_guard.SlowQueryRegistry` 默认 `threshold_ms=100`，env 可覆盖）；连接池 `max_pool_size=100 / min_pool_size=10 / max_idle_time_ms=30000`。

---

## 3. 回归判定契约（T011）

| 输入 | 判定 | 动作 |
|---|---|---|
| 当前窗口 P95 vs 上一滚动窗口 P95 | 劣化 > 20% | 判回归，CI 告警（**不阻断**） |
| 缓存命中率 | < 0.8 | 判退化，告警 |
| 前端 gzip 合计 | > 500KB (admin) / > 300KB (user) | 判超标，`frontend_budget_check.sh` exit=1 |
| 池峰值利用率 | > 0.8 | 判告警（`db_guard.pool_utilization_snapshot`） |
| CPU / 内存利用率 | > 0.7 / > 0.8 | 判告警（`bottleneck_report.md` 阈值 70%/80%） |

基线建立后，回归判定通过 `PerfBudgetChecker` 读取 `baselines.yaml`，与实测指标对比输出差异。

---

## 4. 缓存契约（T023–T031、T029）

| 项 | 契约 |
|---|---|
| 命中率下限 | `hit_rate_min = 0.8`（低于即告警） |
| 默认 TTL | `default_ttl_seconds = 300`，按类型覆盖：session 600 / configuration 300 / permission 120 / token 60 |
| TTL 抖动 | `TTLPolicy.jittered_ttl ±10%`（防止缓存雪崩，热点缓存统一走抖动） |
| 淘汰策略 | Redis `allkeys-lru`，`maxmemory 256mb`（`config/performance.yaml`，T031 校验） |
| 热点 key | `hotspot:{kind}:{ident}`（kind ∈ session/config/permission/token），tag `hotspot:{kind}`；事件失效走 tag 级 `forget_tag`，`invalidate_all` 清空 |
| 穿透防护 | 空结果负缓存（T027） |
| 击穿防护 | 热点互斥重建（T028） |

事件失效链路：`HotspotCache.delete(kind, ident=None)` 整类 tag 失效；缓存失效事件通过 tag 广播，不逐 key 遍历。

---

## 5. 限流 / 背压 / 熔断契约（T042/T043/T026，FR-28）

| 项 | 契约 |
|---|---|
| 限流算法 | 令牌桶，默认 1000 rps/实例（`rate_limit.default_rps`），`burst=2000`，`max_concurrent=500` |
| 超限响应 | HTTP 429 + `Retry-After`（ceil 秒）+ `X-RateLimit-Limit` + RFC 9457 `problem+json` |
| 限流 key | `x-tenant-id` 头 → `tenant:{id}`；缺省回退客户端 IP |
| 背压 | 队列满（`max_depth=1000`）返回 503 + `Retry-After: 1` + `X-Backpressure-Depth` |
| 熔断 | `max_failures=5` / `recovery_time_seconds=30` / `failure_ratio=0.5`；滚动 30s 错误率 > 0.5 触发 open（`db_guard.ErrorRateWindow`） |
| 并发池 | `max_concurrency=50` / `queued_max=100` |

---

## 6. 压测 IO 契约（FR-31）

### 6.1 locust 场景（`benchmarks/locust/`）

| 场景文件 | User | 端点权重 | 并发级别 |
|---|---|---|---|
| `locustfile_chat.py` | `ChatUser` | `chat_short` ×10 / `chat_long_context` ×2 | `CONCURRENCY_LEVELS=(1,10,50,100)` |
| `locustfile_doc.py` | `DocumentUser` | `POST /api/v1/jobs/document-parse`（期望 202）+ 轮询 `/api/v1/jobs/{id}` | 同上 |
| `locustfile_search.py` | `SearchUser` | `vector_search` ×7 / `memory_list` ×3 | 同上 |
| `locustfile_auth.py` | `AuthUser` | `login` ×5 / `me` ×2（凭据走 env，不落库） | 同上 |

- host：`TARGET_HOST` 环境变量；chat 默认 `http://localhost:8000`，doc 默认 `http://localhost:8001`。
- **状态码语义契约**：429/503 属限流/背压正常分支，**计入成功**；401/403 属鉴权正常分支，**计入成功**。
- 输出：`--csv benchmarks/perf_baselines/baseline_<scene>`（每场景一份 stats 与 requests 表）。

### 6.2 k6 冒烟（`benchmarks/k6/smoke.js`）

```
TARGET_HOST=http://localhost:8000 K6_VUS=10 K6_DURATION=30s k6 run benchmarks/k6/smoke.js
```

- `vus = K6_VUS`（默认 10）、`duration = K6_DURATION`（默认 30s）。
- **thresholds**：`http_req_failed < 0.01`、`http_req_duration p(95) < 2000ms`。
- 探测面：`/` 与 `/ready` 返回 `< 500` 视为可观测（依赖不可达时 503 亦计可观测，不判失败）。

### 6.3 前端预算（`benchmarks/frontend_budget_check.sh`）

```
./benchmarks/frontend_budget_check.sh --admin-dir apps/admin-web/dist --user-dir apps/user-web/dist
```

- 计算 js/css 产物 `gzip -9` 合计体积（KB，向下取整），对比 `--admin-max-kb 500` / `--user-max-kb 300`。
- **退出码契约**：`0` 全部通过；`1` 超标或产物缺失；`2` 用法错误。

### 6.4 容量模型（`benchmarks/capacity_model.md`，FR-30）

- 公式：`R_total = C × rps_u`；`N = max(ceil(R_total / rps_i), 2)`；`CPU = N × cpu_i × cpu_util`；`MEM = N × mem_i × buf_mem`；`POOL = N × pool_max`。
- 校正契约：`|预测 N − 实测 N| / 实测 N ≤ 0.2`（压测回填后须满足）。

---

## 7. 一致性校验契约（T052）

```bash
python3 tools/perf/config_loader.py --check      # 退出码 0 一致 / 1 差异 / 2 缺失
python3 tools/perf/config_loader.py --json       # 输出 JSON diff
```

`config/performance.yaml` 与 `baselines.yaml` 关键阈值须一致（`p95_clarify_ms / p95_llm_ms / p95_db_read_ms / p95_db_write_ms / p95_doc_parse_ms / cpu_max_utilization / memory_max_utilization / throughput_max_rps_per_instance`）。`config/performance.yaml` 是**声明清单**，非服务启动自动读取；改动需同步 env 或由 `config_loader` 输出 diff。

---

## 8. 可观测暴露（FR-29 / T051 成功基准）

| 指标 | 暴露位置 | 字段 |
|---|---|---|
| 系统资源 | `/metrics`（`mogo_system_*` 11 个 Gauge） | cpu_usage_percent / memory_used_bytes / memory_available_bytes / disk_{read,write}_bytes_total / disk_{read,write}_iops_total / disk_usage_percent{device} / loadavg_{1m,5m,15m} |
| 延迟分位数 | `PerfBudgetChecker.threshold_for(endpoint, metric)` | p95 实测 vs `p95_max_ms` |
| 缓存命中率 | `CacheManager.stats()` / `HotspotCache.stats()` | hit / miss / hit_rate |
| 池利用率 | `db_guard.pool_utilization_snapshot()` | MONGO/REDIS peak 利用率（≤ 0.8） |
| 慢查询 | `db_guard.persist_slow_queries` → `slow_queries` 集合 | 阈值 100ms 以上查询 |
| 池指标 | `db_guard.persist_pool_utilization` → `pool_metrics` 集合 | 时间点快照 |

**违反契约的判定**：任一实测指标超过第 2/3 节的阈值上限，即视为违反性能预算；T011 回归判定按劣化 > 20% 输出 CI 告警（不阻断）。
