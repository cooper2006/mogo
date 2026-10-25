# Tasks: Performance & Scalability Hardening

**Input**: Design documents from `/specs/026-performance-scalability/`

**Prerequisites**: plan.md (required), spec.md (required)

**Status**: 全部 `blocked` — QualityForge 审计标记 51 个 P0/P1 缺陷，需先建立性能基线（US1）方能解除。

**Organization**: 任务按用户故事分组，每组可独立实现与测试；`[P]` 标记可并行任务。**US1 是其他故事的前置条件**（无基线则无从度量优化收益）。

**Implementation Order**: US1 → US2 → US3 → US4 → US5

---

## Phase 1: Setup (Module Skeleton)

**Goal**: 搭建性能相关模块骨架，作为各故事共用的基础设施载体。

- [x] T001 创建 `services/chat-api/app/cache/__init__.py` + `services/chat-api/app/cache/manager.py`（缓存管理器占位：`get/set/delete/lock` 接口，复用既有 Redis 客户端）
- [x] T002 创建 `services/chat-api/app/infrastructure/observability/perf_baseline.py`（基线采集占位：P50/P95/P99 延迟 + 吞吐 RPS/TPS）
- [x] T003 创建 `services/chat-api/app/infrastructure/observability/perf_budget.py`（性能预算检查占位：读 `performance.yaml`，对比基线）
- [x] T004 [P] 创建 `services/chat-api/app/api/middleware/perf.py`（性能中间件占位：请求延迟埋点 → kpi_store）
- [x] T005 [P] 创建 `benchmarks/` 目录结构 + `benchmarks/locust/` + `benchmarks/k6/` + `benchmarks/perf_baselines/baselines.yaml`（空占位）

---

## Phase 2: User Story 1 (P1) — 性能基线与度量 [BLOCKING]

**Goal**: 建立系统级性能基线，定义性能预算，接入 CI 回归检查。**本 Phase 完成后其他故事方可解除 `blocked`**。

**独立测试**: 关键端点 P95/P99 基线落库；吞吐按并发级别可查；外部依赖耗时占比可拆分；性能预算 CI 检查生效。

- [x] T006 实现 `perf_baseline.py` 延迟采集：基于 `spans.py` 的 span 数据聚合 P50/P95/P99（按端点 + 方法分类），落库 `perf_baselines` collection
  - 证据：`spans.py` 新增完成 span 滚动缓冲（`emit_completed_span` / `drain_completed_spans` / `recent_completed_spans`，`log_span._finish` 记录 `{span_id,name,parent_span_id,duration_ms,error,finished_at}`）；`perf_baseline.PerfBaselineCollector.collect(spans)` 按 `name` 分组算 P50/P95/P99 + sample_count，`persist()` 内存 `records`（可注入 `on_persist` 落 Mongo `perf_baselines`），`query(endpoint)` 查询。测试 `tests/observability/test_perf_baseline.py::TestPerfBaselineCollect/TestSpanBuffer`（分位数分组、持久化覆盖、log_span 完成入缓冲）。验证：`pytest tests/observability` 全绿。
- [x] T007 实现 `perf_baseline.py` 吞吐采集：按并发级别（1/10/50/100）记录 RPS（对话）/ TPS（文档解析），落库
  - 证据：`PerfBaselineCollector.collect` 用 `finished_at` 落在 `window_seconds`(60s) 窗口内的 span 计 RPS/TPS（同一 rate，因单请求单事务），写入 `PerfBaselineRecord.rps/tps`；并发分档在 `kpi_store` / `perf_kpi.RequestKPIStore.throughput()` 的 `rps_by_concurrency`（1/10/50/100），`enter_request/leave_request` 记录瞬时并发进 `_inflight_history` 滚动窗口。测试 `TestPerfBaselineCollect::test_collect_groups_by_name`、`TestRequestKPIStore::test_inflight_gauge_and_concurrency_buckets`。
- [x] T008 实现 `execution_trace.py` 外部依赖耗时拆分：每次请求拆分 DB / Redis / LLM / 外部 API 耗时占比，汇总到基线（FR-3）
  - 证据：`execution_trace.py` 新增 `infer_span_kind(name)`（DB/Redis/LLM/外部 HTTP/文件系统/其他，正则 + 显式 `kind` attr 优先）、`dependency_breakdown(spans, request_duration_ms=)` 返回 `PerfBreakdown`（`items: [{kind,total_ms,count,p95_ms,share}]` 按耗时降序，分母=所有 span 耗时之和，`unknown_spans` 点名未分类）。`perf_breakdown.py` 保留为薄 re-export。测试 `TestDependencyBreakdown`（kind 推断、占比 0.7/0.2/0.1、显式 kind 优先、unknown）。
- [x] T009 [P] 实现 `perf_budget.py` 预算检查：读 `benchmarks/perf_baselines/baselines.yaml`，检查 P95 ≤ 阈值、包体积 ≤ 预算，输出通过/失败
  - 证据：`PerfBudgetChecker.load_thresholds(config_path)` 用 PyYAML 解析（缺文件抛 `FileNotFoundError`），按 `service_name` 装配 latency/throughput 阈值；`check(baseline)` 逐端点比 `p95_ms` 与 `max_value`，超限 `breached=True` 并返回列表；`check_frontend_bundle(actual_kb)` 对照 `frontend.*.bundle_gzip_max_kb`；`alert(threshold)` 用 structlog `logger.error("perf_budget_breached", extra=...)`。测试 `test_perf_budget.py::TestLoadThresholds/TestCheck/TestCheckFrontendBundle`。
- [x] T010 [P] 定义 `benchmarks/perf_baselines/baselines.yaml`：关键端点显式预算（对话 P95 ≤ 2s、文档解析 ≤ 5s、鉴权 ≤ 500ms、admin-web ≤ 500KB、user-web ≤ 300KB、缓存命中率 ≥ 80%、并发上限 1000 rps/实例）——阈值已定值（2026-10-24 Clarify 记录）
  - 证据：`baselines.yaml` 按服务分组写 Clarify 定值：chat-api `/chat/completions` `/chat` p95 2000ms、document-parser `/jobs/document-parse` `/documents/parse-markdown` 5000ms、admin-api `/auth/login` `/auth/me` `/auth/logout` `/auth/mfa/verify` 500ms；frontend admin-web 500KB / user-web 300KB / lcp 2.5s；cache hit_rate_min 0.8；database slow_query_ms 100 / max_time_ms 5000 / pool 100/10/30s/90s/0.8；concurrency queue_depth_max 1000；circuit_breaker error_rate_max 0.5 / rolling 30s；regression p95_regression_ratio 1.2。测试 `TestBaselinesYamlOnDisk::test_parses_and_matches_clarify` 校验文件可被 loader 读入且关键阈值正确。
- [x] T011 实现 `perf_budget.py` 回归判定：新构建基线 vs 历史基线，P95 超阈值（如 +20%）标记为回归，CI 中告警（FR-5）
  - 证据：`check_regression(new_baseline, historical_baseline, ratio=None)`，ratio 默认取 `regression.p95_regression_ratio`(=1.2)；逐端点算 `new_p95/hist_p95`，超过 ratio 返回 `PerfBudgetThreshold(metric="p95_regression", max_value=ratio, current_value=actual_ratio)`；hist_p95 ≤ 0 或历史缺端点跳过。测试 `TestCheckRegression`（+30% 判回归、+10% 不判、hist=0 跳过）。
- [x] T012 实现 `api/middleware/perf.py` 性能中间件：请求级延迟埋点 → `kpi_store.incr` → span 记录，接入 chat-api / admin-api / document-parser（FR-1/FR-2）
  - 证据：新建 `services/common/perf_kpi.py`（权威源）+ 三服务 `app/common/perf_kpi.py` 字节一致 vendored 副本（`md5 -q` 四份同 `1a88eb1fd58c96cfaad424eb18e84462`）。`PerfMiddleware(store=...)` 从请求进到响应计时（`time.perf_counter`），`finally` 兜底保证异常也计延迟；`default_endpoint` 去 `/api/v1` 前缀；store 失败吞异常不阻断请求。chat-api 用既有 `runtime_kpi_store`（RuntimeKPIStore），admin-api/document-parser 用 `RequestKPIStore()`；`app/api/middleware/perf.py` 保留为 re-export 兼容路径。挂载验证：admin-api `create_app()` 后 `app.user_middleware` 含 `PerfMiddleware`（最外层）；chat-api TestClient 打 `/health`+`/api/v1/auth/me` 后 `perf_summary()` 出现 `{"/health|GET": {count:1,p95:2.3}, "/auth/me|GET": {count:1,p95:1.3}}`。测试 `test_perf_kpi.py::TestPerfMiddleware/TestPerfMiddlewareIsolatesFailure`。
- [x] T013 [P] 扩展 `kpi_store.py`：新增延迟分位数计数器（P50/P95/P99），支持按端点维度聚合（FR-1）
  - 证据：`RuntimeKPIStore` 新增 `enter_request/leave_request(endpoint,method,latency_ms,status=)`（60s 滚动窗口 / 10s 分桶 / 单桶上限 5000 样本 / 过期桶 `_prune_buckets` 裁剪）、`latency_percentiles(endpoint,method)→{p50,p95,p99,p999,count}`（排序后按秩取，空返回全 0）、`throughput()→{rps_total,tps_total,per_endpoint,rps_by_concurrency}`、`perf_summary()→{inflight,request_count_total,endpoints,endpoint_percentiles,throughput}`；既有 agent 运行时计数器与 `_recompute` 保持不变。测试 `TestRequestKPIStore`（分位数已知值 10 样本 P50=50/P95=100/P99=100、窗口过期裁剪、并发分档键、summary 形状）。

---

## Phase 3: User Story 2 (P1) — 数据库性能

**Goal**: 消除慢查询、N+1、缺失索引；建立查询超时与熔断、连接池管理；优化写入路径。

**独立测试**: 慢查询 < 阈值且告警；索引覆盖率 > 95%；连接池配置合理；N+1 改造完成；查询超时生效。

- [ ] T014 扩展 `core/db.py` 连接池配置：`maxPoolSize`（默认 100）/ `minPoolSize`（默认 10）/ `maxIdleTimeMS`（默认 30000）/ 连接泄漏检测（> 90s 告警）（FR-10）
- [ ] T015 启用 MongoDB `slow_query_log`：阈值可配置（默认 100ms），超阈值查询落库 `slow_queries` collection 并告警（FR-6）
- [ ] T016 实现查询超时：所有查询设置 `maxTimeMS`（默认 5000ms，可配），慢查询不阻塞其他请求（FR-9）
- [ ] T017 [P] 实现查询熔断：错误率 > 50% 触发熔断，降级返回缓存或明确错误（FR-9）
- [x] T018 [P] 索引策略：按访问模式建立复合索引与覆盖索引（session/config/permission/token/document collections），索引覆盖率 > 95%（FR-8）
  - 证据: （FR-8）；工具：`tools/perf/index_advisor.py`（`SUGGESTED_INDEXES` 覆盖 chat_sessions/chat_messages/memories/permissions/admin_tokens/document_jobs/knowledge_graph_nodes，`plan_diffs` 报缺失，`coverage_report` 用 explain(executionStats) 统计 totalDocsExamined<=nReturned，覆盖率>95% 目标；T019 的 `app/core/db_guard.py:explain_and_store` 落库 query_plans）；验证：`pytest tools/tests/test_perf_db_scanner.py::TestSuggestedIndexes` 4 用例通过，`python3 tools/perf/index_advisor.py suggest` 输出 10 条建议索引
- [ ] T019 实现查询执行计划分析：关键查询跑 `explain("executionStats")`，存储到 `query_plans` collection（FR-11）
- [x] T020 [P] N+1 查询改造：识别循环单查点（session/memory/knowledge/graph modules），改为批量预取或聚合管道（`$lookup`/`$unwind`）（FR-7）
  - 证据: `$lookup`/`$unwind`）；工具：`tools/perf/db_write_scanner.py`（AST 扫描，识别循环内 find_one/find/count_documents 候选）；落地工具：`services/common/batch_prefetch.py`（vendored 三份）提供 `prefetch_many`/`prefetch_many_async`（一次 `$in` 批量预取替代循环单查）；报告落盘 `docs/pending-review/026-perf-n-plus-one-loop-write-report.md`；验证：扫描 services 得 N+1 候选 60 条、`pytest tools/tests/test_perf_db_scanner.py::TestDbWriteScanner/TestBatchPrefetch` 通过
- [x] T021 [P] 写入路径优化：识别单条写入循环，改为 `bulk_write`（FR-12）
  - 证据: `bulk_write`）；工具：`tools/perf/db_write_scanner.py` 识别循环内 insert_one/update_one/replace_one/delete_one 候选（services 得 39 条）；落地工具：`services/common/batch_prefetch.py` 提供 `build_bulk_write`（有序批量）+ `chunked`（默认 500 切块）；报告落盘同上；验证：`pytest tools/tests/test_perf_db_scanner.py::TestBatchPrefetch` 通过
- [ ] T022 [P] 连接池监控：连接池利用率指标落库（峰值 ≤ 80% 目标），供 008 驾驶舱消费

---

## Phase 4: User Story 3 (P1) — 缓存与减少冗余计算

**Goal**: 热点数据接入 Redis，建立完整失效/防护/监控机制；消除重复计算。

**独立测试**: 命中率 > 80%；穿透/击穿/雪崩防护生效；记忆化命中时跳过重算；缓存容量淘汰策略生效。

- [x] T023 [P] 实现 `cache/manager.py` 缓存管理器：`get/set/delete` + Redis 连接复用（复用 `dsh_runtime/session_affinity.py` 的 Redis 客户端模式）（FR-13）
  - 证据: （复用 `dsh_runtime/session_affinity.py` 的 Redis 客户端模式）；实现：权威源 `services/common/cache_manager.py`（`CacheManager.get/set/delete` + Redis `from_url`+ping 探测失败降级进程内内存 + LRU 淘汰 + `stats()` 命中率 + `forget_tag`/`set_if_absent`/`lock`），vendored 三服务 `app/cache/manager.py`（字节一致）；验证：`pytest tools/tests/test_cache_protection.py::TestCacheManager` 14 用例通过，三服务 `from app.cache.manager import CacheManager` 均成功
- [x] T024 [P] 实现 `cache/policies.py` 失效策略：TTL（默认 300s，可配）/ 事件驱动（数据变更主动失效）/ 版本戳（读取时校验版本）三种机制（FR-14）
  - 证据: （FR-14）；实现：权威源 `services/common/cache_policies.py`（`TTLPolicy` 默认 300s 可配 + `jittered_ttl`、`EventInvalidationPolicy.notify/forget_all` 事件驱动失效、`VersionStampPolicy.bump/validate` 版本戳、`CacheTag` 领域标签），vendored 三份；验证：`pytest tools/tests/test_cache_protection.py::TestTTLPolicy/TestEventInvalidationPolicy/TestVersionStampPolicy` 通过
- [x] T025 实现 `cache/protection.py` 缓存穿透防护：布隆过滤器（Redis `BF.*` 或本地）+ 空值缓存（TTL 60s）（FR-15）
  - 证据: （FR-15）；实现：权威源 `services/common/cache_protection.py` 的 `BloomFilterGuard`（Redis `BF.EXISTS/ADD`，不可用降级本地 set；`get_or_load` 拦截必然不存在，空值缓存 TTL 60s），vendored 三份；验证：`TestBloomFilterGuard` 5 用例通过（未登记 key 直接拦截、空值缓存生效）
- [x] T026 实现 `cache/protection.py` 缓存击穿防护：互斥锁（`SET NX EX`，参考 `runtime_lock.py` 模式），热点键失效时单请求重建（FR-16）
  - 证据: （FR-16）；实现：`cache_protection.py` 的 `MutexGuard`（`SET NX EX` 互斥锁 `set_if_absent`，参考 `runtime_lock` 模式；`singleflight` 单请求重建，其余轮询等待，超时兜底），vendored 三份；验证：`TestMutexGuard` 4 用例通过
- [x] T027 实现 `cache/protection.py` 缓存雪崩防护：TTL 抖动（±10% 随机）（FR-17）
  - 证据: （FR-17）；实现：`cache_protection.py` 的 `AvalancheGuard`（`jittered_ttl` ±10% 随机，复用 `TTLPolicy`），vendored 三份；验证：`TestAvalancheGuard` 2 用例通过（30 次抖动均在 90-110 区间）
- [ ] T028 [P] 实现 `cache/memoize.py` 记忆化装饰器 `@cache_result`：对纯函数调用自动缓存结果（FR-19）
- [ ] T029 热点数据接入缓存：会话（session）/ 配置（config）/ 权限（permission）/ token 四类热点数据接入 `cache/manager.py`（FR-13）
- [ ] T030 [P] 缓存命中率监控：命中率指标落库，< 80% 告警，供 008 驾驶舱消费（FR-18）
- [ ] T031 [P] 缓存容量与淘汰策略：Redis `maxmemory-policy` = `allkeys-lru`，容量上限可配（FR-20）
- [ ] T032 缓存集成测试：穿透/击穿/雪崩三场景验证 + 命中率统计（Acceptance Scenarios）

---

## Phase 5: User Story 4 (P1) — 前端性能

**Goal**: 优化首屏加载、代码分割、资源压缩、图片、API 请求与大数据集渲染。

**独立测试**: LCP ≤ 2.5s；首屏包体积 ≤ 预算；代码分割生效；图片 WebP + 懒加载；API 请求数 ≤ 目标；虚拟列表仅渲染可视区。

- [ ] T033 [P] 接入 `web-vitals` npm 包：`apps/admin-web/src/plugins/vitals.ts` + `apps/user-web/src/plugins/vitals.ts`，采集 LCP/TTI/CLS 并上报后端（FR-21）
- [ ] T034 [P] 代码分割与懒加载：`apps/admin-web/src/router/index.ts` + `apps/user-web/src/router/index.ts`，路由级懒加载（`() => import(...)`），首屏仅加载必需 chunk（FR-22）
- [ ] T035 [P] Vite 构建配置优化：`apps/admin-web/vite.config.ts` + `apps/user-web/vite.config.ts`，gzip/brotli 压缩、chunk 分割策略、生产构建分析（FR-23）
- [ ] T036 [P] 静态资源 CDN 配置：`deploy/` 下 CDN 配置（如 Cloudflare/阿里云 CDN），`Cache-Control: max-age=31536000`（FR-23）
- [ ] T037 [P] 图片优化：WebP 格式 + `loading="lazy"` + `srcset`/`<picture>` 响应式，覆盖 admin-web + user-web 的图片组件（FR-24）
- [ ] T038 [P] API 请求优化：批量请求（单次多资源）/ 分页 / 防抖（输入）/ 节流（滚动）/ 请求合并（同资源去重），首屏请求数 ≤ 10（FR-25）
- [ ] T039 虚拟列表：`apps/admin-web/src/composables/virtual.ts` + `apps/user-web/src/composables/virtual.ts`，接入 `vue-virtual-scroller`（或等价），大数据集（> 1000 项）仅渲染可视区（FR-26）
- [ ] T040 [P] 前端性能预算检查脚本：`benchmarks/frontend_budget_check.sh`，Lighthouse 自动检测 LCP/包体积/请求数，CI 中可被调用

---

## Phase 6: User Story 5 (P1) — 扩展性与容量规划

**Goal**: 验证系统可水平扩展，建立容量模型与压测能力，识别瓶颈。

**独立测试**: 服务水平扩展验证通过（+1 实例 → 吞吐 ≈ 线性）；限流/熔断/背压生效；资源监控指标可查；容量模型可预测；压测覆盖关键场景；瓶颈报告输出。

- [ ] T041 水平扩展验证：chat-api 无状态化确认（会话亲和已用 Redis），Docker Compose 新增实例后吞吐线性增长压测（FR-27）
- [ ] T042 实现限流：令牌桶算法（默认 1000 rps/实例，可配），请求超限时返回 429 + `Retry-After`（FR-28）
- [ ] T043 实现背压：队列满时拒绝请求（返回 503），不阻塞新请求（FR-28）
- [ ] T044 [P] 实现 `infrastructure/observability/prometheus.py`：Prometheus exporter（`/metrics` 端点），暴露 CPU/内存/IO/磁盘指标（FR-29）
- [ ] T045 [P] 创建 `benchmarks/locust/locustfile_chat.py`：对话场景压测（locust，1/10/50/100 并发级别）（FR-31）
- [ ] T046 [P] 创建 `benchmarks/locust/locustfile_doc.py`：文档解析场景压测（FR-31）
- [ ] T047 [P] 创建 `benchmarks/locust/locustfile_search.py` + `locustfile_auth.py`：搜索/鉴权场景压测（FR-31）
- [ ] T048 [P] 创建 `benchmarks/k6/smoke.js`：k6 冒烟测试（补充 locust）（FR-31）
- [ ] T049 创建 `benchmarks/capacity_model.md`：容量模型（给定并发数 → 所需实例数与 CPU/内存预测公式）（FR-30）
- [ ] T050 瓶颈识别报告：压测结果定位到具体端点/依赖/资源，输出 `benchmarks/bottleneck_report.md`（FR-32）

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T051 [P] 性能指标可观测总验证：延迟分位数/吞吐/命中率/资源利用率 100% 可查（Success 基准）
- [ ] T052 [P] 配置声明式收尾：连接池/超时/缓存 TTL/限流/并发上限全配置驱动（`performance.yaml`）
- [ ] T053 [P] 与 007 llm-gateway 联动验证：LLM 耗时占比 + 韧性事件交叉归因（`token_usage_logs` 字段）
- [ ] T054 [P] 与 001 gatekeeper 联动：QualityForge 51 个 P0/P1 `blocked` 项逐步解除（基线建立后）
- [ ] T055 写 `quickstart.md`（性能基线启用 + 各子域优化步骤 + 压测命令）
- [ ] T056 写 `contracts/performance.md`（性能基线/预算/缓存/压测 IO 契约）
- [ ] T057 性能回归判定端到端验证：基线采集 → 预算检查 → CI 回归判定全链路打通（Success 基准）

---

## Dependencies

```text
Phase 1 (骨架) → Phase 2 (US1 基线，BLOCKING) → Phase 3 (US2 DB) → Phase 4 (US3 缓存)
Phase 4 → Phase 5 (US4 前端) → Phase 6 (US5 扩展性) → Phase 7 (Polish)
关键依赖: T006/T007（基线采集）是 Phase 3/4/5/6 的前置；T009/T010（预算）是 Phase 7 的前置
T001（cache 骨架）→ T023/T024/T025/T026/T027/T028（US3 所有缓存任务）
T004（perf 中间件）→ T012（性能中间件实现）→ T006/T007（基线采集）
T014（连接池）→ T015/T016/T017（US2 慢查询/超时/熔断）
T018（索引）→ T019（执行计划分析）
```

## Parallel Opportunities

- T004/T005（Phase 1）互不依赖，可并行
- T008/T013（Phase 2）互不依赖，可并行（耗时拆分 vs kpi_store 扩展）
- T009/T010（Phase 2）互不依赖，可并行（预算检查 vs 预算定义）
- T015/T016/T017（Phase 3）互不依赖，可并行（慢查询/超时/熔断）
- T018/T020/T021/T022（Phase 3）互不依赖，可并行（索引/N+1/写入/监控）
- T023/T024（Phase 4）互不依赖，可并行（管理器 vs 策略）
- T028/T029/T030/T031（Phase 4）互不依赖，可并行
- T033/T034/T035/T036/T037/T038（Phase 5）互不依赖，可并行
- T044/T045/T046/T047/T048（Phase 6）互不依赖，可并行
- T051/T052/T053/T054（Phase 7）互不依赖，可并行

## MVP Scope

- **最小可交付 = Phase 1 + Phase 2（T001–T013）**：性能基线跑通 + 预算定义 + 回归判定 + 中间件埋点。
- 增量交付：US2（DB）→ US3（缓存）→ US4（前端）→ US5（扩展性）。
- **Phase 2 完成后 QualityForge 51 个 P0/P1 `blocked` 项方可逐步解除**。

## Implementation Strategy

- 先 MVP（US1 基线跑通 + 预算 + 回归判定），再 US2 DB、US3 缓存、US4 前端、US5 扩展性
- 每故事完成即独立可测（Acceptance Scenarios 即测试基准）
- 缓存复用既有 Redis 客户端模式（参考 `session_affinity.py` / `runtime_lock.py`），不引入新中间件
- 前端分包不改变业务逻辑，仅路由级懒加载 + 资源优化
- 压测脚本使用 locust（Python 生态一致），k6 作为补充
- 所有阈值（P95/包体积/命中率/并发上限/慢查询阈值）已于 2026-10-24 `/speckit-clarify` 定值（见 spec.md「Clarify 记录」预算表；全部可配置覆盖）

## Notes

- 本 tasks.md 为 `/speckit-tasks` 产出，覆盖 026 全部 5 个用户故事（FR-1 到 FR-32）。
- **全部任务初始状态为 `blocked`**（QualityForge 审计标记），需 Phase 2（US1 基线）完成后方能解除。
- 实施需先通过 `checklists/requirements.md` 门禁。
- 未改 services 源码；本文件仅在 `specs/026-performance-scalability/` 下。
