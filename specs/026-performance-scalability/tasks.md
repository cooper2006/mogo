# Tasks: Performance & Scalability Hardening

**Input**: Design documents from `/specs/026-performance-scalability/`

**Prerequisites**: plan.md (required), spec.md (required)

**Status**: 全部 `blocked` — QualityForge 审计标记 51 个 P0/P1 缺陷，需先建立性能基线（US1）方能解除。

**Organization**: 任务按用户故事分组，每组可独立实现与测试；`[P]` 标记可并行任务。**US1 是其他故事的前置条件**（无基线则无从度量优化收益）。

**Implementation Order**: US1 → US2 → US3 → US4 → US5

---

## Phase 1: Setup (Module Skeleton)

**Goal**: 搭建性能相关模块骨架，作为各故事共用的基础设施载体。

- [ ] T001 创建 `services/chat-api/app/cache/__init__.py` + `services/chat-api/app/cache/manager.py`（缓存管理器占位：`get/set/delete/lock` 接口，复用既有 Redis 客户端）
- [ ] T002 创建 `services/chat-api/app/infrastructure/observability/perf_baseline.py`（基线采集占位：P50/P95/P99 延迟 + 吞吐 RPS/TPS）
- [ ] T003 创建 `services/chat-api/app/infrastructure/observability/perf_budget.py`（性能预算检查占位：读 `performance.yaml`，对比基线）
- [ ] T004 [P] 创建 `services/chat-api/app/api/middleware/perf.py`（性能中间件占位：请求延迟埋点 → kpi_store）
- [ ] T005 [P] 创建 `benchmarks/` 目录结构 + `benchmarks/locust/` + `benchmarks/k6/` + `benchmarks/perf_baselines/baselines.yaml`（空占位）

---

## Phase 2: User Story 1 (P1) — 性能基线与度量 [BLOCKING]

**Goal**: 建立系统级性能基线，定义性能预算，接入 CI 回归检查。**本 Phase 完成后其他故事方可解除 `blocked`**。

**独立测试**: 关键端点 P95/P99 基线落库；吞吐按并发级别可查；外部依赖耗时占比可拆分；性能预算 CI 检查生效。

- [ ] T006 实现 `perf_baseline.py` 延迟采集：基于 `spans.py` 的 span 数据聚合 P50/P95/P99（按端点 + 方法分类），落库 `perf_baselines` collection
- [ ] T007 实现 `perf_baseline.py` 吞吐采集：按并发级别（1/10/50/100）记录 RPS（对话）/ TPS（文档解析），落库
- [ ] T008 实现 `execution_trace.py` 外部依赖耗时拆分：每次请求拆分 DB / Redis / LLM / 外部 API 耗时占比，汇总到基线（FR-3）
- [ ] T009 [P] 实现 `perf_budget.py` 预算检查：读 `benchmarks/perf_baselines/baselines.yaml`，检查 P95 ≤ 阈值、包体积 ≤ 预算，输出通过/失败
- [ ] T010 [P] 定义 `benchmarks/perf_baselines/baselines.yaml`：关键端点显式预算（对话 P95 ≤ 2s、文档解析 ≤ 5s、鉴权 ≤ 500ms、admin-web ≤ 500KB、user-web ≤ 300KB、缓存命中率 ≥ 80%、并发上限 1000 rps/实例）——阈值需 `/speckit-clarify` 确认
- [ ] T011 实现 `perf_budget.py` 回归判定：新构建基线 vs 历史基线，P95 超阈值（如 +20%）标记为回归，CI 中告警（FR-5）
- [ ] T012 实现 `api/middleware/perf.py` 性能中间件：请求级延迟埋点 → `kpi_store.incr` → span 记录，接入 chat-api / admin-api / document-parser（FR-1/FR-2）
- [ ] T013 [P] 扩展 `kpi_store.py`：新增延迟分位数计数器（P50/P95/P99），支持按端点维度聚合（FR-1）

---

## Phase 3: User Story 2 (P1) — 数据库性能

**Goal**: 消除慢查询、N+1、缺失索引；建立查询超时与熔断、连接池管理；优化写入路径。

**独立测试**: 慢查询 < 阈值且告警；索引覆盖率 > 95%；连接池配置合理；N+1 改造完成；查询超时生效。

- [ ] T014 扩展 `core/db.py` 连接池配置：`maxPoolSize`（默认 100）/ `minPoolSize`（默认 10）/ `maxIdleTimeMS`（默认 30000）/ 连接泄漏检测（> 90s 告警）（FR-10）
- [ ] T015 启用 MongoDB `slow_query_log`：阈值可配置（默认 100ms），超阈值查询落库 `slow_queries` collection 并告警（FR-6）
- [ ] T016 实现查询超时：所有查询设置 `maxTimeMS`（默认 5000ms，可配），慢查询不阻塞其他请求（FR-9）
- [ ] T017 [P] 实现查询熔断：错误率 > 50% 触发熔断，降级返回缓存或明确错误（FR-9）
- [ ] T018 [P] 索引策略：按访问模式建立复合索引与覆盖索引（session/config/permission/token/document collections），索引覆盖率 > 95%（FR-8）
- [ ] T019 实现查询执行计划分析：关键查询跑 `explain("executionStats")`，存储到 `query_plans` collection（FR-11）
- [ ] T020 [P] N+1 查询改造：识别循环单查点（session/memory/knowledge/graph modules），改为批量预取或聚合管道（`$lookup`/`$unwind`）（FR-7）
- [ ] T021 [P] 写入路径优化：识别单条写入循环，改为 `bulk_write`（FR-12）
- [ ] T022 [P] 连接池监控：连接池利用率指标落库（峰值 ≤ 80% 目标），供 008 驾驶舱消费

---

## Phase 4: User Story 3 (P1) — 缓存与减少冗余计算

**Goal**: 热点数据接入 Redis，建立完整失效/防护/监控机制；消除重复计算。

**独立测试**: 命中率 > 80%；穿透/击穿/雪崩防护生效；记忆化命中时跳过重算；缓存容量淘汰策略生效。

- [ ] T023 [P] 实现 `cache/manager.py` 缓存管理器：`get/set/delete` + Redis 连接复用（复用 `dsh_runtime/session_affinity.py` 的 Redis 客户端模式）（FR-13）
- [ ] T024 [P] 实现 `cache/policies.py` 失效策略：TTL（默认 300s，可配）/ 事件驱动（数据变更主动失效）/ 版本戳（读取时校验版本）三种机制（FR-14）
- [ ] T025 实现 `cache/protection.py` 缓存穿透防护：布隆过滤器（Redis `BF.*` 或本地）+ 空值缓存（TTL 60s）（FR-15）
- [ ] T026 实现 `cache/protection.py` 缓存击穿防护：互斥锁（`SET NX EX`，参考 `runtime_lock.py` 模式），热点键失效时单请求重建（FR-16）
- [ ] T027 实现 `cache/protection.py` 缓存雪崩防护：TTL 抖动（±10% 随机）（FR-17）
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
- 所有阈值（P95/包体积/命中率/并发上限/慢查询阈值）需 `/speckit-clarify` 定值

## Notes

- 本 tasks.md 为 `/speckit-tasks` 产出，覆盖 026 全部 5 个用户故事（FR-1 到 FR-32）。
- **全部任务初始状态为 `blocked`**（QualityForge 审计标记），需 Phase 2（US1 基线）完成后方能解除。
- 实施需先通过 `checklists/requirements.md` 门禁。
- 未改 services 源码；本文件仅在 `specs/026-performance-scalability/` 下。
