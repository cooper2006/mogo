# Feature Specification: Performance & Scalability Hardening

**Feature Branch**: `026-performance-scalability`

**Created**: 2026-10-11

**Status**: Draft

**Input**: QualityForge 审计发现 **51 个 P0/P1 缺陷**（全部处于 `blocked` 状态，需先建立性能基线与优化能力方能解除）。覆盖领域：性能（延迟/吞吐/预算）、扩展性（水平扩展/容量规划）、效率（冗余计算/连接池/缓存）。

## User Scenarios & Testing *(mandatory)*

用户故事按依赖顺序排列，每个独立可交付、可测试。**US1 是其他故事的前置条件**（无基线则无从度量优化收益）。

### User Story 1 (P1) — 性能基线与度量

建立系统级性能基线，覆盖延迟分位数、吞吐、外部依赖耗时占比；定义性能预算并接入 CI；建立回归判定机制。

**Acceptance Scenarios:**
- 关键端点（对话、文档解析、鉴权）记录 P50/P95/P99 延迟基线，落库可查
- 吞吐基线按并发级别（1/10/50/100 并发）记录 RPS/TPS
- 外部依赖耗时占比分析：DB / Redis / LLM / 外部 API 各自耗时占比可查
- 性能预算定义：每个关键端点有显式预算（如 P95 ≤ 2s），CI 中可被检查
- 性能回归判定：新构建与基线对比，超出阈值则标记为回归

### User Story 2 (P1) — 数据库性能

消除慢查询、N+1 查询、缺失索引；建立查询超时与熔断、连接池管理；优化写入路径。

**Acceptance Scenarios:**
- MongoDB `slow_query_log` 启用并收集，阈值可配置，超阈值查询自动告警
- N+1 查询消除：批量预取或聚合管道替代循环单查
- 索引覆盖率 > 95%（所有读写集合有合理索引，复合/覆盖索引按访问模式建立）
- 查询超时（`maxTimeMS`）与熔断生效：慢查询不阻塞其他请求
- 连接池配置合理（`maxPoolSize`、`minPoolSize`、`maxIdleTimeMS`、泄漏检测）
- 读写分离（MongoDB 副本集 secondary 读）**首期不启用**，仅预留扩展点

### User Story 3 (P1) — 缓存与减少冗余计算

热点数据接入 Redis 缓存，建立完整的失效/防护/监控机制；消除重复计算。

**Acceptance Scenarios:**
- 热点数据缓存生效，命中率 > 目标（如 80%）
- 缓存失效策略正确：TTL / 事件驱动 / 版本戳三种机制按场景选用
- 缓存穿透防护：布隆过滤器或空值缓存，无穿透打到 DB
- 缓存击穿防护：互斥锁（`SET NX`），热点键失效时单请求重建
- 缓存雪崩防护：TTL 抖动（±10%）避免集中失效
- 无重复计算：记忆化/结果缓存命中时跳过重算

### User Story 4 (P1) — 前端性能

优化首屏加载、代码分割、资源压缩、图片、API 请求与大数据集渲染。

**Acceptance Scenarios:**
- LCP ≤ 2.5s（Core Web Vitals 标准）
- 首屏包体积 ≤ 预算（如 admin-web ≤ 500KB gzip、user-web ≤ 300KB gzip）
- 代码分割：路由级懒加载，首屏仅加载必需 chunk
- 图片优化：WebP + 懒加载 + 响应式尺寸适配
- API 请求优化：批量/分页/防抖/节流/请求合并，首屏请求数 ≤ 目标
- 虚拟列表：大数据集（> 1000 项）仅渲染可视区

### User Story 5 (P1) — 扩展性与容量规划

验证系统可水平扩展，建立容量模型与压测能力，识别瓶颈。

**Acceptance Scenarios:**
- 服务水平扩展：新增 chat-api 实例后吞吐线性增长（无状态 + 共享存储验证通过）
- 连接数与并发上限：限流/熔断/背压机制生效，超载时优雅降级
- 资源利用率监控：CPU/内存/IO 指标可查（Prometheus exporter）
- 容量模型：给定并发数可预测所需实例数与资源
- 压测覆盖关键场景（对话、文档解析、搜索、鉴权）
- 瓶颈识别：压测结果定位到具体端点/依赖/资源

### Notes / Assumptions

- **本特性是缺口新特性**：QualityForge 审计标记的 51 个 P0/P1 缺陷全部 `blocked`，需先建立性能基线（US1）方能解除阻塞
- **现有基础设施可复用**：
  - `services/chat-api/app/infrastructure/observability/`：`kpi_store.py`（`RuntimeKPIStore`）、`spans.py`、`execution_trace.py` 已有指标采集骨架
  - `services/chat-api/app/core/db.py`：`AsyncIOMotorClient` 已配置，但**无 slow_query_log / 无 maxTimeMS / 无连接池配置**
  - `services/chat-api/app/dsh_runtime/session_affinity.py` + `runtime_lock.py`：已使用 Redis（`redis.Redis.from_url`），但**无缓存层抽象**
  - `services/chat-api/app/llm/instrumented_client.py`：已有调用计量，但**无耗时占比拆分**
- **与特性 001（gatekeeper）的关系**：本特性的性能基线与门禁联动——QualityForge 审计的 `blocked` 状态由性能基线建立解除
- **与特性 007（llm-gateway）的关系**：本特性的"外部依赖耗时占比"包含 LLM 调用耗时，与 007 的韧性事件（`failover_from`/`degradation_step`）可交叉归因
- **与特性 008（ops-dashboard）的关系**：本特性的基线数据、压测结果、容量模型供 008 驾驶舱消费
- **MongoDB 读写分离**：US2 列出但 Non-Goals 明确首期不启用（仅预留扩展点，不实际拆分读写）
- **压测工具**：优先使用 `locust`（Python 生态一致），`k6` 作为补充
- **前端 Web Vitals**：依赖 `web-vitals` npm 包 + `vue-virtual-scroller`（或等价虚拟列表库）

## Functional Requirements

### US1 — 性能基线与度量

- **FR-1**: 关键端点（对话、文档解析、鉴权、文件上传、搜索结果）记录 P50/P95/P99 延迟基线，按端点 + 方法分类，数据落库（`perf_baselines` collection）
- **FR-2**: 吞吐基线按并发级别（1/10/50/100 并发）记录 RPS（对话）与 TPS（文档解析），数据落库
- **FR-3**: 外部依赖耗时占比分析：每次请求拆分 DB / Redis / LLM / 外部 API 耗时占比，汇总到基线
- **FR-4**: 性能预算定义（YAML 配置文件 `performance.yaml`，每个关键端点显式预算如 P95 ≤ 2s、包体积 ≤ 500KB），CI 中可被检查
- **FR-5**: 性能回归判定：新构建基线 vs 历史基线，P95 超阈值（如 +20%）标记为回归，CI 中告警

### US2 — 数据库性能

- **FR-6**: 慢查询识别：启用 MongoDB `slow_query_log`，阈值可配置（默认 100ms），超阈值查询记录到 `slow_queries` collection 并告警
- **FR-7**: N+1 查询消除：批量预取（`find_in_batch`）或聚合管道（`$lookup` / `$unwind`）替代循环单查，改造点逐个登记
- **FR-8**: 索引策略：按访问模式建立复合索引与覆盖索引，索引覆盖率 > 95%（所有读写集合有合理索引）
- **FR-9**: 查询超时与熔断：所有查询设置 `maxTimeMS`（默认 5s，可配），慢查询触发熔断后降级
- **FR-10**: 连接池配置：`maxPoolSize`（默认 100）、`minPoolSize`（默认 10）、`maxIdleTimeMS`（默认 30s）、连接泄漏检测（> 90s 未释放告警）
- **FR-11**: 查询执行计划分析：关键查询跑 `explain("executionStats")`，存储执行计划到 `query_plans` collection，供索引优化参考
- **FR-12**: 写入路径优化：批量写入使用 `bulk_write`，避免单条写入循环

### US3 — 缓存与减少冗余计算

- **FR-13**: 热点数据缓存：高频访问数据（会话、配置、权限、token）接入 Redis，热点键识别机制
- **FR-14**: 缓存失效策略：TTL（默认 5min，可配）/ 事件驱动（数据变更主动失效）/ 版本戳（读取时校验版本）三种机制按场景选用
- **FR-15**: 缓存穿透防护：布隆过滤器（Redis `BF.*` 或本地）+ 空值缓存（TTL 60s），无穿透打到 DB
- **FR-16**: 缓存击穿防护：互斥锁（`SET NX EX`），热点键失效时仅单请求重建，其他请求等待或返回旧值
- **FR-17**: 缓存雪崩防护：TTL 抖动（±10% 随机），避免大批键同时失效
- **FR-18**: 缓存命中率目标与监控：命中率 < 80% 告警，命中率指标落库供 008 消费
- **FR-19**: 避免重复计算：记忆化装饰器（`@cache_result`）+ 结果缓存（Redis），对纯函数调用自动缓存
- **FR-20**: 缓存容量与淘汰策略：Redis `maxmemory-policy` = `allkeys-lru`，容量上限可配

### US4 — 前端性能

- **FR-21**: 首屏加载时间度量：接入 `web-vitals` npm 包，采集 LCP / TTI / CLS 并上报
- **FR-22**: 代码分割与懒加载：路由级懒加载（`() => import(...)`），首屏仅加载必需 chunk，admin-web 首屏 ≤ 500KB gzip，user-web ≤ 300KB gzip
- **FR-23**: 资源压缩与 CDN：gzip/brotli 压缩，CDN 配置（`deploy/` 下），静态资源长期缓存（`Cache-Control: max-age=31536000`）
- **FR-24**: 图片优化：WebP 格式 + 懒加载（`loading="lazy"`）+ 响应式尺寸适配（`srcset` / `<picture>`）
- **FR-25**: API 请求优化：批量请求（单次请求多个资源）/ 分页 / 防抖（输入）/ 节流（滚动）/ 请求合并（同资源去重），首屏请求数 ≤ 10
- **FR-26**: 虚拟列表：大数据集（> 1000 项）使用虚拟滚动（`vue-virtual-scroller` 或等价），仅渲染可视区

### US5 — 扩展性与容量规划

- **FR-27**: 水平扩展：chat-api 无状态化（会话亲和已用 Redis），新增实例后吞吐线性增长（压测验证）
- **FR-28**: 连接数与并发上限：限流（令牌桶，默认 1000 rps/实例）+ 熔断（错误率 > 50% 熔断）+ 背压（队列满拒绝请求）
- **FR-29**: 资源利用率监控：CPU/内存/IO/磁盘指标通过 Prometheus exporter 暴露（`/metrics` 端点）
- **FR-30**: 容量模型：给定并发数 → 所需实例数与资源（CPU/内存）的预测公式，`capacity_model.md`
- **FR-31**: 压测工具与场景：`locust`（主）+ `k6`（补充），覆盖对话/文档解析/搜索/鉴权 4 类场景
- **FR-32**: 瓶颈识别：压测结果定位到具体端点/依赖/资源，输出瓶颈报告

## Non-Goals

- **不引入微服务拆分**（首期单体 + 模块化，保持 `services/chat-api` 单进程部署）
- **不引入读写分离数据库**（首期单库 + 缓存；MongoDB 副本集 secondary 读作为扩展点预留但不实际启用，索引/查询优化优先）
- **不实现自动弹性伸缩**（首期固定规格 + 容量模型指导手动扩缩，HPA/KEDA 作为后续特性）
- **不实现 LLM 响应缓存**（属 007 llm-gateway 独立能力，本特性仅度量 LLM 耗时占比）
- **不改造既有业务逻辑**（本特性仅加性能层，不改变端点语义、不改数据模型）
- **不引入新中间件**（首期仅复用既有 MongoDB / Redis，不引入 Kafka / Elasticsearch / CDN 商业服务）

## Success Criteria

- **性能基线建立**：关键端点 P50/P95/P99 基线数据落库，性能预算（`performance.yaml`）定义完成，CI 回归检查生效
- **数据库优化**：慢查询 < 100ms（阈值可配），索引覆盖率 > 95%，连接池利用率合理（峰值 ≤ 80%），N+1 改造完成
- **缓存优化**：命中率 > 80%，穿透/击穿/雪崩防护生效，无重复计算（记忆化命中时跳过重算）
- **前端优化**：LCP ≤ 2.5s，首屏包体积 ≤ 预算（admin-web ≤ 500KB / user-web ≤ 300KB gzip），首屏请求数 ≤ 10
- **扩展性可验证**：服务水平扩展验证通过（+1 实例 → 吞吐 ≈ 线性增长），容量模型可预测，压测覆盖关键场景，瓶颈报告输出

## Further Details

- 技术实现（基线采集、优化策略、压测脚本）由 plan.md 承载
- 实施顺序：US1（基线）→ US2（DB）→ US3（缓存）→ US4（前端）→ US5（扩展性），**US1 是其他故事的前置条件**
- 与 001（gatekeeper）联动：本特性基线建立后，QualityForge 的 51 个 P0/P1 `blocked` 项可逐步解除
- 与 007（llm-gateway）联动：本特性的"外部依赖耗时占比"包含 LLM 耗时，与 007 韧性事件可交叉归因
- 性能预算阈值（P95 / 包体积 / 命中率 / 并发上限）已定值（见「Clarify 记录」，2026-10-24）

### 跨特性关系（双向声明，2026-10-11）

- **与 001（gatekeeper）**：001 是治理门禁层（配额/凭据/审计），本特性 026 是性能基线层。QualityForge 审计标记的 P0/P1 缺陷需本特性基线建立解除 `blocked` 状态——二者是"治理门禁 ↔ 性能度量"的关系，不重叠。
- **与 007（llm-gateway）**：007 关注 LLM 调用韧性（failover/降级/退避/计量），本特性关注**耗时占比度量**（LLM 只是被度量的外部依赖之一）。007 写入 `token_usage_logs` 的韧性字段供 026 归因；026 的压测结果反向验证 007 的韧性收益。
- **与 008（ops-dashboard）**：026 的基线数据、压测结果、容量模型、命中率指标供 008 驾驶舱消费，008 提供可视化归因。
- **与 020（platform-multi-tenancy）**：020 的多租户隔离与 026 的连接池/限流配置正交——020 管"谁"能访问，026 管"多快"能访问。
- **与 025（api-contract-hardening）**：025 管 API 契约稳定性，026 管 API 性能稳定性——两个"稳定性"维度互补。

## Clarify 记录（/speckit-clarify，2026-10-24 消解）

> 本特性无编号 OQ，唯一待定项是「性能预算阈值需定值」（spec Further Details / tasks T010/Notes）。2026-10-24 按下表定值；全部阈值经配置层可覆盖（`performance.yaml` / `baselines.yaml`），定值是**默认预算**，不是硬编码。

| 预算项 | 默认值 | 口径 |
|---|---|---|
| 对话端点 P95 | ≤ 2s（chat-api，非 LLM 生成段；LLM 流式首 token 另计） | 服务端处理时延，不含网络与客户端渲染 |
| 文档解析 P95 | ≤ 5s（≤20 页 PDF，worker 侧端到端） | document-parser 任务提交→结果可读 |
| 鉴权端点 P95 | ≤ 500ms | admin-api `/api/auth/*` |
| admin-web 首屏包体积 | ≤ 500KB gzip | 构建产物 entrypoint 口径 |
| user-web 首屏包体积 | ≤ 300KB gzip | 同上 |
| 前端 LCP | ≤ 2.5s（内网基线环境） | Lighthouse，staging 实测 |
| 缓存命中率 | ≥ 80%（会话/热点查询域） | Redis info + 业务埋点，滚动 24h |
| 慢查询阈值 | ≥ 100ms 记录并告警（可配） | MongoDB `slow_query_log` |
| 查询超时 | `maxTimeMS` 默认 5000ms（可配） | 所有业务查询 |
| 连接池 | maxPool 100 / minPool 10 / maxIdle 30s / 泄漏告警 90s / 峰值利用率目标 ≤ 80% | 与 023 FR-24 资源池隔离共用配置 |
| 并发上限 | 1000 rps/实例（令牌桶，FR-28）；队列深度 1000，超出 429 | 单实例口径，容量模型据此外推 |
| 熔断（DB 依赖） | 错误率 > 50%（滚动 30s 窗口）打开，半开试探同 023 OQ-3 口径 | 与 023 FR-21 参数一致，pybreaker 共用 `services/common/dependency_guard.py` |
| P95 回归判定 | 新基线 vs 历史基线劣化 > 20% 判回归，CI 告警（非阻断，首期观察档） | T011 |

- 与 023 关系：本表熔断/超时/重试参数与 023 Clarify（2026-10-24）对齐，不重复定义；023 定"依赖守护框架"，026 定"性能预算数值"。
- tasks T010「阈值需 /speckit-clarify 确认」标注自本记录起解除；`baselines.yaml` 按上表落默认值。
