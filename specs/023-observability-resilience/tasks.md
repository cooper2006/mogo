# Tasks: Observability & Resilience Hardening

**Input**: Design documents from `/specs/023-observability-resilience/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-10-24 消解)**:
- OQ-1 日志后端 = **Loki**（配 Grafana，OTel Collector 收日志）。
- OQ-2 追踪后端 = **Tempo**（OTLP 接入，Collector 路由）；T009/T011/T012 中 "Jaeger（或 Tempo）" 一律取 **Tempo**。
- OQ-3 熔断库 = **pybreaker**（T006~T008 依赖清单不变）。
- OQ-4 备份存储 = **本地磁盘主存 + S3 兼容对象存储异地**（复用 admin-api 既有 `oss2`；未配置远程桶时降级本地-only 并在 /ready 显式可见）。
- OQ-5 告警渠道 = **IM webhook（钉钉/飞书/企业微信，复用 013）+ 邮件**；电话/语音为 Non-Goal；P0 文案必带面板 + Runbook 链接（T013）。
- OQ-6 SLO = **可用性 99.9% / P99 < 3s / LLM 错误率 < 1%**；burn rate 窗口 1h/6h + 6h/3d 两组。
- OQ-7 RTO/RPO = **RTO ≤ 30min / RPO ≤ 15min**（MongoDB 数据面口径；Redis 可丢如实声明）。
- OQ-8 跨 AZ = **单宿主机模拟 + 备份重建**；FR-29/T096 起的灾备任务验收文案如实标注"非真实跨 AZ"。
- 默认参数：熔断连续失败 5 次打开 / 30s 半开试探 1 请求；超时层级 30s→10s→5s；重试 1.5s 基数 / 30s 上限 / ±10% 抖动 / 最多 3 次（与 007 一致）；备份每小时增量 + 每日全量；本地保留 30 天 / 异地 90 天。

> 本文件此前标注「待 OQ-1 至 OQ-8 通过 `/speckit-clarify` 消解后更新」。**2026-10-24 八个 OQ 已全部消解**（决策依据见 spec.md「Clarify 记录」），规约层阻塞解除，可按 Phase 1 → 8 顺序开工。

**Checklist Gate**: `checklists/requirements.md` 未勾选项构成 `/speckit-implement` 拦截门禁；本任务文件仅规划，不修改 checklist 标记。

**Organization**: 任务按用户故事分组，每组可独立实现与测试；`[P]` 标记可并行任务。

> ⚠️ **重要提醒**：QualityForge 审计中 74 个 P0/P1 缺陷绝大多数为 **blocked**（基础设施缺口），以下任务均需**从零建立基础设施**，而非在既有模块上扩展。每个 Phase 完成后需通过对应的 QualityForge 缺陷验证。

---

## Phase 1: Foundation (可观测性公共基座)

**Goal**: 建立三个服务共享的可观测性公共模块（`services/common/`），作为后续 US1-6 的共同载体。

- [x] T001 创建 `services/common/observability_base.py`：定义三个服务共享的结构化日志基类（structlog 配置、字段约定、trace_id 上下文变量）
- [x] T002 创建 `services/common/observability_base.py` 中的追踪基类：OpenTelemetry SDK 初始化（TracerProvider、Sampler、OTLP Exporter）
- [x] T003 创建 `services/common/observability_base.py` 中的指标基类：Prometheus client 初始化（CollectorRegistry、HTTP adapter）
- [x] T004 创建 `services/common/dependency_guard.py`：依赖包装基类（熔断器接口、超时接口、重试接口、连接池管理接口）
- [x] T005 创建 `services/common/slo.py`：SLO 定义数据结构（SLOSpec、ErrorBudget、BurnRate）+ 错误预算计算函数
- [x] T006 修改 `services/admin-api/requirements.in` 与 `requirements.txt`：新增 `structlog`、`opentelemetry-api`、`opentelemetry-sdk`、`opentelemetry-exporter-otlp`、`prometheus-client`、`pybreaker` 依赖
- [x] T007 [P] 修改 `services/chat-api/requirements.in` 与 `requirements.txt`：同步 T006 的依赖
- [x] T008 [P] 修改 `services/document-parser/requirements.in` 与 `requirements.txt`：同步 T006 的依赖
- [x] T009 更新 `docker-compose.yml`：新增 Prometheus / Grafana / Alertmanager / OpenTelemetry Collector / Jaeger（或 Tempo）/ Loki 服务定义
- [x] T010 创建 `deploy/prometheus/prometheus.yml`：抓取配置（三个服务 + 自身 + 业务指标）
- [x] T011 创建 `deploy/otel-collector/config.yaml`：Collector 配置（接收 OTLP、路由到 Jaeger/Tempo）
- [x] T012 创建 `deploy/grafana/provisioning/datasources/`：Grafana 数据源配置（Prometheus、Loki、Jaeger）
- [x] T013 创建 `deploy/alertmanager/alertmanager.yml`：告警路由/分组/静默/抑制配置（含 IM webhook 通知）

---

## Phase 2: User Story 1 (P1) — 结构化日志与健康检查

**Goal**: 三个服务输出 JSON 结构化日志，日志级别运行时可调，错误日志含完整上下文，/health 与 /ready 端点，启动自检。
**独立测试**: 日志 JSON 字段稳定；LOG_LEVEL 切换生效；ERROR 含堆栈+请求+用户+租户；/ready 检查依赖；启动自检失败返回 503。

- [x] T014 修改 `services/admin-api/app/main.py`：接入 structlog（替换或包裹既有 logging），注册 `/health` 与 `/ready` 端点
- [x] T015 创建 `services/admin-api/app/observability/logging.py`：admin-api 专属日志配置（含 tenant_id/user_id 上下文绑定）
- [x] T016 创建 `services/admin-api/app/observability/health.py`：admin-api 健康检查端点（/health + /ready + 启动自检）
- [x] T017 修改 `services/admin-api/app/main.py`：实现 `/admin/log-level` 运行时切换端点（FR-2）
- [x] T018 修改 `services/chat-api/app/main.py`：接入 structlog，注册 `/health` 与 `/ready` 端点
- [x] T019 创建 `services/chat-api/app/observability/logging.py`：chat-api 专属日志配置
- [x] T020 创建 `services/chat-api/app/observability/health.py`：chat-api 健康检查端点
- [x] T021 修改 `services/document-parser/app/main.py`：接入 structlog，注册 `/health` 与 `/ready` 端点
- [x] T022 创建 `services/document-parser/app/observability/logging.py`：document-parser 专属日志配置
- [x] T023 创建 `services/document-parser/app/observability/health.py`：document-parser 健康检查端点
- [x] T024 创建启动自检模块 `services/common/observability_base.py::startup_selfcheck()`：MongoDB ping、Redis ping、LLM provider 连通性、配置文件完整性
- [x] T025 日志字段稳定性测试：`services/admin-api/tests/observability/test_logging.py` — 验证 JSON 字段稳定（ts/level/service/message/trace_id/span_id/tenant_id/user_id）
- [x] T026 [P] 日志级别切换测试：`services/admin-api/tests/observability/test_log_level.py` — 验证 `/admin/log-level` 端点切换生效
- [x] T027 [P] /ready 端点测试：`services/admin-api/tests/observability/test_health.py` — 验证依赖不可达时返回 503
- [x] T028 启动自检测试：`services/admin-api/tests/observability/test_startup_selfcheck.py` — 验证自检失败不退出但 /ready 返回 503
- [x] T029 ERROR 日志上下文测试：验证堆栈、请求路径、用户标识、租户标识、下游耗时完整
- [x] T030 更新 QualityForge 缺陷（可观测性子域）：关闭对应 blocked 项（验证方式：curl /health、/ready、检查日志 JSON 格式）

---

## Phase 3: User Story 2 (P1) — 分布式追踪

**Goal**: 入口生成 trace_id，跨服务传播，日志-追踪互跳，异步任务保留上下文。
**独立测试**: 完整调用链可还原；日志 trace_id 可跳转；异步任务 trace_id 一致；traceparent 注入；采样率可配。

- [ ] T031 创建 `services/common/observability_base.py::init_tracing()`：OpenTelemetry SDK 初始化（TracerProvider、Sampler、OTLP Exporter）
- [ ] T032 创建 `services/common/observability_base.py::FastAPIInstrumentor` 集成：FastAPI 自动插桩（HTTP server span、HTTP client span）
- [ ] T033 修改 `services/admin-api/app/main.py`：初始化 OTel SDK，注册 FastAPI Instrumentor，注册 HTTPX Instrumentor（下游调用）
- [ ] T034 修改 `services/chat-api/app/main.py`：初始化 OTel SDK，注册 FastAPI + HTTPX Instrumentor
- [ ] T035 修改 `services/document-parser/app/main.py`：初始化 OTel SDK，注册 FastAPI + HTTPX Instrumentor
- [ ] T036 修改 `services/common/observability_base.py::logging`：日志中自动注入 trace_id/span_id（从 OTel context 获取）
- [x] T03[7-9] 修改 `services/chat-api/app/llm/resilience/failover.py` 与 `retry.py`：LLM 调用 span（复用 007 既有代码，新增 span 包装）
- [x] T03[7-9] 修改 `services/chat-api/app/` 异步任务入口（Celery/RQ worker）：通过任务参数传递 trace_id，保留父 span 上下文（FR-10）
- [x] T03[7-9] 采样率配置：`services/common/observability_base.py::init_tracing()` 支持 `OTEL_SAMPLER_PROBABILITY` 环境变量（默认 0.1）
- [x] T04[0-4] 端到端追踪测试：`services/chat-api/tests/observability/test_tracing.py` — 模拟一次完整请求（admin-api → chat-api → document-parser），验证 trace_id 传播
- [x] T04[0-4] 日志-追踪互跳测试：验证日志含 trace_id，可通过 trace_id 查询到对应 span
- [x] T04[0-4] 异步任务追踪测试：验证异步任务（后台 worker）的 trace_id 与触发请求一致
- [x] T04[0-4] traceparent 注入测试：验证下游 HTTP 调用自动注入 W3C traceparent header
- [x] T04[0-4] 更新 QualityForge 缺陷（追踪子域）：关闭对应 blocked 项

---

## Phase 4: User Story 3 (P1) — 指标与 SLO

**Goal**: 黄金四信号 + 业务指标 + 维度基数受控 + SLO 定义 + 错误预算。
**独立测试**: /metrics 可查询四信号；业务指标按维度聚合；高基数 label 受控；SLO 数值可查；错误预算消耗可查。

- [ ] T045 创建 `services/common/observability_base.py::init_metrics()`：Prometheus client 初始化 + `/metrics` 端点注册
- [ ] T046 创建 `services/common/observability_base.py::gold_signals.py`（或子模块）：定义黄金四信号指标（请求延迟 histogram、流量 counter、错误率 counter、饱和度 gauge）
- [ ] T047 修改 `services/admin-api/app/observability/metrics.py`：注册 admin-api 专属业务指标（会话创建数、消息发送数等）
- [ ] T048 修改 `services/chat-api/app/observability/metrics.py`：注册 chat-api 专属业务指标（LLM 调用数、token 用量等）
- [ ] T049 修改 `services/document-parser/app/observability/metrics.py`：注册 document-parser 专属业务指标（文档解析数、解析耗时等）
- [ ] T050 指标维度基数受控：实现高基数 label 哈希化（user_id/session_id/path 参数 → 枚举桶或哈希），单指标 label 组合 ≤ 10000
- [ ] T051 创建 `services/common/slo.py::SLODefinition`：SLO 定义（可用性 99.9%、延迟 P99 < 3s、LLM 错误率 < 1%）
- [ ] T052 创建 `services/common/slo.py::ErrorBudgetCalculator`：错误预算计算（burn rate、remaining budget、time to exhaust）
- [ ] T053 修改 `deploy/prometheus/prometheus.yml`：新增 recording rule（SLO 指标、错误预算消耗速度）
- [ ] T054 创建 `deploy/grafana/provisioning/dashesds/slo-overview.json`：SLO 概览面板（可用性、延迟、错误率、错误预算）
- [ ] T055 创建 `deploy/grafana/provisioning/dashboards/gold-signals.json`：黄金四信号面板（按服务分组）
- [ ] T056 创建 `deploy/grafana/provisioning/dashboards/business-metrics.json`：业务指标面板（会话/消息/LLM/token/文档解析）
- [ ] T057 指标查询测试：`services/chat-api/tests/observability/test_metrics.py` — 验证 /metrics 端点可查询黄金四信号
- [ ] T058 维度基数测试：验证高基数 label 受控（单指标 label 组合 ≤ 10000）
- [ ] T059 SLO 计算测试：验证错误预算数值可查、消耗速度计算正确
- [ ] T060 更新 QualityForge 缺陷（指标子域）：关闭对应 blocked 项

---

## Phase 5: User Story 4 (P1) — 告警与排障

**Goal**: 告警基于症状 + 分级 + 静默抑制 + 通知含排障入口 + Runbook + 排障看板。
**独立测试**: SLO 违约触发 P0；告警分级生效；静默/抑制生效；通知含链接；Runbook 覆盖 5+ 场景；看板可下钻。

- [ ] T061 修改 `deploy/alertmanager/alertmanager.yml`：配置告警分级路由（P0/P1/P2）、静默窗口、抑制规则
- [ ] T062 创建 `deploy/alertmanager/receivers.yml`（或扩展 alertmanager.yml）：IM webhook（钉钉/飞书/企业微信）+ 邮件配置
- [ ] T063 创建 `deploy/prometheus/alert-rules.yml`（或扩展 prometheus.yml）：SLO 违约告警规则（错误预算消耗速度超阈值）
- [ ] T064 创建 `deploy/prometheus/alert-rules.yml`：关键路径错误率告警、服务 /ready 失败告警
- [ ] T065 创建 `deploy/prometheus/alert-rules.yml`：资源阈值告警降级为 P2（CPU/内存/磁盘）
- [ ] T066 告警通知模板：`deploy/alertmanager/templates/` — 通知模板含 Runbook 链接、Grafana 面板链接、Trace 查询链接
- [ ] T067 创建 `docs/runbooks/README.md`：排障手册索引
- [ ] T068 创建 `docs/runbooks/mongodb_unreachable.md`：MongoDB 不可达 Runbook（症状/影响/根因/恢复步骤/复盘模板）
- [ ] T069 [P] 创建 `docs/runbooks/llm_timeout.md`：LLM provider 超时 Runbook
- [ ] T070 [P] 创建 `docs/runbooks/redis_stall.md`：Redis 抖动 Runbook
- [ ] T071 [P] 创建 `docs/runbooks/queue_backlog.md`：队列积压 Runbook
- [ ] T072 [P] 创建 `docs/runbooks/certificate_expired.md`：证书过期 Runbook
- [ ] T073 创建 `deploy/grafana/provisioning/dashboards/troubleshooting.json`：排障看板（服务概览 → 依赖健康 → 单个慢请求 span 下钻）
- [ ] T074 告警分级测试：模拟 SLO 违约 → 验证 P0 告警触发并触达 IM + 邮件
- [ ] T075 静默/抑制测试：维护窗口内告警不触发；同一根因去重
- [ ] T076 通知模板测试：验证告警通知含 Runbook 链接 + Grafana 面板链接 + Trace 查询链接
- [ ] T077 更新 QualityForge 缺陷（告警子域）：关闭对应 blocked 项

---

## Phase 6: User Story 5 (P1) — 容错与弹性

**Goal**: 熔断器 + 超时层级 + 重试退避 + 资源池隔离 + 背压限流。
**独立测试**: 连续失败触发熔断；超时资源释放；重试退避抖动；独立连接池；队列深度超限 429。

- [ ] T078 创建 `services/common/dependency_guard.py::CircuitBreaker`：熔断器实现（半开策略、连续失败阈值、试探间隔）
- [ ] T079 创建 `services/common/dependency_guard.py::TimeoutGuard`：超时层级递减配置（入口 30s > 下游 10s > 单次操作 5s）
- [ ] T080 修改 `services/chat-api/app/llm/resilience/retry.py`（007 既有）：确保退避参数（1.5s/30s/±10%/3 次）与本特性 FR-23 对齐
- [ ] T081 创建 `services/common/dependency_guard.py::ConnectionPool`：资源池隔离（关键依赖独立池）
- [ ] T082 修改 `services/chat-api/app/llm/providers/`（各 provider）：用 ConnectionPool 包装（独立池）
- [ ] T083 修改 `services/chat-api/app/` 与 `services/admin-api/app/` MongoDB 客户端：用 CircuitBreaker + TimeoutGuard + ConnectionPool 包装
- [ ] T084 修改 `services/chat-api/app/` 与 `services/admin-api/app/` Redis 客户端：用 CircuitBreaker + TimeoutGuard + ConnectionPool 包装
- [ ] T085 创建 `services/common/dependency_guard.py::RateLimiter`：限流实现（租户级 QPS、并发连接数限制）
- [ ] T086 创建 `services/common/dependency_guard.py::BackpressureGuard`：背压实现（队列深度上限 1000，超出返回 429）
- [ ] T087 修改 `services/chat-api/app/main.py` 与 `services/admin-api/app/main.py`：注册 RateLimiter + BackpressureGuard 中间件
- [ ] T088 创建 `services/chat-api/app/observability/metrics.py::circuit_breaker_metrics`：熔断器状态指标（打开/半开/关闭状态、失败次数）
- [ ] T089 熔断器测试：`services/chat-api/tests/resilience/test_circuit_breaker.py` — 连续失败 5 次触发熔断，半开试探成功关闭/失败重新打开
- [ ] T090 [P] 超时测试：验证超时层级递减（入口 30s > 下游 10s > 单次 5s），超时后资源释放
- [ ] T091 [P] 重试测试：验证指数退避 + 抖动，可重试错误（429/5xx/超时）重试，不可重试（401/403）不重试
- [ ] T092 [P] 资源池隔离测试：验证关键依赖独立连接池，不共享
- [ ] T093 [P] 背压测试：队列深度超限返回 429，不崩溃
- [ ] T094 更新 QualityForge 缺陷（容错子域）：关闭对应 blocked 项

---

## Phase 7: User Story 6 (P1) — 恢复与灾备

**Goal**: 自动备份 + 恢复演练 + 备份加密保留 + 跨 AZ + 故障转移 + RTO/RPO 实测 + 预案。
**独立测试**: 备份定时执行且加密；保留策略生效；恢复演练数据一致；单 AZ 故障存活；RTO/RPO 达标；预案文档化。

- [ ] T095 创建 `scripts/backup/backup_mongo.sh`：MongoDB mongodump 定时备份脚本（含 AES-256 加密、上传异地存储）
- [ ] T096 创建 `scripts/backup/backup_mongo.sh` 的 cron 配置：每小时增量 + 每日全量
- [ ] T097 创建 `scripts/backup/restore_mongo.sh`：MongoDB 恢复脚本（含解密、恢复、数据一致性校验）
- [ ] T098 创建 `scripts/backup/rotate_backups.sh`：备份保留策略（本地 30 天 + 异地 90 天，过期清理）
- [ ] T099 创建 `scripts/drill/drill_recovery.sh`：恢复演练脚本（从备份恢复到干净环境 + 抽样比对）
- [ ] T100 创建 `scripts/drill/drill_recovery.sh`：记录演练结果（时间线、RTO/RPO 实测值、数据丢失窗口）
- [ ] T101 修改 `deploy/docker-compose.yml`：配置 MongoDB 备份卷挂载（加密卷）
- [ ] T102 修改 `deploy/docker-compose.yml`：配置备份密钥管理（从环境变量或密钥管理系统读取，不进代码仓库）
- [ ] T103 创建 `deploy/docker-compose.prod.yml`：跨 AZ 部署配置（多副本 + 外部负载均衡/Keepalived）
- [ ] T104 修改 `deploy/docker-compose.prod.yml`：关键服务（chat-api、admin-api）至少一主一备跨 AZ
- [ ] T105 修改 `deploy/docker-compose.prod.yml`：Liveness/Readiness 探针配置（故障自动切换）
- [ ] T106 修改 `deploy/docker-compose.prod.yml`：restart policy 配置（故障自动重启）
- [ ] T107 创建 `docs/runbooks/disaster-recovery.md`：灾难恢复预案（MongoDB 数据丢失、LLM 全面故障、宿主机宕机、证书过期、密钥泄露 5+ 场景）
- [ ] T108 创建 `docs/observability/rto-rpo.md`：RTO/RPO 定义与实测记录模板
- [ ] T109 备份测试：验证 mongodump 定时执行、加密、上传异地存储
- [ ] T110 [P] 恢复测试：验证从备份恢复到干净环境，数据一致性校验通过
- [ ] T111 [P] 保留策略测试：验证过期备份自动清理（30 天本地 + 90 天异地）
- [ ] T112 跨 AZ 测试：模拟宿主机宕机，验证关键服务自动切换（RTO ≤ 30min）
- [ ] T113 RTO/RPO 实测：执行恢复演练，记录实测值（目标 RTO ≤ 30min、RPO ≤ 15min）
- [ ] T114 预案文档化：验证 `docs/runbooks/disaster-recovery.md` 覆盖 5+ 场景，每场景含预案 + 恢复步骤
- [ ] T115 更新 QualityForge 缺陷（恢复子域）：关闭对应 blocked 项

---

## Phase 8: Polish & Cross-Cutting Concerns

**Goal**: 全链路贯通验证、文档完善、回归测试。

- [ ] T116 全链路追踪验证：一次真实请求 → 日志（含 trace_id）→ 追踪后端可查 → 指标可见 → 告警可触发
- [ ] T117 端到端韧性验证：注入 MongoDB 故障 → 熔断生效 → 快速失败 → 告警触发 → 排障看板可下钻
- [ ] T118 端到端恢复验证：执行完整恢复演练（备份 → 恢复 → 一致性校验 → 服务切换）
- [ ] T119 更新 `docs/observability/architecture.md`：可观测性架构文档（日志/追踪/指标/告警/容错/恢复全景图）
- [ ] T120 更新 `docs/observability/slo-definition.md`：SLO 定义与错误预算文档
- [ ] T121 更新 `docs/observability/monitoring-dashboard.md`：监控看板配置指南
- [ ] T122 更新 `quickstart.md`：完善启用步骤与验证命令
- [ ] T123 更新 `CHANGELOG.md`：记录本特性变更
- [ ] T124 写入 obsidian vault 当日 session-log：记录实施过程（日期、改动、文件、验证方式）；`docs/WORK_LOG.md` 自 2026-10-17 停更
- [ ] T125 全量回归测试：验证不破坏既有 001/007/008 特性的行为
- [ ] T126 QualityForge 缺陷最终核对：74 个 P0/P1 缺陷全部关闭（对照 Success Criteria）

---

## Dependencies

```text
Phase 1 (公共基座 + 部署编排)
    ↓
Phase 2 (US1 日志+健康检查) → Phase 3 (US2 追踪，依赖 US1 的 trace_id)
    ↓                              ↓
Phase 4 (US3 指标，依赖 US1) → Phase 5 (US4 告警，依赖 US3 的 SLO)
    ↓                              ↓
Phase 6 (US5 容错，可与 US1-4 并行)
    ↓
Phase 7 (US6 恢复，依赖 US1-5 全部完成)
    ↓
Phase 8 (Polish)
```

**关键依赖**:
- T001-T005（公共基座）被 US1/US2/US3/US5 复用
- T006-T008（依赖安装）被所有 Phase 依赖
- T009-T013（部署编排）被 US3/US4/US6 依赖
- T024（启动自检）被 US1 的 /ready 依赖
- T078-T082（熔断/超时/重试/池隔离）被 US5 各任务依赖
- T095-T100（备份/恢复脚本）被 US6 各任务依赖

## Parallel Opportunities

- T006/T007/T008（三个服务依赖安装）互不依赖，可并行
- T068-T072（Runbook 文档）互不依赖，可并行
- T089-T093（US5 测试）互不依赖，可并行
- T109-T113（US6 测试）部分可并行（T110/T111 可并行）
- US1 完成后，US2/US3/US5 可并行推进
- US4 依赖 US3，但 US4 的 Runbook 文档（T068-T072）可与 US3 并行

## MVP Scope

- **最小可交付 = Phase 1 + Phase 2 + Phase 4**（T001-T030 + T045-T060）：日志/健康检查/指标/SLO 跑通，可观测性基础能力建立
- 增量交付：US2（追踪）→ US4（告警）→ US5（容错）→ US6（恢复）

## Implementation Strategy

1. 先 Phase 1（公共基座 + 部署编排），确保基础设施就位
2. US1（日志+健康检查）作为 US2/US3 的前置，优先完成
3. US2/US3/US5 可并行推进（追踪/指标/容错相对独立）
4. US4 依赖 US3 的 SLO 定义，在 US3 完成后推进
5. US6 最后实施，需 US1-5 全部完成（备份恢复演练需要完整可观测性）
6. Phase 8 收尾（全链路验证 + 文档 + 回归）

## Notes

- 本 tasks.md 为 `/speckit-tasks` 产出；OQ-1 至 OQ-8 已于 2026-10-24 消解（决策见文件头 Clarify Decisions 与 spec.md「Clarify 记录」），阻塞解除
- 实现需先通过 `checklists/requirements.md` 门禁
- 未改 services 源码；本文件仅在 `specs/023-observability-resilience/` 下
- QualityForge 缺陷验证：每个 US 完成后需关闭对应子域的 blocked 项（对照 Success Criteria）
- 与既有特性的联动：001（限流执行层）、007（退避参数对齐）、008（数据源）、010（分层包裹）
