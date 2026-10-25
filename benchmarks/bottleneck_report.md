# 026 T050 — 瓶颈识别报告（FR-32）

> 将性能风险定位到具体端点 / 依赖 / 资源，并按优先级给出处置。
> 数据来源：静态扫描（`tools/perf/db_write_scanner.py`，本轮实测）+ 预算基线
> （`benchmarks/perf_baselines/baselines.yaml`）+ 连接池 / 熔断配置。
> 待真实压测（T045-T048）产出 `perf_baselines` 后，本报告数值需回填更新。

## 1. 结论摘要

- 主瓶颈集中在**数据访问层**：MongoDB 循环单点读写（N+1 / 循环写入）是延迟与
  连接占用主因；扫描 `services/**` 命中 **N+1 候选 60 处、循环单条写入候选 39 处**。
- 次要瓶颈为**缓存缺失**：四类热点数据（会话 / 配置 / 权限 / 令牌）首期未接入
  缓存层，缓存命中率无数据（T030 采集需启用）；已交付三件套
  （`app/cache/{manager,policies,protection}.py`）待接入。
- 资源面：并发上限默认 1000 rps/实例，超限依赖限流（T042）+ 背压（T043）
  返回 429/503；Mongo 慢查询阈值 100ms（T015 自动登记）。
- 扩展性：单实例线性扩容（FR-27）受 MongoDB 连接池总量约束，详见
  `benchmarks/capacity_model.md` §2.5。

## 2. 端点级瓶颈（按 P95 预算）

| 端点 | 预算 P95 | 风险 | 处置 |
|---|---|---|---|
| `POST /api/v1/chat/completions` | 2000ms（非 LLM 生成段） | 对话会话/消息历史 N+1 读取（`personal_knowledge.py:106`、`auth.py:289`） | 走批量预取 `batch_prefetch.prefetch_many_async` |
| `POST /api/v1/jobs/document-parse` | 5000ms | worker 端到端受存储 IO 影响 | 磁盘使用率纳入容量监控（T044） |
| `POST /api/v1/auth/login` | 500ms | admin 会话/权限多次 `find_one` | 会话/权限结果缓存（T024 `CacheTag.PERMISSION`） |
| `POST /api/v1/retrieval/search` | 2000ms（默认） | 向量检索 top-k 放大读放大 | 索引建议 `tools/perf/index_advisor.py` |

> 端点级 RPS/TPS 实测需 `T006 PerfBaselineCollector` 采集后回填。

## 3. 依赖级瓶颈

| 依赖 | 现状 | 瓶颈 | 处置 |
|---|---|---|---|
| MongoDB | `maxPoolSize=100/minPoolSize=10/maxIdleTimeMS=30000`（T014 已接入 `init_db`） | 循环单条读写耗尽连接；慢查询无索引全表扫 | 建索引（T018）+ bulk_write（T020/T021）+ `explain` 落 `query_plans`（T019） |
| Redis | `allkeys-lru` / `maxmemory` 需 ≥ `256mb`（T031 校验） | 未配置时逐出导致命中率下降 | `tools/perf/cache_capacity_check.py` CI 校验 |
| LLM Gateway（007） | 外部调用 | 生成段耗时主导对话 P95 | 生成段与非生成段分开度量（T010 baselines 已区分） |
| 上游第三方（浏览器录制等） | 外部调用 | 无超时聚合视图 | `dependency_breakdown()`（T008）归因 |

## 4. 资源级瓶颈

| 资源 | 现状 | 阈值 | 处置 |
|---|---|---|---|
| CPU | `/proc/stat` 两次采样 | `cpu_util` 70% 水位 | `mogo_system_cpu_usage_percent`（T044） |
| 内存 | `/proc/meminfo` | 峰值利用率 ≤ 80% | `mogo_system_memory_used_bytes`（T044） |
| 磁盘 | `/proc/diskstats` + `statvfs` | 使用率 + IOPS | `mogo_system_disk_usage_percent{device}`（T044） |
| 连接 | `resilience.pool_spec` | 峰值利用率 ≤ 80% | `pool_utilization_snapshot()`（T022） |

## 5. 已识别代码级热点（可立即处置）

完整清单见 `docs/pending-review/026-perf-n-plus-one-loop-write-report.md`。

**N+1 候选（60 处）Top 采样**：

- `services/admin-api/app/api/routes/directory.py:280` `find_one` in `while`
- `services/admin-api/app/api/routes/directory.py:530` `find_one` in `for`
- `services/chat-api/app/api/endpoints/auth.py:289` `find_one` in `for`
- `services/chat-api/app/api/endpoints/personal_knowledge.py:106` `find_one` in `while`
- `services/directory_bootstrap.py:24/27` `find_one` in `for`
- `services/tenant_provisioning.py:69` `find_one` in `for`

**循环单条写入候选（39 处）Top 采样**：

- `services/admin-api/app/api/routes/directory.py:149/338/1104` `update_one` in `for`

处置建议：改为 `batch_prefetch.prefetch_many_async()` + `build_bulk_write()`；
需人工确认语义后执行（静态扫描未执行代码）。

## 6. 复测方法（压测回填）

```bash
# 1. 采集基线（T006）
#    PerfBaselineCollector.collect(spans) → perf_baselines
# 2. 检查预算（T009）
#    PerfBudgetChecker.check(baseline) → breached 列表
# 3. 判定回归（T011，P95 劣化 > 20%）
#    PerfBudgetChecker.check_regression(new, historical)
# 4. 容量校准（T049）
#    按 baselines 回填 rps_i 重算 capacity_model.md
```

判定准则：任一端点 P95 超出 §2 预算即为瓶颈；回归判定劣化 > 20% 判回归
（CI 告警非阻断）。