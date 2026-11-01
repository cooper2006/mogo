# Feature Specification: Observability & Resilience Hardening

**Feature Branch**: `023-observability-resilience`

**Created**: 2026-10-11

**Status**: Draft

**Input**: QualityForge 审计（74 个 P0/P1 缺陷，覆盖可观测性、容错、恢复、韧性测试 4 个子域）。这些缺陷绝大多数为 **blocked**（基础设施缺口：日志非结构化、无健康检查、无指标暴露、无追踪、无告警、无熔断、无备份恢复、无 SLO），需要**从零建立生产级可观测性与韧性基础设施**，而非在既有模块上扩展。

## User Scenarios & Testing *(mandatory)*

用户故事按实施顺序排列，每个独立可交付、可测试。

### User Story 1 (P1) — 结构化日志与健康检查

三个服务（admin-api / chat-api / document-parser）统一输出 JSON 结构化日志（含 trace_id、span_id、tenant_id、user_id、service、level、message、ts），日志级别运行时可调，错误日志携带完整定位上下文，容器输出到 stdout；暴露 `/health`（存活）与 `/ready`（就绪）端点，启动时执行依赖自检。

**Acceptance Scenarios:**
- 任意一次请求 → 日志为 JSON 且字段稳定（`trace_id`/`span_id`/`tenant_id`/`user_id`/`level`/`ts`/`message`）
- 运行时切换 `LOG_LEVEL=DEBUG` → 后续日志立即生效（无需重启）
- 抛异常 → ERROR 日志含完整堆栈、请求路径、用户标识、租户标识
- `GET /health` → 返回进程存活状态（依赖不检查）
- `GET /ready` → 返回依赖就绪状态（MongoDB/Redis/LLM provider 可达），任一依赖不可达 → 503
- 启动自检失败（依赖不可达）→ 进程不退出但 `/ready` 返回 503，容器编排可感知

### User Story 2 (P1) — 分布式追踪

入口请求生成 `trace_id`，透传到所有下游调用（admin-api → chat-api → document-parser → LLM provider → 外部工具）；跨服务调用链可在追踪后端完整还原；日志可通过 `trace_id` 跳转追踪；异步任务（Celery/RQ/后台 worker）保留追踪上下文。

**Acceptance Scenarios:**
- 一次真实对话请求 → 在追踪后端能看到完整调用链（HTTP 入口 → 下游 HTTP → DB 查询 → LLM 调用）
- 日志条目含 `trace_id` → 点击可跳转到对应 span
- 异步任务（文档解析/后台批处理）→ 保留父 span 上下文（`trace_id` 与触发请求一致）
- 下游 HTTP 调用 → 自动注入 W3C `traceparent` header
- 追踪采样率可配（生产默认 10%，调试可临时 100%）

### User Story 3 (P1) — 指标与 SLO

按 Google SRE 黄金信号采集四类指标（延迟、流量、错误率、饱和度），覆盖请求维度（method/path/status/duration）；业务指标（会话数、消息数、LLM 调用数、token 用量、文档解析数）；指标维度基数受控（label 白名单 + 高基数字段哈希化）；定义 SLO 并计算错误预算；错误预算耗尽触发告警。

**Acceptance Scenarios:**
- Prometheus 抓取 `/metrics` → 可查询四个黄金信号（延迟分位、QPS、错误率、连接池/队列深度）
- 业务指标（会话/消息/LLM 调用/token）→ 可按租户/智能体维度聚合
- 高基数 label（user_id、session_id、path 参数）→ 哈希化或降级为枚举桶，PromQL 不 OOM
- SLO 定义（例：99.9% 请求 < 3s、LLM 调用错误率 < 1%）→ 错误预算数值可查
- 错误预算消耗速度异常 → 触发告警（见 US4）

### User Story 4 (P1) — 告警与排障

告警基于**用户可见症状**（SLO 违约、关键路径错误率突增）而非仅资源阈值（CPU 95%）；告警分级（P0/P1/P2）+ 静默 + 抑制；通知渠道含 IM webhook（钉钉/飞书/企业微信）+ 邮件；告警通知携带排障入口（Runbook 链接 + 相关 Grafana 面板链接 + 相关 span 查询链接）；排障手册覆盖高频故障场景；排障看板可逐层下钻（服务 → 依赖 → 单个请求）。

**Acceptance Scenarios:**
- SLO 违约（错误预算消耗速度 > 阈值）→ 告警触达值班责任人（IM + 邮件）
- P0 告警 → 电话/语音升级（或强制弹窗）；P1 → IM + 邮件；P2 → 仅记录
- 告警通知 → 含排障入口链接（Runbook + 相关 Grafana 面板 + Trace 查询）
- 同一根因多次触发 → 抑制规则去重（不重复打扰）
- 计划维护 → 静默窗口生效（不产生噪音告警）
- 排障手册 → 覆盖 MongoDB 不可达、LLM provider 超时、Redis 抖动、队列积压、证书过期 5+ 高频场景
- 排障看板 → 从"服务概览"下钻到"依赖健康"再到"单个慢请求 span"

### User Story 5 (P1) — 容错与弹性

对下游依赖（MongoDB、Redis、LLM provider、外部 HTTP API）实现：熔断器（半开策略 + 连续失败阈值）、超时层级递减（入口 30s > 下游调用 10s > 单次 LLM 调用 5s）、重试（指数退避 + 抖动，仅对可重试错误）、资源池隔离（关键依赖独立连接池）、背压与限流（请求队列深度上限、并发连接数限制）。

**Acceptance Scenarios:**
- MongoDB 连续失败 N 次（默认 5）→ 熔断器打开，后续请求快速失败（不排队等待）
- 熔断器半开 → 试探一个请求，成功则关闭、失败则重新打开
- 入口超时（30s）→ 上游 LLM 调用（10s）→ 单次请求（5s），层层递减（避免下游卡死拖垮上游）
- LLM 429/5xx/超时 → 指数退避 + 抖动重试（默认 3 次，与 007 一致）
- 关键依赖（MongoDB、Redis）→ 独立连接池，不与其他依赖共享池（避免连带影响）
- 队列深度超过阈值（默认 1000）→ 背压：返回 429 或降级响应，不崩溃
- 限流（租户级 QPS）→ 超出配额返回 429（与 001 gatekeeper 联动）

### User Story 6 (P1) — 恢复与灾备

MongoDB 自动备份（定时 mongodump，加密存储）+ 恢复演练（每季一次）；备份加密 + 保留策略（30 天本地 + 90 天异地）；跨可用区部署（Docker Compose 多副本 + 至少一主一备跨 AZ，单 AZ 故障存活）；故障转移能力（关键服务副本切换）；RTO/RPO 定义与实测（目标 RTO ≤ 30min、RPO ≤ 15min）；灾难恢复预案文档 + 演练记录归档。

**Acceptance Scenarios:**
- 自动备份定时执行（每小时/每日，可配）→ 备份文件加密落盘（AES-256）+ 上传异地存储
- 备份保留策略（30 天本地 + 90 天异地）→ 过期自动清理
- 恢复演练：从备份恢复到干净环境 → 数据一致性校验通过（抽样比对）
- 单 AZ 故障（模拟 Docker 宿主机宕机）→ 关键服务副本自动切换，用户请求无中断（RTO ≤ 30min）
- RTO/RPO 实测：从故障发生到服务恢复的时间 ≤ 30min，数据丢失窗口 ≤ 15min
- 灾难恢复预案 → 文档化 + 至少一次完整演练记录（含时间线、责任人、改进项）
- 备份密钥丢失场景 → 恢复失败演练（明确预案边界）

### Notes / Assumptions

- 本特性是**基础设施级建设**，QualityForge 审计中 74 个 P0/P1 缺陷绝大多数为 `blocked`（缺基础设施），需从零建立
- 覆盖范围：3 个 Python 服务（admin-api / chat-api / document-parser）+ 前端可选埋点（admin-web / user-web）+ Docker Compose 编排
- 首期用开源栈（structlog + OpenTelemetry + Prometheus + Grafana + Alertmanager），不引入商业 APM
- 首期单区域 + 备份，不做多区域灾备、不做全自动扩缩容
- 与既有特性的联动：001 gatekeeper（限流/配额/审计联动）、007 llm-gateway（重试/降级复用）、008 ops-dashboard（指标/告警数据源）
- 熔断/超时/退避默认参数需 `/speckit-clarify` 定值（与 007 已有值对齐）

## Functional Requirements

### US1 — 结构化日志与健康检查

- **FR-1**: 三个服务（admin-api / chat-api / document-parser）统一输出 **JSON 结构化日志**，字段稳定且包含 `ts`、`level`、`service`、`message`、`trace_id`、`span_id`、`tenant_id`、`user_id`（缺失时为 `null`，不省略键）
- **FR-2**: 日志级别运行时可调（DEBUG / INFO / WARN / ERROR），通过环境变量 `LOG_LEVEL` 或运行时端点 `/admin/log-level` 切换，**无需重启进程**
- **FR-3**: ERROR 级日志必须携带完整定位上下文：完整堆栈（`exc_info`）、请求方法/路径、租户标识、用户标识、下游调用耗时
- **FR-4**: 日志输出到 **stdout**（容器友好），不写文件、不依赖本机文件系统；日志采集由部署层（Filebeat / Vector）处理
- **FR-5**: 每个服务暴露 `GET /health`（存活检查，仅返回进程存活，不检查依赖）与 `GET /ready`（就绪检查，检查 MongoDB/Redis/关键下游可达性），依赖不可达时 `/ready` 返回 503
- **FR-6**: 启动时执行依赖自检（MongoDB ping、Redis ping、LLM provider 连通性、配置文件完整性），自检失败不退出进程但 `/ready` 返回 503，错误详情写日志

### US2 — 分布式追踪

- **FR-7**: 每个服务入口请求生成 W3C `trace_id`（128-bit）并写入日志上下文；若请求头已含 `traceparent`，优先使用上游 trace_id（跨服务传播）
- **FR-8**: 跨服务 HTTP 调用自动注入/提取 W3C `traceparent` header，实现 admin-api → chat-api → document-parser → LLM provider 的完整调用链
- **FR-9**: 日志与追踪可互相跳转：日志含 `trace_id` 字段，追踪后端可通过 trace_id 查询对应日志（Grafana 或 Loki 联动）
- **FR-10**: 异步任务（Celery/RQ/后台 worker）保留父 span 上下文（通过任务参数或 Redis key 传递 trace_id），异步任务产生的 span 与触发请求的 trace_id 一致

### US3 — 指标与 SLO

- **FR-11**: 每个服务暴露 Prometheus 格式 `/metrics` 端点（`/metrics`），采集黄金四信号：请求延迟（histogram）、请求流量（counter）、错误率（counter）、饱和度（gauge：连接池、队列深度、GC 停顿）
- **FR-12**: 业务指标（会话创建数、消息发送数、LLM 调用数、token 用量、文档解析数）按租户/智能体维度可聚合查询
- **FR-13**: 指标维度基数受控：高基数 label（user_id、session_id、path 动态参数）必须哈希化或降级为枚举桶，单指标 label 组合 ≤ 10000
- **FR-14**: SLO 定义（首期：可用性 99.9%、请求延迟 P99 < 3s、LLM 调用错误率 < 1%）+ 错误预算计算，错误预算数值可查询（Grafana 面板 + Prometheus recording rule）
- **FR-15**: SLO 违约（错误预算消耗速度超阈值）→ 触发告警（见 US4 FR-17）

### US4 — 告警与排障

- **FR-16**: 告警基于**用户可见症状**：SLO 违约、关键路径错误率突增、服务 `/ready` 失败；资源阈值告警（CPU/内存）降级为 P2 参考
- **FR-17**: 告警分级 P0（P0 需电话/语音升级或强制弹窗，值班响应 ≤ 5min）/ P1（IM + 邮件，响应 ≤ 15min）/ P2（仅记录，响应 ≤ 4h）+ 静默（维护窗口）+ 抑制（同一根因去重）
- **FR-18**: 告警通知携带排障入口：Runbook 链接、相关 Grafana 面板链接、Trace 查询链接（含 trace_id 过滤条件）
- **FR-19**: 排障手册（`docs/runbooks/`）覆盖至少 5 个高频故障场景（MongoDB 不可达、LLM provider 超时、Redis 抖动、队列积压、证书过期），每场景含症状/影响/根因/恢复步骤/事后复盘模板
- **FR-20**: 排障看板（Grafana）：从"平台概览"下钻到"服务健康"→"依赖健康"→"单个慢请求 span"，支持逐层下钻

### US5 — 容错与弹性

- **FR-21**: 对关键下游依赖（MongoDB、Redis、LLM provider）实现**熔断器**：连续失败达阈值（默认 5）→ 熔断打开，后续请求快速失败；半开策略试探（默认 30s 后放开 1 个请求，成功关闭、失败重新打开）
- **FR-22**: 超时层级递减（**默认值可配**）：入口请求 30s > 下游服务调用 10s > 单次 LLM/DB 操作 5s；每层超时后资源必须释放（不泄漏连接、不占用线程）
- **FR-23**: 重试（指数退避 + 抖动，默认基数 1.5s / 上限 30s / ±10% 抖动 / 最多 3 次，与 007 一致），**仅对可重试错误**（429 / 5xx / 超时）重试；401/403 立即失败
- **FR-24**: 资源池隔离：关键依赖（MongoDB、Redis、LLM HTTP client）使用**独立连接池**，不与其他依赖共享（避免连带影响）
- **FR-25**: 背压与限流：请求队列深度上限（默认 1000，超出返回 429 或降级响应）、并发连接数限制（按租户/按服务）；与 001 gatekeeper 的配额联动（001 负责策略决策，本特性负责执行层限流）

### US6 — 恢复与灾备

- **FR-26**: MongoDB 自动备份：定时 `mongodump`（默认每小时增量 + 每日全量），备份文件 **AES-256 加密** 落盘 + 上传异地存储（对象存储/S3 兼容）
- **FR-27**: 备份保留策略：本地 30 天 + 异地 90 天，过期自动清理；备份密钥独立管理（不进代码仓库，从密钥管理系统读取）
- **FR-28**: 恢复演练：每季度至少一次完整恢复演练（从备份恢复到干净环境 + 数据一致性校验），演练记录归档（时间线、责任人、RTO/RPO 实测值、改进项）
- **FR-29**: 跨可用区部署：关键服务至少一主一备跨 AZ 部署，单 AZ 故障存活（Docker Compose 多副本 + 外部负载均衡/Keepalived）
- **FR-30**: 故障转移能力：关键服务（chat-api、admin-api）副本故障自动切换（Liveness/Readiness 探针 + Compose restart policy）
- **FR-31**: RTO/RPO 定义与实测：目标 RTO ≤ 30min、RPO ≤ 15min；每季度实测并记录（演练报告含具体耗时与数据丢失窗口）
- **FR-32**: 灾难恢复预案文档化（`docs/runbooks/disaster-recovery.md`）：覆盖 MongoDB 数据丢失、LLM 供应商全面故障、宿主机宕机、证书过期、密钥泄露 5+ 场景，每场景含预案、恢复步骤、演练记录

## Non-Goals

- **不引入商业 APM 产品**（Datadog / New Relic / Dynatrace 等）—— 首期用开源栈（structlog + OpenTelemetry + Prometheus + Grafana + Alertmanager），成本可控
- **不实现多区域灾备**（跨地域双活/多活）—— 首期单区域 + 备份恢复，多区域属后续演进
- **不实现全自动扩缩容**（Kubernetes HPA / Karpenter）—— 首期 Docker Compose 手动扩容，自动扩缩容属后续演进
- **不实现前端（admin-web / user-web）完整性能监控**（RUM、Web Vitals）—— 首期仅后端 3 服务可观测性，前端埋点后续补
- **不替换现有日志采集方案**（若已有 Loki/ELK 则复用，否则本特性引入 Loki 或 Vector）
- **不修改业务代码逻辑**（本特性仅新增可观测性/韧性基础设施层，不侵入既有业务模块）
- **不做混沌工程自动化**（LitmusChaos / Chaos Mesh）—— 首期手动故障注入演练，自动化属后续演进
- **不做合规审计日志**（等保/PCI 等合规要求的审计日志）—— 首期仅功能性结构化日志，合规审计后续特性

## Success Criteria

- QualityForge 审计中可观测性 4 子域（可观测性、容错、恢复、韧性测试）的 **P0/P1 缺陷清零**（74 项全部关闭）
- **日志/追踪/指标/告警 4 个信号全链路贯通**：一次请求可通过 trace_id 在 4 个系统间跳转
- SLO 违约能在 5 分钟内触发 P0 告警并触达责任人（IM + 邮件）
- 下游依赖故障（MongoDB/Redis/LLM 超时）时，服务不崩溃且熔断生效（连续失败后快速失败）
- 备份可恢复：从备份恢复数据完整，恢复时间 ≤ RTO 目标（30min）
- 单 AZ 故障存活：模拟宿主机宕机后关键服务自动切换，用户无感知（RTO ≤ 30min）
- 所有变更向后兼容：不破坏既有 001/007/008 特性的行为

## Further Details

- 技术实现（structlog 配置、OpenTelemetry SDK、Prometheus client、Alertmanager 配置、熔断器实现）由 [plan.md](./plan.md) 承载
- 启用步骤与验证命令由 [quickstart.md](./quickstart.md) 承载
- 任务拆解（含文件路径）由 [tasks.md](./tasks.md) 承载
- 默认参数（熔断阈值 5 次连续失败 / 半开 30s、超时层级 30s→10s→5s、重试基数 1.5s/上限 30s/±10%/3 次、备份频率每小时增量+每日全量、RTO ≤ 30min / RPO ≤ 15min）已定值（见 Clarify 记录 OQ-3/OQ-7，2026-10-24）

### 跨特性关系（双向声明，2026-10-11）

- **与 001（gatekeeper）**: 001 负责**限流/配额策略决策**（工具调用次数、LLM token 用量、租户配额），本特性负责**执行层限流 + 背压 + 审计日志联动**；本特性的告警可触发 001 的自动降权
- **与 007（llm-gateway-resilience）**: 007 实现 **LLM 调用级 failover/降级/退避**（`llm/resilience/` 子模块），本特性实现**服务间与依赖级的熔断/超时/限流**；007 的退避参数（1.5s/30s/±10%/3 次）与本特性 FR-23 对齐，不重复实现
- **与 008（ops-dashboard）**: 本特性是 008 的**数据源**（Prometheus 指标、Grafana 面板、告警历史）；008 驾驶舱消费本特性的指标/追踪/告警数据展示业务视角
- **与 010（dag-orchestration）**: 010 的节点级重试包裹本特性的依赖级重试；追踪链路贯穿 010 DAG 节点与下游调用
- **与 002/003/004/005/006**（其他业务特性）: 本特性提供基础设施，业务特性无需感知；只需在入口注入 trace_id 即可（由中间件自动处理）

## Clarify 记录（/speckit-clarify，OQ-1~OQ-8 已于 2026-10-24 消解）

> 2026-10-24 由需求方逐条确认（QA R11 后续消解轮）。决策与依据如下；impact 行指受影响的 FR/tasks。

- **OQ-1 日志后端选型 — 决策：Loki（轻量自托管）**。理由：单机 Compose 内自托管、无云依赖可离线复现；LogQL 与 Grafana 同屏排障；ELK 资源开销不必要；纯 stdout 无法支撑 FR-20 逐层下钻的日志侧。**影响**：FR-1/FR-4、T009/T012。
- **OQ-2 追踪后端选型 — 决策：Tempo（配 OTel Collector）**。理由：与 Grafana/Loki 同栈、资源占用低于 Jaeger all-in-one，Grafana 内 trace↔logs 互跳；Zipkin 数据模型过旧。**影响**：FR-7~FR-13、T009/T011。
- **OQ-3 熔断库选型 — 决策：`pybreaker`**。理由：状态机语义（fail 计数→open、恢复窗口→half-open 单请求试探）与 FR-21 默认值（5 次/30s）逐字对应，代码量最小。**影响**：T004/T006~T008 依赖清单。
- **OQ-4 备份存储后端 — 决策：本地磁盘主存 + S3 兼容对象存储异地（复用 admin-api 既有 `oss2`，默认阿里云 OSS endpoint，驱动接口按 S3 兼容抽象）**。备份桶经配置项指定；未配置时降级为本地-only，降级状态必须在 /ready 与 health 中显式可见（不允许静默）。理由：仓库已有 oss2 依赖；FR-27「30 天本地 + 90 天异地」要求两种介质。**影响**：FR-26/FR-27。
- **OQ-5 告警升级渠道 — 决策：IM webhook（钉钉/飞书/企业微信，复用 013 多 IM 入口）+ 邮件双渠道；电话/语音列为 Non-Goal**。理由：013 已具备三家 IM 通道；Alertmanager webhook_configs 原生支持；P0 告警文案必须携带 Grafana 面板链接 + Runbook 链接（FR-18 排障入口）。**影响**：FR-16~FR-19、T013。
- **OQ-6 SLO 目标值 — 决策：可用性 99.9%、请求延迟 P99 < 3s、LLM 调用错误率 < 1%**（采纳 spec 建议值，与 FR-14 一致）。burn rate 告警窗口首期取 1h/6h 快速档与 6h/3d 慢档两组。**如实登记**：99.9% 即每月错误预算约 43min；首期部署为单机 Compose 无热备（见 OQ-8），该目标为「承诺 + 度量」口径，由 FR-15 错误预算耗尽告警暴露差距，不假装已具备热备达成能力。**影响**：FR-14/FR-15。
- **OQ-7 RTO/RPO 目标值 — 决策：RTO ≤ 30min、RPO ≤ 15min**（采纳 spec 建议值，与 FR-31 一致）。口径：两者均指 **MongoDB 数据面**（副本集 oplog 重建 + 备份恢复路径），2026-10-23 实测逻辑 dump 恢复耗时 ~2min、冷 tar ~8min，30min 目标有余量；应用层冷启动（compose up + 镜像在位）不计入 RTO 但须单独登记实测值。Redis 数据可丢，RPO 按 Redis 自身持久化配置如实声明（继承 024 Assumptions）。每季度演练实测并记录（FR-28/FR-31）。**影响**：FR-28~FR-31。
- **OQ-8 跨 AZ 实现方式 — 决策：单宿主机模拟 + 备份重建（如实声明）**。理由：部署形态为单机 Compose（024 Assumptions 已定、不引入 K8s/云托管），「跨可用区」在单宿主机上无法真实度量；首期以「compose 多副本 + 外部 LB 配置模板 + 单宿主机故障注入演练」验证恢复路径存在，FR-29 验收文案明示「单宿主机演练，非真实跨 AZ」。真实跨 AZ 留待云托管形态（后续特性）。**影响**：FR-29、SC 相应项。
