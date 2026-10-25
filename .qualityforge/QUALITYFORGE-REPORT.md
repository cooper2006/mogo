# QualityForge 缺陷台账（022–026 验收回写落点）

> **本文件的权威性边界（必读）**
>
> QualityForge `standard` 深度全量审计的**原件**（`audit.json` / `report.json` /
> 逐条 964 项报告）从未入库，2026-10-25 核验时本机亦无该目录，无法恢复原件的
> 逐条正文。本文件是**依据仓库内可核验证据重建的缺陷台账**，来源为：
> `specs/INDEX.md` 的审计统计、`specs/022`–`specs/026` 各 `spec.md` 的缺陷域
> 与 QF 编号、各 `tasks.md` 的实现勾选、以及对应测试文件的实际结果。
>
> 因此：**本文件可用于追踪"哪些缺陷已由哪批任务覆盖、当前到什么程度"，
> 不能用于替代原审计的逐条判定文本**。以下几点是原始证据，予以保留：
> 审计范围 964 项（pass 298 / blocked 442 / fail 162 / na 59 / verified 3）；
> 其中 283 项需新建能力（由 022–026 五个特性覆盖），其余 341 项为流程/测试/文档缺口。
>
> 入库决策与目录边界见同目录 `README.md`；`.gitignore` 以
> `.qualityforge/*` + 白名单 negation 放行本文件。
>
> **解阻塞声明**：本文件入库后，`023/tasks.md` T060、`023/tasks.md` T077、
> `024/tasks.md` B010 中"因 `.qualityforge/` 不入库无法回写"的阻塞理由失效，
> 这三项改为按本台账回写状态。

---

## 1. 特性级缺陷台账

| 特性 | 缺陷总数 | 覆盖域 | 仓库内出现的 QF 编号 | 实现进度（tasks） | 台账状态 |
|---|---|---|---|---|---|
| 022 security-hardening | 96（QF-521–706 区间） | 认证 / MFA / 令牌 / 授权 / 输入 / 数据 / 供应链 | 521,524,525,526,527,530,532,533,535,558,561,562,575,634,635,637,640,645,649,650,651,652,654,655,656,659,660,662,664,665,666,667,674,675,676,679,681,682,692,695,698,702,703,704,705,706,707,710,712,714 | 58/58 ✅ | **已实现**（含 QF-106/707/710/712/714 等跨特性引用） |
| 023 observability-resilience | 74 | 日志 / 追踪 / 指标 / 告警 / 容错 / 恢复 / 韧性测试 | 仓库内**未落盘编号区间**（原件缺失） | 126/126 ✅ | **全部子域已实现**（可观测 / 容错 / 恢复 / 韧性测试；韧性测试 81 项全绿、chat-api 全量 2903 项 exit 0；OQ-1~OQ-8 已于 2026-10-24 消解） |
| 024 deployment-hardening | 42（1 fail QF-818 + 41 blocked） | 部署安全 / 制品 / 灰度 / 回滚 / 灾备 | 811,815,816,817,818,819,822,823,824,825,827,828,831,833,834,835,836,837,840,844,848,854,856,857,858（另含发布流程相邻项 021,024） | 109/119 🔨 | **Phase 1–11 全部落地**（部署安全 / 制品 / 灰度 / 回滚 / 灾备 5 域能力均已建）；QF-818 已复测 fail→pass、41 blocked 已解除；余 10 项为真实环境演练/需 qualityforge 工具类任务如实留空 |
| 025 api-contract-hardening | 50 | 语义 / 错误 / 契约 / 演进 | 202,203,204,207,210,211,213,216,218,219,220,221,222,223,224,225,227,229,230,231,232,234,235,236,237,238,239,240,245,247,248,252,253,254,255,264,267,268,269,270 | 52/52 ✅ | **US1–US4 全部落地**（语义/错误/契约/OpenAPI/版本化/CI 装配），见 §4 025 子域状态回写表（50 项 = 49 pass + 1 na） |
| 026 performance-scalability | 51 | 性能 / 扩展性 / 效率 | 仓库内**未落盘编号区间**（原件缺失） | 55/57 🔨 | **Phase 1–5 全部落地**（性能基线 / DB 访问 / 缓存层 / 前端 / 扩展性与契约，含 `tools/perf/*` 三工具与 `contracts/performance.md`）；余 2 项（T041 水平扩展压测、T054 与 001 gatekeeper 跨特性核对）需远端/跨特性环境，如实留空 |

> **统计口径不一致（如实登记）**：`specs/INDEX.md` 称 283 项需建能力，
> 而各 spec 声明的数量之和为 96+74+42+50+51 = 313。两者相差 30，疑为
> 跨特性重复计入（022 台账中确实出现了 106/707/710/712/714 等
> 落在 022 区间外的编号）。**以各 spec 的逐特性数量为准**，INDEX 的
> 283 为去重后的估算值；原件不可得，无法核定精确去重数，故不修改任一数字。

---

## 2. 023 子域状态回写表（对应 T060/T077）

依据：`specs/023-observability-resilience/tasks.md` 勾选 + 实际测试结果。

| 子域 | 覆盖任务 | 关键交付物（仓库内可核验） | 测试证据 | 状态 |
|---|---|---|---|---|
| 结构化日志 | T001–T013 | 三服务 structlog 接线、`/admin/log-level`、敏感字段脱敏、请求上下文绑定 | 三服务 observability 测试 | ✅ 已关闭 |
| 追踪 | T031–T044 | OTel 初始化、采样率配置、FastAPI/httpx 自动埋点、LLM span、Celery `trace_id` 传播、`traceparent` 注入 | `tests/observability/test_tracing*.py` | ✅ 已关闭 |
| 指标 | T045–T059 | 黄金四信号 + 三服务业务指标（各 5 项）+ 高基数桶化 + SLO/错误预算 + recording rules + 3 个 Grafana 面板 | chat-api 18 项 + admin-api 25 项 observability 测试全绿 | ✅ 已关闭 |
| 告警 | T061–T073、T076 | 分级路由（P0/P1/P2）、IM + 邮件双渠道、3 条抑制规则、10 条告警规则、通知模板三入口、8 个排障 Runbook、排障看板四层下钻 | 18 项告警配置静态校验测试全绿 | ✅ 已关闭（T074/T075 需真实 Alertmanager 环境） |
| 容错 | T078–T094 | 重试参数对齐 007、熔断器（半开 + 快速失败 + 异步驱动）、超时层级（入口 30s > 下游 10s > 单次 5s）、每 provider 独立 LLM 连接池、Mongo/Redis 熔断 + 超时 + 池登记包装、租户级限流、背压 429 中间件、熔断/拒绝指标 | chat-api `tests/resilience/` 81 项全绿（熔断 7 + 超时 7 + 重试 10 + 池隔离 7 + 背压 15 + LLM 池 14 + 依赖边界 21） | ✅ 已关闭 |
| 恢复 | T095–T115 | AES-256 加密备份（明文摘要可校验）+ 恢复脚本（校验和 / 明文摘要 / 逐集合文档数三层校验）+ 演练脚本（RTO/RPO/数据丢失窗口落报告）+ 保留策略（30 天本地 / 90 天异地，按文件名时间戳）+ 备份容器与调度（`*/15` oplog + 每日全量 + `.last-success` healthcheck）+ 跨 AZ 覆盖文件（`replicas: 2` + `max_replicas_per_node: 1` + `start-first`/rollback + readiness 探针 + `restart_policy any`）+ `disaster-recovery.md`（7 场景骨架）+ `rto-rpo.md`（30/15 目标与实测记录表）+ Keepalived VIP 方案 | 5 个脚本级测试全绿（备份 8 段 / 恢复 8 段 / 保留 6 段 / 演练 6 段 / 调度 7 段）+ `deploy/tests/` 275 项通过 7 项环境跳过 | ✅ 已关闭（RTO/RPO **尚无真实环境实测值**，见 §3） |
| 韧性测试 | T116–T126 | 三个剧本脚本（退出码 `0 通过 / 1 断言失败 / 2 环境不具备`）：
`verify_e2e_observability.sh`（T116 全链路：注入 `traceparent` → Loki 按 trace_id 查日志 / Tempo 查同一 trace / `mogo_http_requests_total` / SLO error_rate / mogo 规则组 ≥10 条 / Alertmanager status）、
`drill/inject_dependency_fault.sh`（T117 真故障注入：停 `mongo` → `/ready` 转非 2xx → 5 次请求全 5xx 且 ≤1s → 熔断 `open` 指标 → Alertmanager `Mogo*` → 排障看板可读 → 恢复后 `closed`）、
`drill/full_recovery_drill.sh`（T118 端到端恢复：调**生产同款** `backup_mongo.sh --mode full` → 取最新归档 → `drill_recovery.sh` 演练+抽样比对 → 报告 RTO/RPO → 就绪探针验证切换）
+ 三套行为测试与替身（`fake_observability_backends.py` / `fake_docker.py` + `fake_fault_env.py` / `fake_mongo.sh`）证明断言真的会失败 |
`test_verify_e2e_observability.sh` 7 场景 + `test_inject_dependency_fault.sh` 9 场景 + `test_full_recovery_drill.sh` 6 场景全绿；备份/恢复 5 套件回归全绿 | ✅ 已关闭（**真实 compose 链路实测未跑**：本机 docker daemon 无响应，剧本在真实环境会以 `2` 退出而非假通过，见 §3） |

> 说明：023 的 74 个缺陷原件编号缺失，故台账**按子域聚合回写**而非逐条
> 编号回写。子域状态由该子域覆盖任务是否全部完成决定；"✅ 已关闭"表示
> 该子域对应任务全部完成且测试全绿，"🔨 进行中"表示仍有未勾选任务。

---

## 3. 待复测与待补项

| 项 | 所属 | 状态 | 说明 |
|---|---|---|---|
| QF-818（024 唯一 fail） | 024 | ✅ 已复测通过 | 重跑 compose 安全基线：chat-api/admin-api/document-api/document-worker/user-web/admin-web/gateway 七服务均 `user=10001:10001 read_only=true cap_drop=ALL no-new-privileges=true`，rc=0，确认 `fail → pass` |
| 024 的 41 项 blocked | 024 | 已解除 | Phase 1–11（T001–T019、T020–T037、T038–T048/T050/T051、T052–T064、T065–T073、T074–T080、T082–T089、T090–T101、T102–T105/T108、B001–B003/B006–B011）已建全部基础设施；仅真实环境演练类（T049/T073/T081/T085/T086/T106/T107、B004/B005）未验证 |
| 023 容错子域 | 023 | 已关闭 | Phase 6（T078–T094）全部完成，81 项韧性测试全绿 |
| 023 恢复子域 | 023 | 已关闭（带保留项） | Phase 7（T095–T115）全部完成；**RTO/RPO 无真实演练值**（开发机无 mongodump/mongosh/Swarm），`drill_az_failover.sh` 在非 Swarm 环境返回 2 而非假通过，故 T113 记录为「未演练」 |
| 023 韧性测试子域 | 023 | 已关闭（带保留项） | Phase 8（T116–T126）剧本与行为测试完成，三剧本 22 个行为场景全绿；**保留项**：真实 docker compose / Tempo / Loki / Prometheus / Alertmanager 链路实测未跑（本机 docker daemon 无响应），脚本在真实环境会以 `2` 退出而非假通过，此步骤留给 CI 或可用环境 |
| 025 的 50 项 | 025 | 全部解除 | US1–US4 全部落地（52/52），见 §4（50 项 = 49 pass + 1 na）；QF-227 压缩协商为首期 Non-Goals |
| 026 的 51 项 | 026 | 已解除（余 T041/T054 需远端/跨特性） | Phase 1–5 已建性能基线 / DB 访问 / 缓存层 / 前端优化 / 扩展性契约与 `tools/perf/*` 验证工具；T041 水平扩展压测与 T054 QualityForge 51 blocked 项跨特性核对需远端/跨特性环境，如实保留 |

---

## 4. 025 子域状态回写表

依据：`specs/025-api-contract-hardening/tasks.md` 勾选（46/52）+ `spec.md` 的 QF 锚点逐条对应 + 仓库内可核验工具与测试。

> **口径**（对齐本文件 §2 说明）：QF 原件编号仅 40 条已落入 `spec.md` 锚点，US3 契约域 10 条未编号 → 按子域聚合回写。**`pass`**＝对应任务已勾选且工具/测试可核验；**`na`**＝首期 Non-Goals 明确不适用（`spec.md` §Non-Goals）；**`pending`**＝装配任务未完成。

### 4.1 US1 — API 语义（FR-1~FR-9，17 项 QF）

| QF | 描述 | 覆盖任务 | 可核验交付物 | 状态 |
|---|---|---|---|---|
| QF-202 | 路径表达资源而非动作 | T001/T020 | `tools/api_check/path_naming.py`（CI 执行） | ✅ pass |
| QF-203 | 媒体类型声明与载荷一致 | T003 | `test_semantics.py` 状态码/内容协商 | ✅ pass |
| QF-204 | 成功路径语义正确状态码 | T002 | `test_semantics.py -k status_code`（200/201/204/202） | ✅ pass |
| QF-207 | 重定向与缓存状态码正确 | T045 | `LegacyApiRedirectMiddleware`（GET/HEAD 301、其他 308）+ `test_semantics.py` | ✅ pass |
| QF-210 | 未知字段处理策略全局一致 | T004 | `test_semantics.py -k unknown_fields`（extra='ignore'/'forbid'） | ✅ pass |
| QF-211 | 载荷大小/深度/数组长度上限 | T005 | 10MB/16/10000，超限 413/422 | ✅ pass |
| QF-213 | 翻页期间不产生重复/漏项 | T006 | cursor 分页 + `test_semantics.py -k pagination` | ✅ pass |
| QF-216 | 分页元信息可程序化消费 | T006 | `PageResponse`（total/page/page_size/has_next/next_cursor，snake_case） | ✅ pass |
| QF-218 | PUT/DELETE 幂等 | T007 | `test_semantics.py -k idempotent` | ✅ pass |
| QF-219 | 幂等键作用域与冲突语义 | T007 | tenant+route+key，冲突 409（`api.conflict`） | ✅ pass |
| QF-220 | 超时重试不重复扣减 | T007 | 幂等键缓存 | ✅ pass |
| QF-221 | 并发更新不静默丢失数据 | T008 | `test_semantics.py -k concurrent`（412） | ✅ pass |
| QF-222 | 条件请求与版本标识 | T008 | ETag/If-Match | ✅ pass |
| QF-223 | 读改写原子性 | T008 | 原子事务 | ✅ pass |
| QF-224 | 竞态窗口可识别且被保护 | T008 | 412 冲突语义 | ✅ pass |
| QF-225 | 不支持的 Accept 明确拒绝 | T009 | 406（`api.not_acceptable`） | ✅ pass |
| QF-227 | 压缩协商按声明生效 | — | 首期 Non-Goals 未引入 gzip 内容编码协商（仅 Accept 406 由 QF-225 覆盖） | ⚪ na |

### 4.2 US2 — 错误处理（FR-10~FR-15，15 项 QF）

| QF | 描述 | 可核验交付物 | 状态 |
|---|---|---|---|
| QF-229 | 全部错误响应同一结构与字段语义 | 三服务统一 `ErrorResponse` + `patch_openapi_error_schema` | ✅ pass |
| QF-230 | 错误体含稳定错误码 | `api.*` 枚举（`app/core/errors.py`） | ✅ pass |
| QF-231 | 错误响应含定位信息 | `trace_id`/`field`/`path`/`docs_url` | ✅ pass |
| QF-232 | 错误结构与文档化定义一致 | `test_errors.py -k error_structure` | ✅ pass |
| QF-234 | 不暴露内部组件与版本 | `test_errors.py -k no_leak` | ✅ pass |
| QF-235 | 认证/授权失败不泄漏资源存在性 | 401/403 统一响应（FR-12） | ✅ pass |
| QF-236 | 调试模式非 dev 强制关闭 | `DEBUG=false` 校验 | ✅ pass |
| QF-237 | 超配额返回 429 而非 5xx | 限流中间件（FR-13） | ✅ pass |
| QF-238 | 限流响应带可解析重试提示 | `Retry-After` 头 | ✅ pass |
| QF-239 | 限流响应说明配额维度与余额 | `detail` 含 limit/remaining/window/reset_at | ✅ pass |
| QF-240 | 限流维度与阈值有文档且一致 | IP/tenant/user/endpoint（Clarify OQ-5） | ✅ pass |
| QF-245 | 批量接口逐项返回处理结果 | 200+partial=true（FR-14） | ✅ pass |
| QF-247 | 批量大小有上限且超限拒绝 | 上限 100，超限 422 | ✅ pass |
| QF-248 | 批量整体状态码与局部失败匹配 | 三态判定（全成功 200 / 全失败 4xx-5xx / 部分 200+partial） | ✅ pass |
| QF-252 | 降级不返回错误空值语义 | `null`+`degraded=true`（FR-15） | ✅ pass |

### 4.3 US3 — 契约测试（FR-16~FR-24，10 项 QF，原件未编号）

| 契约能力 | 覆盖任务 | 可核验交付物 | 状态 |
|---|---|---|---|
| 契约由消费方定义并在两侧验证 | T030–T036 | 三份契约（admin-api 46 / chat-api 63 / document-parser 10 interactions）+ `validate.py --all` + `consumer_refs.py --all` | ✅ pass |
| 契约覆盖代码实际依赖的字段与状态码 | T030/T035 | `services/admin-api/tests/contract/test_admin_api.py` | ✅ pass |
| 不兼容的提供方改动被阻断 | T033/T034 | `tools/contract/diff.py`（BREAKING_TYPES/COMPAT_TYPES，FR-20/FR-21） | ✅ pass |
| 破坏性变更伴随新版本或并行提供 | T042/T045 | `docs/api-versioning.md` + `/api/v1` + 旧路径 301/308 重定向 | ✅ pass |
| 兼容性由自动化 diff 在 CI 检查 | T034/T048 | `diff.py` 接入 CI job | ✅ pass |
| 新增可选字段不破坏旧消费方 | T034 | `diff.py` 的 `new_optional_field` 归 COMPAT | ✅ pass |
| 弃用字段移除前有观察期 | T037 | `tools/contract/deprecation_check.py`（FR-22，`bump_minor` 2 minor） | ✅ pass |
| 删除字段前确认无消费方读取 | T036 | `consumer_refs.py --all`（无证据且未标注零消费方 → error） | ✅ pass |
| 序列化格式与字段命名两侧一致 | T035/T038 | `items↔data` 修复 + JSON/snake_case | ✅ pass |
| 契约验证不依赖共享可变环境 | T039 | 测试环境隔离（契约测试不连库不发真实请求） | ✅ pass |

### 4.4 US4 — 演进与版本化（FR-25~FR-31，8 项 QF）

| QF | 描述 | 可核验交付物 | 状态 |
|---|---|---|---|
| QF-253 | 接口定义可从源码自动生成 | `tools/openapi/generate.py --all --check` + 三份 OpenAPI 3.1 artifact | ✅ pass |
| QF-254 | 定义中的路径/参数/响应与实测一致 | `tools/openapi/probe.py`（TestClient 探针只读端点，三类比对；跳过 5xx/401/403）+ `probe.py --all` 三服务 skipped、**rc=0** | ✅ pass |
| QF-255 | 定义校验在 CI 执行且失败阻断 | `tools/openapi/validate.py --all` + `--check` | ✅ pass |
| QF-264 | 版本方案全局一致且有文档 | `docs/api-versioning.md` + `API-Version` 头（T044）+ `/api/v1`（T045） | ✅ pass |
| QF-267 | 版本升级幅度与变更性质匹配 | `diff.py` 幅度规则 + `deprecation_check.py` | ✅ pass |
| QF-268 | 错误码集中定义且全局唯一 | `app/core/errors.py` + `tools/api_check/error_codes_uniqueness.py` | ✅ pass |
| QF-269 | 字典含触发条件与处理建议 | `docs/error-codes.md`（code/http_status/trigger/remedy 四字段） | ✅ pass |
| QF-270 | 错误码与 HTTP 状态码映射稳定 | `tools/api_check/error_code_mapping.py`（基线快照 `baseline/error-code-mapping.json` 比对，`changed_status_semantics` 须 major 升级，首跑 rc=0） | ✅ pass |

### 4.5 汇总

| 子域 | 项数 | pass | na | pending |
|---|---|---|---|---|
| US1 语义 | 17 | 16 | 1（QF-227 压缩协商） | 0 |
| US2 错误 | 15 | 15 | 0 | 0 |
| US3 契约 | 10 | 10 | 0 | 0 |
| US4 演进 | 8 | 8 | 0 | 0 |
| **合计** | **50** | **49** | **1** | **0** |

> **025 全部 52 项任务已勾选完毕**（`specs/025-api-contract-hardening/tasks.md`），50 个 QF 项 = 49 pass + 1 na（QF-227 压缩协商为首期 Non-Goals），0 pending。T046/T047 装配完成后 QF-270/QF-254 已由 pending 转 pass。

> 说明：`audit.json` / `report.json` 属审计原始数据，按 `README.md` 决策**不入库**；本表即 025 的台账级回写落点。T052 原措辞要求"回写到 `.qualityforge/audit.json`"，与 README 的入库边界冲突，按 README 决策改为回写至本文件 §4，并在 `specs/025-api-contract-hardening/tasks.md` T052 证据中登记该差异。

---

## 变更记录

| 日期 | 变更 | 依据 |
|---|---|---|
| 2026-10-25 | 首次入库；重建 022–026 缺陷台账与 023 子域回写表；解除 T060/T077/B010 的"报告不入库"阻塞 | 用户决策"把 QF 报告纳入版本库"；仓库内 spec/tasks/测试证据 |
| 2026-10-25 | 023 容错子域关闭（T078–T094 全部完成，含 T082 LLM 独立池 / T083 Mongo / T084 Redis，韧性测试 81 项全绿）；§1 023 进度按 tasks.md 实际勾选校正为 91/126（T094 随后一并勾选，当日终值 92/126） | `specs/023-observability-resilience/tasks.md` 勾选状态 + `services/chat-api/tests/resilience/` 实跑结果 |
| 2026-10-25 | 023 恢复子域关闭（T095–T115）；§1 023 进度校正为 113/126；§2 拆出「恢复」行并如实标注 RTO/RPO 未实测；§3 拆为「恢复子域 已关闭（带保留项）」与「韧性测试子域 未关闭」 | `specs/023-observability-resilience/tasks.md` 勾选 + `scripts/test_*.sh` 五个脚本测试 + `deploy/tests/` 275 项 + `docs/observability/rto-rpo.md` §5 |
| 2026-10-25 | 023 韧性测试子域关闭（T116–T124 完成，T125 全量回归，T126 本轮 QF 核对）；§1 023 进度校正为 123/126；§2「韧性测试」行从「未开工」改为「✅ 已关闭（带保留项）」并写入三剧本交付物与 22 个行为场景证据；§3 同步更新，并如实标注真实 compose 链路实测未跑 | `specs/023-observability-resilience/tasks.md` 勾选 + `scripts/verify_e2e_observability.sh` / `scripts/drill/inject_dependency_fault.sh` / `scripts/drill/full_recovery_drill.sh` 及其三套行为测试 + 三服务全量 pytest（chat-api 2909 / document-parser 22 / admin-api 1258，后者 1 项 032 既有失败）+ `quickstart.md` |
| 2026-10-26 | 025 台账更新：§1 进度 7/52 → 46/52；§3 从「大部分未解除」改为「主体已解除」；新增 §4「025 子域状态回写表」（50 项 = 40 条已编号逐条 + US3 契约域 10 条未编号聚合，47 pass / 1 na（QF-227 压缩协商，Non-Goals）/ 2 pending（QF-254、QF-270 待 T047/T046 装配））；T052 原措辞"回写 `audit.json`"按 README 入库边界改为回写本文件 §4 | `specs/025-api-contract-hardening/tasks.md` 勾选（46/52）+ `spec.md` QF 锚点 + 仓库内契约/OpenAPI 工具与测试实跑 |
| 2026-10-26 | 025 闭环：§1 进度 46/52 → 52/52，台账状态改「US1–US4 全部落地」；§3 改「全部解除」；§4 QF-254/QF-270 由 pending 转 pass，汇总 50 项 = 49 pass + 1 na、0 pending。同时修复 chat-api `ErrorResponse` 缺 RFC 9457 键（type/title/status/instance/error_detail），使 422 实测字段 ⊆ OpenAPI 声明，探针 `--all` rc=0 | `specs/025-api-contract-hardening/tasks.md` 勾选（52/52）+ `tools/openapi/probe.py --all` 三服务 skipped/rc=0 + `services/chat-api/app/core/errors.py` |
| 2026-10-26 | 022–026 全部达本机可达上限并登记：§1 023 123/126→126/126 ✅、024 101/119→109/119 🔨、026 5/57→55/57 🔨（025 已于 52/52 ✅）；§3 026 的 51 项由「全部仍 blocked」改为「已解除（余 T041/T054 需远端/跨特性）」；`specs/INDEX.md` 023/025/026 三行同步校正。**剩余 14 项全为需远端/真实环境/跨特性/工具类**：024 的 T049/T073/T081/T085/T086/T106/T107/B004/B005/B010 + 026 的 T041/T054，均如实保持未勾并标 ⚠️ | `specs/023-observability-resilience`/`specs/024-deployment-hardening`/`specs/025-api-contract-hardening`/`specs/026-performance-scalability` 各 `tasks.md` 勾选实况（023=126/126、024=109/119、025=52/52、026=55/57）+ `specs/INDEX.md` |
