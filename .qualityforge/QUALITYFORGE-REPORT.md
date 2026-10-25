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
| 023 observability-resilience | 74 | 日志 / 追踪 / 指标 / 告警 / 容错 / 恢复 / 韧性测试 | 仓库内**未落盘编号区间**（原件缺失） | 123/126 🔨 | **已实现**（可观测 / 容错 / 恢复 / 韧性测试 4 子域关闭；T074/T075 待真实 Alertmanager 环境复测） |
| 024 deployment-hardening | 42（1 fail QF-818 + 41 blocked） | 部署安全 / 制品 / 灰度 / 回滚 / 灾备 | 811,815,816,817,818,819,822,823,824,825,827,828,831,833,834,835,836,837,840,844,848,854,856,857,858（另含发布流程相邻项 021,024） | 18/119 🔨 | **Phase 1 已落地**，US2–US4 未开工；QF-818 尚未复测 |
| 025 api-contract-hardening | 50 | 语义 / 错误 / 契约 / 演进 | 202,203,204,207,210,211,213,216,218,219,220,221,222,223,224,225,227,229,230,231,232,234,235,236,237,238,239,240,245,247,248,252,253,254,255,264,267,268,269,270 | 7/52 🔨 | **Phase 1 已落地**（错误结构统一 + trace_id + 唯一性门禁），US1–US4 未开工 |
| 026 performance-scalability | 51 | 性能 / 扩展性 / 效率 | 仓库内**未落盘编号区间**（原件缺失） | 5/57 🔨 | **Phase 1 骨架已建**，基线与优化未开工 |

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
| QF-818（024 唯一 fail） | 024 | 待复测 | 需重跑审计确认 `fail → pass`；未重跑前不得标 pass |
| 024 的 41 项 blocked | 024 | 部分解除 | Phase 1（T001–T010、T012、T014–T019）已建基线工具链，其余待 US2–US4 |
| 023 容错子域 | 023 | 已关闭 | Phase 6（T078–T094）全部完成，81 项韧性测试全绿 |
| 023 恢复子域 | 023 | 已关闭（带保留项） | Phase 7（T095–T115）全部完成；**RTO/RPO 无真实演练值**（开发机无 mongodump/mongosh/Swarm），`drill_az_failover.sh` 在非 Swarm 环境返回 2 而非假通过，故 T113 记录为「未演练」 |
| 023 韧性测试子域 | 023 | 已关闭（带保留项） | Phase 8（T116–T126）剧本与行为测试完成，三剧本 22 个行为场景全绿；**保留项**：真实 docker compose / Tempo / Loki / Prometheus / Alertmanager 链路实测未跑（本机 docker daemon 无响应），脚本在真实环境会以 `2` 退出而非假通过，此步骤留给 CI 或可用环境 |
| 025 的 50 项 | 025 | 大部分未解除 | 仅 Phase 1（T001–T007）落地 |
| 026 的 51 项 | 026 | 全部仍 blocked | 需性能基线（US1）建立后方可解除 |

---

## 变更记录

| 日期 | 变更 | 依据 |
|---|---|---|
| 2026-10-25 | 首次入库；重建 022–026 缺陷台账与 023 子域回写表；解除 T060/T077/B010 的"报告不入库"阻塞 | 用户决策"把 QF 报告纳入版本库"；仓库内 spec/tasks/测试证据 |
| 2026-10-25 | 023 容错子域关闭（T078–T094 全部完成，含 T082 LLM 独立池 / T083 Mongo / T084 Redis，韧性测试 81 项全绿）；§1 023 进度按 tasks.md 实际勾选校正为 91/126（T094 随后一并勾选，当日终值 92/126） | `specs/023-observability-resilience/tasks.md` 勾选状态 + `services/chat-api/tests/resilience/` 实跑结果 |
| 2026-10-25 | 023 恢复子域关闭（T095–T115）；§1 023 进度校正为 113/126；§2 拆出「恢复」行并如实标注 RTO/RPO 未实测；§3 拆为「恢复子域 已关闭（带保留项）」与「韧性测试子域 未关闭」 | `specs/023-observability-resilience/tasks.md` 勾选 + `scripts/test_*.sh` 五个脚本测试 + `deploy/tests/` 275 项 + `docs/observability/rto-rpo.md` §5 |
| 2026-10-25 | 023 韧性测试子域关闭（T116–T124 完成，T125 全量回归，T126 本轮 QF 核对）；§1 023 进度校正为 123/126；§2「韧性测试」行从「未开工」改为「✅ 已关闭（带保留项）」并写入三剧本交付物与 22 个行为场景证据；§3 同步更新，并如实标注真实 compose 链路实测未跑 | `specs/023-observability-resilience/tasks.md` 勾选 + `scripts/verify_e2e_observability.sh` / `scripts/drill/inject_dependency_fault.sh` / `scripts/drill/full_recovery_drill.sh` 及其三套行为测试 + 三服务全量 pytest（chat-api 2909 / document-parser 22 / admin-api 1258，后者 1 项 032 既有失败）+ `quickstart.md` |
