# 026 T056 — 性能契约（contracts/performance.md）

> 本文件定义 **性能基线 / 预算 / 缓存 / 压测** 的 IO 契约，供服务端、前端、
> 压测脚本与 CI 共同遵守。数值单一来源为 `benchmarks/perf_baselines/baselines.yaml`
> 与 `config/performance.yaml`；本文件只规定**结构**与**语义**，不改动阈值本身。

---

## 1. 性能基线契约（输入 → 输出）

| 项 | 契约 |
|---|---|
| 输入 | `spans` 事件流（`services/*/app/infrastructure/observability/spans.py`） |
| 输出 | `perf_baselines` 记录，含 `{service, endpoint, p50_ms, p95_ms, rps, tps, error_rate, collected_at}` |
| 采集方 | `PerfBaselineCollector.collect(spans)`（T006） |
| 存储 | `perf_baselines` 集合，按 `(service, endpoint)` 聚合滚动窗口 |
| 阈值来源 | `baselines.yaml`（单一来源，改动需同步 `config_loader.py`） |
| 违反语义 | 超限即"违反预算"，非崩溃；由 `PerfBudgetChecker` 标记 `breached` |

## 2. 预算契约

| 项 | 契约 |
|---|---|
| 检查方 | `PerfBudgetChecker.check(baseline)`（T009） |
| 输出 | `breached: [{service, endpoint, metric, actual, expected}]` |
| 回归判定 | `PerfBudgetChecker.check_regression(new, historical)`：P95 劣化 > 20% 判回归（T011） |
| CI 语义 | 回归判 **告警不阻断**（FR-3）；预算超限仅记录，不 fail CI |
| 阈值覆盖 | 未显式列出的端点用 `services.<svc>.defaults.p95_max_ms` |

## 3. 缓存契约

| 项 | 契约 |
|---|---|
| 三件套 | `app/cache/manager.py`（`CacheManager`）、`policies.py`（`CacheTag`/TTL）、`protection.py`（击穿/雪崩/穿透） |
| TTL 来源 | `config/performance.yaml → cache.tags`（session 600 / configuration 300 / permission 120 / token 60） |
| 容量策略 | `allkeys-lru`，`maxmemory ≥ 256mb`（`tools/perf/cache_capacity_check.py` 校验） |
| 命中率 | `cache_hit_rate ≥ 0.8`（T030 `CacheMetricsReporter`，breached 时 `logger.error("cache.hit_rate_low")`） |
| 键空间 | `memo:<tag>:<qualname>:<sha1(args,kwargs)>`（`cache_memoize.py`）；显式 `cache_key` 优先级更高 |
| 不可缓存值 | `None` 与 generator（`_is_cacheable` 排除） |
| 布隆过滤器 | 穿透防护默认启用，未登记 key 直接返回空 |

## 4. 压测契约（IO）

| 项 | 契约 |
|---|---|
| 工具 | **locust 为主**，**k6 补充**（FR-31） |
| 场景覆盖 | 对话 / 文档解析 / 搜索 / 鉴权 4 类，见 `benchmarks/locust/locustfile_{chat,doc,search,auth}.py` + `benchmarks/k6/smoke.js` |
| 并发级别 | `1 / 10 / 50 / 100`（脚本内 `CONCURRENCY_LEVELS` 常量声明） |
| 目标地址 | 环境变量 `TARGET_HOST`（chat=8000 / document=8001 / admin=8002） |
| 凭据 | 环境变量 `TARGET_ADMIN_USER` / `TARGET_ADMIN_PASSWORD`，**禁止写入仓库** |
| 状态码语义 | 429/503 属 FR-28 预期（限流/背压），压测计入 `success` 不计失败；401/403 属鉴权正常分支 |
| 产出 | `perf_baselines`（T006）→ `perf_budget_checks`（T009）→ 回归判定（T011） |
| 容量模型 | `benchmarks/capacity_model.md`：`N = max(ceil(C × rps_u / rps_i), 2)`，压测回填 `rps_i` |

## 5. 观测契约

| 项 | 契约 |
|---|---|
| 指标端点 | `GET /metrics`（prometheus text 格式） |
| 黄金信号 | 延迟分位数（`http_request_duration_seconds`）/ 吞吐（`http_requests_total`）/ 错误率（`http_errors_total`）/ 饱和度（`inflight_requests` + 进程指标） |
| 系统资源 | `mogo_system_cpu_usage_percent` / `mogo_system_memory_{used,available}_bytes` / `mogo_system_disk_{read,write}_bytes_total` / `mogo_system_disk_{read,write}_iops_total` / `mogo_system_disk_usage_percent{device}` / `mogo_system_loadavg_{1m,5m,15m}`（T044） |
| label 白名单 | `method` / `path_template` / `status_class`（**非**完整 status/path 原值，FR-12 基数受控） |
| 资源阈值 | CPU 70% / 内存峰值 80% / 连接池峰值 80%（`config/performance.yaml → baselines`） |

## 6. 配置驱动契约（T052）

- 连接池 / 超时 / 缓存 TTL / 限流 / 并发上限**全部配置驱动**，单一来源 `config/performance.yaml`；
- 每项标注 env 覆盖键名（如 `MONGODB_MAX_POOL_SIZE`、`RATE_LIMIT_RPS`、`REDIS_MAXMEMORY_POLICY`）；
- 一致性由 `tools/perf/config_loader.py --check` 校验（与 `baselines.yaml` 关键阈值对齐，CI 可调用）。

## 7. 契约变更流程

1. 修改 `baselines.yaml` 或 `performance.yaml`（**不要**改本文件阈值）；
2. 运行 `python3 tools/perf/config_loader.py --check` 确认一致；
3. 若结构变化（新增指标/字段），同步本文件对应表格并注明轮次（如 `026 T0xx`）；
4. 涉及压测脚本端点变化，同步 `locustfile_*.py` 与 `benchmarks/k6/smoke.js`。