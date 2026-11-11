# 特性规约总览（SDD Index）

> 📌 **口径提示（2026-10-05 更新）**：本文件记录的是 **spec/plan/checklist/tasks 的文档完成度**。
> **2026-10-03 落地审计**（`LANDING_AUDIT_2026-10-03.md`）判定 `landed` 0 · `partial` 10 · `hollow` 9，
> 该审计的**全部高危缺口已在 2026-10-03 至 2026-10-05 期间修复**（见各特性"已修"条目）。
> **017（three-scope-memory）与 021（unified-context-address）** 在 2026-10-05 优化轮完整实现：
> 密度轴 L0/L1/L2、渐进检索、`mogo://` 统一地址空间、四根适配器（memory/resource/skill/session）、
> 会话沉淀接线 —— 均已通过测试（2146 + 433 + 22 = 2601 项全绿，2026-10-05 基线）并具备生产接线。
> **📌 当前状态说明（2026-11-06，v3 / D4）**：上面三行的「完整实现 / 具备生产接线」为 **2026-10-05 历史快照**，仅指当时的文档与优化轮代码，不代表当前验收状态。按 v3 当前口径，**017 为 B0 / B1 已落地、B2–B7 进行中（尚未全部验收）**；范围轴已由 `workspace/org` **直接改名**为 `project/department`、**无运行时兼容层**（D4）。021 生产入口以 `POST /api/v1/context/resolve` 为准。详见下方 017 行、`specs/017-three-scope-memory/` 与 `contracts/memory-context-contract.md`。
> **2026-10-11 补充**：QualityForge 审计修复新增 022–026 共 5 个质量加固特性（安全/可观测性/部署/API/性能），
> 各含 spec + plan + tasks + quickstart 四件套（共 20 份文档，5530 行），覆盖 283 个 P0/P1 缺陷。
> 本文件下方的 spec/plan/checklist/tasks 计数已同步至该口径。
> **2026-10-13 补充**：新增 027（数据后端迁移：MongoDB → PanWeiDB），含 spec + plan + tasks +
> quickstart + checklist 五件套。该特性属**既有工作回溯补规格**（R1 代码先于 spec 落地），
> R1 已完成并实测通过，R2 起严格按 SDD 流程推进。本文件下方计数已同步至 **27 个特性**。
> **2026-10-16 补充**：新增 **030（本体数据权限）**，属**回溯补规格**（建表入库 + 运行时解析 +
> 管理端 API/前端代码先落地，本轮补 spec/plan/tasks）。本文件下方计数已同步至 **31 个特性**
> （含 028/029 会话轨迹与 SSO 接收方、030 本体数据权限、031 模型供应商发现与多协议接入）。
> **2026-10-18 补充**：新增 **031（模型供应商发现与多协议接入）**，属**回溯补规格**（后端 discover 五协议 + 三协议种子 + 前端「获取列表」弹窗与首次向导字段提示先于 spec 落地，本轮补 spec/plan/tasks，详见「四（补 5）」）。
>
> **2026-10-23 补充（AgentOS 整合批次）**：依据《企业 Agent OS 产品落地方案》与 mogo 的代码级对照评估（`docs/MOGO-AgentOS整合方案.md`，2026-10-23），新增 **032–044 共 13 个缺口特性**的 spec/plan/tasks 三件套。全部为**全新特性、代码尚未开工**（与 027/030/031 的"回溯补规格"相反，tasks 全部未勾选，按 SDD 正向推进）；形态边界遵循 `Decisions/ADR-7-触达层边界-移动端以IM入口覆盖.md`（移动端以 013 IM 入口覆盖，不单独做移动端、不做桌面端）。详见「四（补 6）」。
>
> **2026-10-31 补充（035/042 口径收敛落地）**：依据 `specs/035-cost-attribution/review-2026-10-30-dimension-source-audit.md`（业务线取消、空间→项目、企业→租户、042 整改批次 A/B/C）新增 **046–048 三个特性**（项目维度统一 / 配额可发现性 / 业务线维度删除），各含 spec + plan + tasks + checklist 四件套。**代码已落地（2026-11-01）**。046 34/34、047 30/30、048 13/13（tasks 全勾，与 CHANGELOG 一致）。详见「四（补 7）」。
>
> **2026-11-09 补充（StaffDeck 整合批次）**：依据 StaffDeck（AGPL-3.0 数字员工平台）与 mogo 的代码级对照评估（`docs/MOGO-StaffDeck整合方案.md`，2026-11-09），新增 **050–053 共 4 个全新特性**的 spec/plan/tasks/checklist 四件套（共 16 份文档）。**2026-11-09 已按三波次实现**：050 27/27、051 29/30（B1 + B2 全链路 + E2E 行为验证）、052 22/22、053 29/29 勾选（余 051 前端手工验收，如实留空，按 SDD 正向推进）。**2026-11-10 收尾**：四份 checklist 由 4 位 reviewer agent 代审完毕，050 16/16、051 17/17、052 17/17、053 17/17 全部达标（reviewer-owned，生成时不预勾，勾选由 reviewer 完成），并在各 spec「Non-Goals」前追加「判定口径补充（2026-11-10 /speckit-checklist 回填）」节逐条消解 CHK；051 B2 与 053 US3 P2 代码/端点契约已复核，052 T015 按「接管 = 050 跨模式挂起，P2 预留」定清首期软依赖边界。详见「四（补 9）」。**许可证红线**：StaffDeck 为 AGPL-3.0，与 mogo 社区许可不兼容——只借鉴设计思想，禁止拷贝任何代码。详见「四（补 9）」。
>
> **2026-11-10 补充（055 菜单管理）**：新增 `specs/055-menu-management/`（spec / plan / tasks / checklist 四件套，tasks 25/25 全勾）。**代码同轮落地**：admin-api `app/menu_settings/` + `GET|PUT|DELETE /api/v1/settings/menus`（租户级覆盖层）、admin-web `menuCatalog.ts` / `menuConfig.ts` / `useMenuOptions.ts` / `views/settings/MenuManagePage.vue`；入口挂在「权限中心」下。验收：admin-api 新增 27 项单测全通过、前端 `vue-tsc` + `vite build` 通过、路由/合并层 14 项断言 + 构建产物 15 项浏览器场景通过。**注**：054（资源中心）由其它会话在途，本条不重扫目录计数，待 054 落地后按发布流程统一重扫 specs 计数与 tasks 勾选数。
>
> **2026-11-04 三服务全量实测（OrbStack，镜像 `4abce5be`）**：admin-api 1519 passed / 1 skipped、
> document-parser 72 passed / 6 skipped、chat-api 3103 passed / 3 skipped（marker 过滤
> `not dsh_host_e2e and not network`，27 deselected；`MONGODB_URI=mongodb://mongo:27017`）；
> 三服务共 **4694 passed / 10 skipped / 0 failed**。chat-api 修正 2 个陈旧断言
> （`test_user_questions_api.py`，endpoint 语义变更未同步测试）后全绿。
> 上一版 2601 项（2026-10-05 基线）为陈旧计数，以此为准。specs 目录已达
> **2026-11-11 全量重扫口径：54 个特性**（001–053 + 055；054 由其它会话在途、磁盘未落地），其中 **50 份 `tasks.md` 已完整勾选**；余 **4 份部分勾选**：024 112/119（余 7 项环境类演练保留）、017 41/46（切换演练与真实浏览器 E2E 待维护窗口）、049 23/25（全链路手工验证 + 成员变更审计回归）、051 29/30（T028 浏览器目视验收待人工）。`tasks.md` 合计 **1681/1696 = 99.12%**（旧口径 49 特性 / 46 份全勾 / 1549/1563 已作废）。029/030/046/047 均已 100% 勾选（此前的「20/21、29/30、34/35、30/31」部分勾选表述为旧计数，已按磁盘实测更正）。本文件下方的
> spec/plan/checklist/tasks 计数已同步至该口径。
> 本文"已实现/✅"表述指**文档 + 代码 + 测试 + 生产接线**四层均已完成。

本索引汇总 `specs/` 下全部特性规约，按"既有能力回溯"与"缺口新特性"分组，标注每个特性的 spec/plan 完成度、对应规划文档条目与代码位置。

> 规划文档：`docs/MOVO企业级智能体功能补强规划.md`（§1.1 既有优势 / §1.2 不重复投入边界 / §2 GAP / §3 补强清单 / §4 路线图）

## 一、既有能力回溯规约（§1.1/§1.2 优势固化）

| 编号 | 特性 | 类型 | spec | plan | 对应规划 | 主要代码位置 |
|---|---|---|---|---|---|---|
| 003 | document-ingestion-delivery | 既有回溯 | ✅ | ✅ | §1.2 文档理解+内容生成 | `services/document-parser`、`chat-api/enterprise_capabilities/content` |
| 004 | skillhub-lifecycle | 既有回溯 | ✅ | ✅ | §1.2 SkillHub+ZIP 安装 | `admin-api/skill_lifecycle`、`chat-api/skills + skill_packages` |
| 005 | knowledge-rag-research | 既有回溯 | ✅ | ✅ | §1.1 企业知识/RAG | `chat-api/knowledge`、`document-parser` 检索 |
| 006 | position-rbac-admin | 既有回溯 | ✅ | ✅ | §1.1 管理后台 RBAC | `admin-api/position_roles` |

## 二、缺口新特性规约（§2 GAP / §3 补强清单）

| 编号 | 特性 | 对应规划 | 优先级 | spec | plan |
|---|---|---|---|---|---|
| 001 | gatekeeper-governance（六层门禁） | 清单 1（§2.1） | P0 | ✅ | ✅（3 OQ 待 clarify） |
| 002 | session-versioning（会话级版本化） | 清单 6（§2.6） | P1 | ✅ | ✅ |
| 007 | llm-gateway-resilience（网关韧性） | 清单 2（§2.2） | P0 | ✅ | ⏳ |
| 008 | ops-dashboard（总览驾驶舱） | 清单 3 | P0 | ✅ | ⏳ |
| 009 | hooks-interception（Hooks 拦截） | 清单 4（§2.3） | P1 | ✅ | ⏳ |
| 010 | dag-orchestration-engine（DAG 编排） | 清单 5（§2.4） | P1 | ✅ | ⏳ |
| 011 | dream-cycle-self-evolution（自进化） | 清单 7（§2.5） | P2 | ✅ | ⏳ |

## 三、P2 规模化生态后置清单（spec / plan 已建）

| 编号 | 特性 | 对应规划 | 优先级 | spec | plan |
|---|---|---|---|---|---|
| 012 | a2a-agent-gateway | 清单 8 | P2 | ✅ | ✅ |
| 013 | multi-im-entry | 清单 9 | P2 | ✅ | ✅ |
| 014 | business-semantic-index | 清单 10 | P2 | ✅ | ✅ |
| 015 | knowledge-graph-layer | 清单 11 | P2 | ✅ | ✅ |
| 016 | skill-market-hardening | 清单 12（市场强化部分） | P2 | ✅ | ✅ |
| 017 | three-scope-memory（叠加密度轴 L0/L1/L2 + 检索轨迹 + 会话结合，详见 021）。**依赖 049 项目成员 + ADR-9**；**状态：B0/B1 已落地，B2–B7 进行中**。目标态 `workspace/org → project/department` 直接改名、无运行时兼容层（D4），部门可见性含后代不含祖先（D3）、`default` 项目隔离（N2）、`project_owner_id` 消歧（N1）、C-7 成员变更审计首期必做；项目成员与管理端项目管理由 049 提供、017 只消费。**v3 设计文档**：[`design-2026-11-05-project-department-scopes.md`](./017-three-scope-memory/design-2026-11-05-project-department-scopes.md)；**发布手册**：[`rollout-017-d4-cutover.md`](./017-three-scope-memory/rollout-017-d4-cutover.md)；规格与验收：[`spec.md`](./017-three-scope-memory/spec.md) | 清单 13 | P2 | ✅ | ✅ |
| 021 | unified-context-address（统一上下文地址空间：memory/resource/skill/session 四根 + 检索轨迹 + 委托式鉴权） | 优化 017 引出（OpenViking 思路） | P2 | ✅ | ✅ |
| 018 | capability-asset-registration | 清单 14 | P2 | ✅ | ✅ |
| 019 | harness-elastic-config | 清单 15 | P2 | ✅ | ✅ |

> 规划清单 12 的"沉淀闭环（会话→经验→Skill）"已并入 011（Dream Cycle）；016 仅承载"市场强化"部分。

## 三（补）、平台化能力（新增范围，非原规划清单）

| 编号 | 特性 | 说明 | 优先级 | spec | plan | contracts | quickstart | tasks |
|---|---|---|---|---|---|---|---|---|
| 020 | platform-multi-tenancy（平台化多租户） | 补齐租户供给：新增 `tenants` 主表 + 平台管理员（`__platform__`）+ 引导流程改造 + 生命周期（归档/恢复/彻底清理）+ 配额默认不限额 | P0 | ✅ | ✅ | ✅ | ✅ | ✅ |

> 背景：数据层（集合按 `tenant_id` 分区）与认证层（登录可带 `tenantId`、跨租户选租户）已具备多租户能力，唯一缺口是租户供给。既有部署语义为"一套部署 = 一个企业"。
> 19 项待定决策已全部确认，记录在 `specs/020-platform-multi-tenancy/tasks.md` 的 Clarify Decisions；详细论证见 `docs/platform-multi-tenancy-plan.md`（v4）。

## 四、质量加固（QualityForge 审计修复，2026-10-11 新增）

| 编号 | 特性 | 说明 | 优先级 | spec | plan | quickstart | tasks |
|---|---|---|---|---|---|---|---|
| 022 | security-hardening（安全加固） | 96 个 P0/P1 缺陷：认证/MFA/令牌/授权/输入/数据/供应链 7 域 | P0 | ✅ | ✅ | ✅ | ✅（58/58） |
| 023 | observability-resilience（可观测性与韧性） | 74 个 P0/P1 缺陷：日志/追踪/指标/告警/容错/恢复 6 域 | P1 | ✅ | ✅ | ✅ | 🔨 **126/126**（Phase 1 T001–T013 + Phase 2 T014–T030 + Phase 3 T031–T044 + Phase 4 T045–T059 + Phase 5 T061–T073/T076：三服务 structlog 接线、/health /ready /admin/log-level 端点、启动自检、OTel 追踪 + 采样率配置、LLM span、Celery trace_id、traceparent 注入、Prometheus 黄金四信号 + 三服务业务指标 + 高基数桶化 + SLO/错误预算 + recording rule + 3 个 Grafana 面板、告警分级路由（P0/P1/P2）+ IM/邮件双渠道 + 3 条抑制规则 + 10 条告警规则（SLO 燃烧率/症状/资源）+ 通知模板三入口 + 8 个排障 Runbook + 排障看板四层下钻、18 项指标/SLO 测试 + 18 项告警配置静态校验全绿；Phase 6 T078–T081/T085–T093：熔断器（半开+快速失败）+ 超时层级 + 连接池隔离 + 租户级限流 + 背压 429 中间件（纯 ASGI）+ 熔断/拒绝指标，46 项韧性测试全绿；Phase 6 收尾 T082–T084/T094：每 provider 独立 LLM 连接池（`services/chat-api/app/llm/providers/pools.py`，句柄跟随事件循环 + connect/read 超时分档）+ Mongo/Redis 熔断·超时·池包装（双服务 `app/core/resilience.py`，超时计入失败以让挂死依赖可熔断）+ QF 容错子域回写，韧性测试增至 81 项全绿、chat-api 全量 2903 项 exit 0；pybreaker 1.4.1 的 `call_async` 依赖 tornado，已改为状态机原语自驱；T060/T077 已随 `.qualityforge/` 缺陷台账入库（提交 `0e38d8d`）完成 QF 回写；T074/T075 已于 2026-10-26 用真实 Alertmanager v0.27 端到端完成（镜像经镜像站拉取，提交 `250056a`/`1efd81f`）。Phase 7 T095–T115：AES-256 加密备份（`scripts/backup/backup_mongo.sh`，明文摘要 + 逐集合文档数入清单，口令缺失即失败不回退默认值）+ 恢复（`restore_mongo.sh`，校验和/明文摘要/文档数三层校验，目标库非空默认拒绝）+ 保留策略（`rotate_backups.sh`，30 天本地/90 天异地，按文件名时间戳而非 mtime）+ 恢复演练（`scripts/drill/drill_recovery.sh`，落 RTO/RPO/数据丢失窗口报告）+ 备份容器与调度（`container_run.sh`/`schedule.sh`，`*/15` oplog + 每日全量 + `.last-success` healthcheck）+ 跨 AZ 覆盖文件（`deploy/docker-compose.prod.yml`：关键服务 replicas 2 + 每节点最多 1 + start-first/rollback + readiness 探针 + restart policy any，探针脚本 `deploy/probes/`）+ 灾难恢复预案（`docs/runbooks/disaster-recovery.md`，7 场景骨架 + 跨 AZ 拓扑 + Keepalived 方案）+ RTO/RPO 文档（`docs/observability/rto-rpo.md`，30/15 目标与实测记录表），5 个脚本级测试（备份 8/恢复 8/保留 6/演练 6/调度 7 段）+ `deploy/tests/` 275 项通过 7 项环境跳过；**保留项（如实记录，不视为达标）**：RTO/RPO 无真实环境实测值（开发机无 mongodump/mongosh/Swarm，T113 标记「未演练」），`drill_az_failover.sh` 在非 Swarm 下返回 2 而非假通过，跨 AZ 按 OQ-8 属「单宿主机模拟 + 备份重建」口径；`deploy/tests/test_ontology_permission_mongo_parity.py` 需容器内 mongo 网络（030 遗留，skip 条件未生效），本机全量会红，与本轮无关。Phase 8 T116–T126：三个剧本脚本（`scripts/verify_e2e_observability.sh` T116 全链路：注入 traceparent 后用自生成 trace_id 反查 Loki/Tempo/Prometheus/Alertmanager；`scripts/drill/inject_dependency_fault.sh` T117 韧性：停 mongo→`/ready` 转非 2xx→5 次请求全 5xx 且 ≤1s→熔断 open 指标→Alertmanager `Mogo*`→排障看板→恢复后 closed，docker 调用全走 `timeout` 包装防 daemon 卡死挂死；`scripts/drill/full_recovery_drill.sh` T118 恢复：调生产同款 `backup_mongo.sh --mode full`→取最新归档→`drill_recovery.sh` 演练+抽样比对→报告 RTO/RPO→就绪探针验证切换）+ 三套行为测试 + 三替身（`fake_observability_backends.py` / `fake_docker.py`+`fake_fault_env.py` / `fake_mongo.sh`）共 22 场景全绿；退出码硬约定 `0 通过 / 1 断言失败 / 2 环境不具备`（2 不算通过，CI 应标 skipped）；文档 `architecture.md` §9 + `slo-definition.md` + `monitoring-dashboard.md` + 新建 `quickstart.md` + README 链接 + CHANGELOG；QF 报告回写韧性测试子域已关闭（提交 `dbf3bcb`）。**保留项（如实记录，不视为达标）**：真实 docker compose 链路实测未跑（本机 docker daemon 无响应，脚本在真实环境会以 2 退出而非假通过）；T074/T075 告警分级/静默抑制测试已于 2026-10-26 用真实 Alertmanager v0.27 端到端完成（6 用例全绿，提交 `250056a`/`1efd81f`），真实 Alertmanager 环境项已闭合；全量回归 admin-api 1258 项中 1 项失败 `tests/test_trust_rating.py::test_scanner_walks_ratings_and_records_state` 属 032 既有缺陷、与本特性无关。OQ-1~OQ-8 已于 2026-10-24 消解） |
| 024 | deployment-hardening（部署与发布） | 42 个 P0/P1 缺陷：部署安全/制品/灰度/回滚/灾备 5 域 | P1 | ✅ | ✅ | ✅ | 🔨 **112/119**（Phase 1–11 全部落地：非 root/只读/能力基线 T001–T019；镜像基线 T020–T037；灰度通道 T038–T048/T050/T051；特性开关 T052–T055；数据库迁移 T056–T060；发布检查单 T061–T064；备份自动化 T065–T073；跨区切换 T074–T080；DR 预案 T082–T089；证书 T090–T096；值班告警 T097–T101；监控容量 T102–T105/T108；收尾 B001–B003/B006–B011）。**保留项（如实留空不勾）**：T049/T073 已于 2026-10-26 隔离环境真实演练（独立复跑，见 `deploy/runbook/drills/2026-10-26-t049-t073-isolated-rerun.md`，T049 自动回滚实测 13.5s、T073 恢复 RTO=338.9s / RPO=141.2s，勾选数 112）；余 T081/T085/T086/T106/T107 真实环境演练、B004/B005 需真实 docker daemon，均未验证。**B010 已于 2026-10-26 凭仓库内台账 + 本机实测勾选**（QF-818 复测：`deploy/cli/baseline-check.sh --json` 63 pass/0 fail rc=0，七业务容器 `User=appuser`/uid 10001、`ReadonlyRootfs=true`、`CapDrop=[ALL]`、`NoNewPrivileges=true`；按 `.qualityforge/README.md` 口径复测回写台账级结论而非 audit.json） |
| 025 | api-contract-hardening（API 契约与语义） | 50 个 P0/P1 缺陷：语义/错误/契约/演进 4 域 | P1 | ✅ | ✅ | ✅ | ✅ **52/52**（US1–US4 全部落地：US1 语义（错误码统一结构 15 通用码 + 业务码登记表，含 trigger/remedy，FR-30）+ US2 错误（三服务 `ErrorResponse` 对齐 + `patch_openapi_error_schema`，修复 chat-api 422 缺 RFC 9457 键 type/title/status/instance/error_detail）+ US3 契约（`specs/025-api-contract-hardening/contracts/*.yaml` 三服务 + `tools/contract/{validate,diff,deprecation_check,consumer_refs}.py` + FR-27 路由迁移 `/api/v1` 301/308 + API-Version 头 + FR-16–24 全部契约约束）+ US4 演进（OpenAPI 生成 `--check` + `tools/openapi/probe.py` 三服务实测闭环、`tools/api_check/{path_naming,error_codes_uniqueness,error_code_mapping}.py`、`.github/workflows/quality-gate.yml` `api-contract-hardening` job）；实测 probe `--all` rc=0、`validate.py --all` 三服务通过、pytest 178 passed |
| 026 | performance-scalability（性能与扩展性） | 51 个 P0/P1 缺陷：基线/DB/缓存/前端/扩展性 5 域 | P1 | ✅ | ✅ | ✅ | 🔨 **56/57**（Phase 1–5 全部落地：US1 性能基线（`benchmarks/` 采集 + `services/chat-api/app/infrastructure/observability/perf_baseline.py` + `benchmarks/perf_baselines/baselines.yaml`）；US2 DB（`db_guard` 连接池 + 慢查询 + 熔断 + query_plans）；US3 缓存（HotspotCache 门面 TTL 抖动/事件失效 + `@cache_result` 记忆化 + 命中率监控 + Redis 容量淘汰策略）；US4 前端（web-vitals 原生 PerformanceObserver + 路由懒加载 + vite 构建优化 + CDN 长缓存 + OptimizedImage/虚拟列表 + `frontend_budget_check.sh`）；US5 扩展性（性能配置声明式 `config/performance.yaml` + `contracts/performance.md` + `tools/perf/{observability_verify,llm_resilience_correlate,e2e_regression_check}.py` + quickstart）。**保留项（如实留空不勾）**：T041 水平扩展压测、T054 已于 2026-10-26 凭仓库内证据勾选（001 gatekeeper 经 `LANDING_AUDIT_2026-10-03.md` 判定 hollow、非 QF 复测工具，51 项解除按 `.qualityforge/QUALITYFORGE-REPORT.md` §3 已登记；前置 US1 基线 T006–T013 已完成） |

> 背景：QualityForge standard 深度全量 QA 审计（964 项，pass 298 / blocked 442 / fail 162 / na 59 / verified 3）发现的 P0/P1 代码级缺陷与基础设施缺口。283 个缺陷需建能力（022-026 覆盖），其余 341 个为流程/测试/文档缺口（不需 spec，直接修复）。详见 `.qualityforge/QUALITYFORGE-REPORT.md`。
>
> **⚠️ 落地口径更正（2026-10-24 QA R11）**：022–026 的 **checklist（需求质量门禁）100% 勾选**与 **tasks（实现任务）落地** 是两件事，不能混用。实际状态：022 已完整落地（58/58）；**023 / 024 / 025 / 026 四个特性当时代码未开工（tasks 勾选 0/126、0/119、0/52、0/57，合计 0/354）**。因此「所有特性全流程已就绪」的宣称对这 4 个特性**不成立**，本轮发布范围不含它们；其覆盖的 QualityForge 缺陷仍以「已立项、未实现」登记。阻塞原因须逐特性区分，不可一概写作「待 OQ-1~OQ-8」：023 原有 8 个 open OQ（日志/追踪后端、熔断库、备份存储、告警渠道、SLO、RTO/RPO、跨 AZ 方式），**已于 2026-10-24 全部消解**（决策见其 spec「Clarify 记录」与 tasks「Clarify Decisions」：Loki / Tempo / pybreaker / 本地磁盘+S3 兼容异地 / IM webhook+邮件 / 99.9%·P99<3s·LLM错误率<1% / RTO≤30min·RPO≤15min / 单宿主机演练如实声明）；025 的 OQ-1~OQ-5 早于 2026-10-11 消解完毕；024 无 open OQ（全部决策登记于 spec「Assumptions」节，checklist CHK017 已核对）；026 的预算阈值已于 2026-10-24 定值（spec「Clarify 记录」预算表）。**四者规约层阻塞全部解除，剩余缺口纯属实现排期**——按 tasks.md Phase 1 起可直接开工。
>
> **📌 进度校正（2026-10-26，覆盖 2026-10-24 / 2026-10-25 两份快照）**：前两份快照（2026-10-24「0/126、0/119、0/52、0/57」；2026-10-25「023 124/126、024 18/119、025 7/52、026 5/57」）**均已过时**。2026-10-26 实跑勾选：023 **126/126**（T074/T075 告警 E2E 已于 2026-10-26 用真实 Alertmanager v0.27 闭合，本机可达上限全勾）、024 **112/119**（余 7 项 T081/T085/T086/T106/T107/B004/B005 需真实环境演练或真实 docker daemon）、025 **52/52**、026 **56/57**（仅 T041 需真实水平扩展压测）。四者均已达本机可达上限，剩余缺口全部为环境类、如实留空不勾；其覆盖的 QualityForge 缺陷已按台账回写为「已实现（带保留项）」。上表 tasks 列以本校正为准。

## 四（补）、未独立拆分的后续范围

| 规划清单 | 说明 | 归属 |
|---|---|---|
| 清单 6 工作流级版本化 | GraphSpec 可执行契约 + 灰度/回滚/轨迹回放 | 002 后续 + 010 引擎 |
| 清单 12 Skill 沉淀闭环 | 会话→经验→Skill 自动沉淀 | 已并入 011 |

## 四（补 2）、数据后端迁移（2026-10-13 新增）

| 编号 | 特性 | 说明 | 优先级 | spec | plan | quickstart | tasks |
|---|---|---|---|---|---|---|---|
| 027 | mongo-to-panweidb-migration（MongoDB → PanWeiDB 数据后端迁移） | 数据存储从 MongoDB 迁到 PanWeiDB（openGauss 内核）；**兼容层先行 + 开关式回滚**，612 处调用点零改写 | P1 | ✅ | ✅ | ✅ | ✅（R1 50/50 + R2 T069–T087 + R3 扁平化全部落地） |

> 背景：用户要求把三个服务的数据存储迁移到 PanWeiDB。实测确认**目标库不提供 MongoDB
> 线协议兼容**（那是金仓 KingbaseES 的能力），且 `sql_compatibility=A` 为 `internal`
> 上下文不可改。因此采用「兼容层先行」：集合映射为单表 + JSON 文档列，在数据访问入口
> 之下实现形状与现有驱动一致的门面，业务调用点零修改；用 `MOGO_DATA_BACKEND` 开关切换，
> 默认保持 MongoDB 且行为不变，**回滚不需要改代码**。
>
> **R1（基础设施）已完成并实测通过**：兼容门面在真实 PanWeiDB 上异步 64/64、同步 26/26；
> 搬迁工具「演练 → 搬迁 → 幂等重跑 → 计数校验 → 门面回读」全链路通过；DDL 生成器产出
> 114 表 / 229 个 btree 索引 / **0 GIN**（1.6s）；纯逻辑单测 29 项 + 一致性守卫 14 项；
> 三服务带哈希锁定文件均通过完整性安装。权威方案见 `docs/mongo-to-panweidb-migration-plan.md`。
>
> **R2（接线）已交付（T069–T087）**：聚合编译器（`$match`/`$group`/`$sort`/…）、`bulk_write`、
> 202 处索引语义核对、域级开关、主键字符串化解耦、审计库分离；R3 关系扁平化亦已落地
> （44 表 / 455 列 / 44 索引，见 `r3-flatten/`）。未覆盖能力按 FR-016 显式失败。

## 四（补 3）、会话级轨迹 tab 与 SSO 接收方（2026-10-15 新增）

| 编号 | 特性 | 说明 | 优先级 | spec | plan | quickstart | tasks |
|---|---|---|---|---|---|---|---|
| 028 | user-web-trajectory-tab（user-web 会话级「对话 / 轨迹」双 tab） | 按 `docs/user-web-复用dsh-web会话能力-方案.md` 的**路线 C** 落地：对话与轨迹本同源（同一批 V3 事件的两种投影），把 execution-v3 从「消息内联」提升为会话级「轨迹」tab；**不引入官方 React/cordis 前端、不绕过 chat-api 治理、后端零改动** | P2 | ✅ | ✅ | ✅ | ✅ 10/10 |
| 029 | user-web-sso-receiver（user-web SSO 接收方） | 外部门户免二次登录进入 MOGO 用户工作台；设计闭环于 `docs/MOGO-Web应用集成方案.md` §1.3.2，落地 4 阶段 T001–T020 | P2 | ✅ | ✅ | — | ✅ 20/20（已实现） |

> **028 的实现要点**：tab 状态挂 pane（会话级，多会话不串味），对话/轨迹用 `v-show` 而非 `v-if`
> 切换——避免卸载 ChatWindow 中断 `useChatStream` 流式读取与丢失滚动状态（FR-007）；
> `ChatWindow.vue` 零改动以保对话 tab 零回归。已实现并提交（commit `90fef32`，14 files），
> 自动化验证 8/8 + 三项回归 + `vue-tsc` 0 错误 + `vite build` 通过；**quickstart 的 6 步目视验证待用户在 dev 环境执行**。

## 四（补 4）、本体数据权限（2026-10-16 新增）

| 编号 | 特性 | 说明 | 优先级 | spec | plan | quickstart | tasks |
|---|---|---|---|---|---|---|---|
| 030 | ontology-data-permission（本体数据权限） | 给本体域新增一层**数据范围（data scope）**权限，与既有 RBAC **功能权限正交**：`mesc_ontology_grant` / `mesc_ontology_class_detail` / `mesc_ontology_perm_audit` + 通用 `sys_config`（`enforce` 开关）；运行时按 `(tenant_id, user_id)` 解析可见本体（fail-closed，60s 缓存），检索按 `ontology_id` 过滤；管理端 13 条路由 + 1 内部接口 + admin-web 清单页与用户授权弹窗 | P1 | ✅ | ✅ | — | ✅ 26/26（Phase 0–5 全部落地；T023 HTTP 冒烟 12/12 + mongo parity 8/8、T024 网关已天然放行、T025 `vue-tsc`+`vite build` 双 exit 0、T026 前端代码级复核六点通过；本轮补 checklist 并抓到 enabled 归一化高危 bug；仅 T026 浏览器目视需用户执行） |

> **性质**：**回溯补规格**（代码先于 spec 落地，与 027 同处理方式）——建表入库、运行时解析、
> 管理端 API/前端均已实现，spec/plan/tasks 于本轮补齐并把实现口径固化。
>
> **设计来源**：`docs/ontology-permission-merge-plan.md`（合并方案，5 项决策已拍板）+ `docs/ontology-permission-ddl.sql`
> （原始三表设计稿）+ `docs/MOGO-Web应用集成方案.md` §5.4–§5.9（清单 / 接口 / 内部对接 / 前端设计）。
>
> **关键决策**：① 新建通用 `sys_config`；② 本体层**独立可选**、不强制 `kg:read` 前置；
> ③ `enforce=true` 时缺省固定 **deny**（fail-closed）；④ 后端走**原生 repository**（PG SQL / mongo motor，
> **不经** `pg_compat` 通用壳门面）；⑤ 权限判定键为 **`ontology_id`**，`entity_type` 仅作类型标签。
>
> **双后端**：`deploy/pg/ontology_permission.sql` 与 `deploy/mongo/ontology_permission.js` 字段一一对应，**两侧均已执行入库**。
> 未闭环项（索引写入方暂不填真实 `ontology_id`、`sourceEntity`/`keyField` 占位、类明细列/行过滤未接生效点、
> 跨进程缓存窗口 = 60s TTL、`/internal/*` 网关未放行）见 `specs/030-ontology-data-permission/tasks.md` 末节。
>
> **029 由另一会话建规约**：spec/plan/tasks 三件已就绪，quickstart 与 checklist 未建。
> **2026-10-15 已按 T001–T020 全部实现并验证**：chat-api 新增 `app/core/portal_sso.py`（票据签发/验签/accept-once）+
> `POST /api/auth/portal-ticket`（服务身份 scope `portal.issue_ticket`，按 `end_users._id` 匹配、无 JIT）+
> `POST /api/auth/portal-exchange`（验签 fail-closed + accept-once + 复用 `_create_session`，单租户直建 / 多租户选租户挑战 / 跨租户拒绝）；
> `config.py` 增 `PORTAL_SSO_SECRET`（回退 `END_USER_AUTH_SECRET`）；gatekeeper 注册 `portal.issue_ticket` scope；
> user-web `App.vue` onMounted 读票/清票/换票/失败回落登录弹窗，多租户透传选租户挑战给登录弹窗。
> 门户接入示例见 `docs/samples/portal-sso-integration/`。测试：chat-api `tests/api/test_auth_portal_sso.py` 9 项 +
> user-web `tests/portal-sso-receiver.test.ts` 契约测试通过；api/security/core 回归全绿。

## 四（补 5）、模型供应商发现与多协议接入（2026-10-18 新增）

| 编号 | 特性 | 说明 | 优先级 | spec | plan | quickstart | tasks |
|---|---|---|---|---|---|---|---|
| 031 | model-provider-discover（模型供应商发现与多协议接入） | admin-web「新增模型配置」免手填模型 ID：后端 `POST /api/models/discover` 用已配置 baseUrl+apiKey 直连 provider 真实 API 拉回模型清单，前端「获取列表」弹窗点选回填；discover 由 OpenAI/Azure 扩展到 Anthropic Claude / Google Gemini / Ollama（本地）三类协议（种子 + 前端类型 + 连接测试分发）；首次配置向导 `SetupModelFields` 为三类补专属字段提示 | P1 | ✅ | ✅ | — | ✅（T001–T014 已落地于 commit `6ea16f3`，T015–T018 本轮收尾） |

> **性质**：**回溯补规格**（代码先于 spec 落地，与 027/030 同类）——后端 discover 端点、三协议种子、前端「获取列表」弹窗与首次向导字段提示均已实现，spec/plan/tasks 于本轮补齐并把实现口径固化。
>
> **设计来源**：commit `6ea16f3`（`feat(models): 新增「获取模型列表」并支持 Anthropic/Gemini/Ollama`）。
>
> **关键决策**：① 数据来源 = 代理 provider 真实 API（非 dsh 静态 catalog）；② 完整接入 anthropic/gemini/ollama（种子 + 前端类型/标签 + 连接测试分发）；③ provider_type 五值体系贯穿 seed/setup/连接测试/前端；④ 各协议列表端点与解析口径见 `specs/031-model-provider-discover/spec.md` §已定决策；⑤ 三类新协议无 API Version 概念，向导不强行加版本字段，仅以占位符 + feedback 提示（YAGNI）。
>
> **验证**：admin-api `tests/test_models_discover.py` 11/11 全绿（OpenAI/Azure 解析、Anthropic/Gemini/Ollama 解析、HTTP 错误→502、路由分发、未知类型→422）；前端 `SetupModelFields.vue` 经 `@vue/compiler-sfc` 单文件编译通过。

## 四（补 6）、AgentOS 整合特性（2026-10-23 新增，代码未开工）

> **来源**：《企业 Agent OS 产品落地方案》（2026-10-15）与 mogo 31 个特性的代码级对照评估，产出 `docs/MOGO-AgentOS整合方案.md`（§4 立项清单 13 项）。本批次把该清单落为 SDD 规约。
>
> **性质**：**全新特性，代码尚未开工**——与 027/030/031 的"回溯补规格"（代码先于 spec）相反，本批次 spec/plan/tasks 先于实现，tasks 全部未勾选，按 `/speckit-implement` 正向推进。checklist 与 quickstart 待 `/speckit-checklist` 与实现收敛时按需生成。
>
> **形态边界**：`Decisions/ADR-7-触达层边界-移动端以IM入口覆盖.md`——移动端以 013 多 IM 入口覆盖，不单独做移动端、不做桌面端；门户（037）以 Web 形态交付。

| 编号 | 特性 | 整合方案条目 | 优先级 | spec | plan | tasks | 一句话定位 |
|---|---|---|---|---|---|---|---|
| 032 | eval-gate（评测门禁） | §4.1 | P0 | ✅ | ✅ | ✅ | 黄金测试集 + 发布时点评测 + 硬阈值阻断（幻觉率落地为引用支撑率/拒答正确率/任务成功率三项可计算代理指标），不达标 `publish()` 直接拒绝 |
| 033 | canary-rollout（比例灰度+影子发布） | §4.2 | P0 | ✅ | ✅ | ✅ | 016 canary 从按租户扩展到 1%→10%→50%→100% 比例阶梯 + 影子双跑不污染结果，异常回滚能力保留 |
| 034 | credential-encryption（凭证存储加密） | §4.3 | P0 | ✅ | ✅ | ✅ | 接线 022 已实现但零调用方的 AES-GCM/KMS 到工具凭证存取（写入加密/读取解密/响应掩码）+ 存量明文迁移；Agent 侧服务端注入行为不变 |
| 035 | cost-attribution（成本归集补维） | §4.4 | P1 | ✅ | ✅ | ✅ | 补部门/Agent/空间/业务线四维（TokenUsageRecord 补 agent_id 埋点），六维归集 + 单次调用下钻含单条成本；替换 008 的诚实占位 |
| 036 | trust-rating（可信评级 L1–L4） | §4.5 | P1 | ✅ | ✅ | ✅ | 资产可信度分级（L1 实验→L4 关键双人复核）与权限强绑定；与 001 的 L1–L5×R0–R4 执行矩阵做映射（评级封顶自主级），连续 3 周评测不达标自动降级 |
| 037 | unified-portal（统一门户+自助申领） | §4.6 | P1 | ✅ | ✅ | ✅ | user-web 应用门户：上架目录→自助申领→001 审批流→开通即用；Web 形态（ADR-7），经 029 SSO 与 IM 分发 |
| 038 | egress-sandbox（出站白名单+远程沙箱） | §4.7 | P1 | ✅ | ✅ | ✅ | HTTP 工具/浏览器 Agent 出站域名白名单（默认拒绝+审计+热更新），脚本沙箱网络拒绝语义提升为全出站统一管控；远程沙箱只留契约预留 |
| 039 | visual-orchestration（可视化编排画布） | §4.8 | P2 | ✅ | ✅ | ✅ | 010 引擎的前端画布（vue-flow）：画布↔YAML 双向互转（YAML 为权威定义），复用既有节点/工具选择器 |
| 040 | model-tier-routing（模型分层路由） | §4.9 | P2 | ✅ | ✅ | ✅ | 按任务复杂度（规则法）路由轻量/主力/旗舰三档；补缺失的 `model_routing.yaml`；与 007 降级链分工（路由管选谁划算、降级管谁挂谁顶） |
| 041 | connector-market（连接器市场） | §4.10 | P2 | ✅ | ✅ | ✅ | 预置连接器模板目录（首批 10–20 个，数量不承诺）+"从模板创建"向导；与既有企业工具连接升级而非并行；凭证托管依赖 034 |
| 042 | three-level-quota（三级配额） | §4.11 | P2 | ✅ | ✅ | ✅ | 配额从租户+用户两级扩到团队/项目+租户+用户三级（团队复用部门树、项目新建分组）；三层取最小；001 门禁层零改动获得三层语义 |
| 043 | session-replay（会话回放） | §4.12 | P2 | ✅ | ✅ | ✅ | 028 轨迹从只读陈列升级为可跳转回放：Stage 1 前端纯投影（时间轴+跳轮+下钻，零后端改动）为 MVP；Stage 2 真回放仅预研预留 |
| 044 | multi-agent-modes（轮询择优/辩论对质） | §4.13 | P2 | ✅ | ✅ | ✅ | 010 引擎扩 round_robin（三种可配择优策略）与 debate（轮次上限+三类收敛条件）两种 mode；不改既有四模式语义 |
| 045 | asset-center（资产中心枢纽） | §5 | P1 | ✅ | ✅ | ✅ | 技能/能力资产（MCP/工具/连接器）统一坐标 `(asset_type, asset_key)` 互链：资产中心页 `GET /api/v1/capabilities/list` + 既有 skills/trust-ratings/portal/listings 前端 join；评级/上架/申领/使用四徽标下钻；门户上架下拉选资产；审批页资产视角卡片。2026-10-29 落地，tasks 15/15、checklist 19/19、`test_capability_assets_admin.py` 5 passed |

**跨批次依赖关系**（本批次内部）：032 产出评测数据 → 036 消费（自动降级）；034 凭证加密 → 041 验收依赖；035 单条成本透出 → 043 成本行展示（未落地时降权）；033 扩展 016、035 扩展 008、042 扩展配额体系、044 扩展 010（均含"同步更新被扩展特性 spec/契约"的联合改动点，见各 tasks）。

**落地节奏**（整合方案 §5 三波次）：Wave 1 治理闭环 = 032+033+034；Wave 2 运营与产品完整性 = 035+036+037+038；Wave 3 生态体验 = 039–044 按资源选做。

## 四（补 7）、035/042 口径收敛落地（2026-10-31 新增，代码未开工）

> **来源**：`specs/035-cost-attribution/review-2026-10-30-dimension-source-audit.md`（唯一正本，含 §7.1 项目维度 D0–D8、§7.2 042 整改批次 A/B/C、§8 落地顺序）与 `Decisions/ADR-8-统一项目概念-项目即工作目录.md`。
>
> **性质**：046/047 **代码已落地（2026-11-01）**，048 代码已落地（2026-11-01）。三份 spec/plan/tasks/checklist 四件套于实现后补齐规约（回溯补规格，与 027/030/031 同类处理方式）。与 032–045 的关系：046 是 035「空间」维度改名为"项目"后的**数据供给方**（035 只改文档，未兑现"项目维度有数据"）；047 是 042 的**可发现性整改**（042 引擎已实现，入口不可用）；048 是 035 已取消维度的**代码侧执行**（文档于 2026-10-30 先行改完）。
>
> **B0 归属**：`points_unlimited` 默认值缺陷（chat-api 缺 `, True`）按 2026-10-30 决定并入 042 `tasks.md` **T025**，不单独建 spec。

| 编号 | 特性 | 来源 | 优先级 | spec | plan | tasks | checklist | 一句话定位 |
|---|---|---|---|---|---|---|---|---|
| 046 | project-dimension（项目维度统一） | 035 §7.1 / §8 P0–P2 | P0 | ✅ | ✅ | ✅ | ✅ | 三套同名"项目"收敛为一套（项目 = 工作目录）：`desktop_projects` → `projects`、默认项目 `"default"`、`chat_sessions.project_id`、网关反查绑定、全量回填、侧边栏与驾驶舱切读、042 项目层 `scope_id = project_id`。**代码已落地（2026-11-01）**：T001–T031 全部完成（P0 数据模型 T001–T005 + P1 回填 T019/T020 + P2 切读 T009–T031），含模型网关令牌 `user_id`/`project_id` 注入（T010–T012）、`merge_request_context`（T013）、会话创建写 `project_id`（T015）、归因落账测试（T014）、回填幂等测试（T019）、自动归档（T024/T026/T027）、配额项目层成员来源改 `chat_sessions.project_id`（T030）、驾驶舱项目维度对账（T031）。 |
| 047 | quota-discoverability（配额可发现性） | 035 §7.2 批次 A/B/C | P0 | ✅ | ✅ | ✅ | ✅（26/30 已勾，T013 手工验证、T027-T030 Polish 已补） | 042 引擎已实现但找不到：新增独立菜单「项目管理」、修 `?open=quota` 深链（现指向租户额度）、驾驶舱补「配额异常」卡片、文案「团队」→「部门」（标识符保留）、跨服务一致性测试 + tz 统一 |
| 048 | business-line-removal（业务线维度删除） | 035 §4 / §4.3 | P1 | ✅ | ✅ | ✅ | ✅ | 删除无写方且必然产出单桶假数据的「业务线」维度：后端 `_resolve_business_line` 与 `businessLineAttribution`、前端标签/类型、测试断言；成本段 6 段 → 5 段。**代码已落地（2026-11-01）**：`dashboard.py` 删 `_resolve_business_line` + `_resolve_org_attribution()` 的 business_line 分支 + `_attribution_dimensions()` 的 business_line 段与 `businessLineAttribution` 键；`DashboardPage.vue` 删标签/来源/类型；`test_cost_attribution_035.py` 删业务线断言与用例；7 条原测试 + 新增 T009 验证全绿，`reconciles=True`，全仓 `businessLine`/`is_business_line` 0 命中。 |
| 049 | project-members（项目成员与项目层配额收口） | 用户 2026-11-05 报障 + 追加需求 | P1 | ✅ | ✅ | ✅ | ✅ | 一处读路径修复 + 一个能力扩展：admin「项目管理」读路径从 0 行旧表 `quota_projects` 切到 046 统一后的 `projects`（ADR-8 残留）；项目加 `member_user_ids`（user-web「…」菜单成员弹窗，`end_users` + 部门过滤多选）；可见性改“我的 + 我参与的”（union）；项目层配额口径 = 成员 ∪ 创建者用量合计（双 `quota_policy.py` 同口径）；`quota_projects` 退役（写端点下线、读路径 0 命中）。**代码已落地（2026-11-05）**：spec/plan/tasks/checklist 四件套 + ADR-9；Phase 0–3 完成（读路径切 `projects`、成员字段/端点/弹窗、双服务配额口径、admin 前端清理），前端双端 SFC 4/4 + 双端 `vue-tsc` 0 错误，后端 chat-api 27 / admin-api 51 用例全绿；22:10 按用户拍板「按 spec 严格收口」（删 3 个 410 写路由、清 `tenant_purge` 旧表清理项、补 T019 运行时双服务对拍并做变异自检，D-2 默认项目租户共享兜底登记为**已批准豁免**）；余 T022 全链路手工验证待用户提供 admin 会话与 A/B/C 三账号（服务已 `healthy`，见 `specs/049-project-members/quickstart.md`）。 |

**四包依赖关系**：046 的集合改名（T004）**必须先于** 047 的 A1（新页面读 `projects`）；047 的 A5 依赖 A1；048 与 046 的 T028/T029 **同批提交**（同一函数 `_attribution_dimensions()` 既删业务线段又改空间段；048 已于 2026-11-01 落地，待 046 合并后一并提交）；047 与 048 都动 `DashboardPage.vue` 但改不同位置，可并行；**049 依赖 046 的 `projects` 表（已落地）与 047 的管理页（已落地），049 内部 Phase 1（US3 读路径修复）为最小可交付、先于 Phase 2/3（成员/配额口径）**。

**与既有批次的关系**：046 扩展 035（数据供给）；047 整改 042（可发现性）；048 收尾 035（取消维度）；**049 收口 042/046 的读路径残留并给 `projects` 加成员（ADR-9），扩展 046 D1 纯个人语义为“个人 + 可协作”**。四包均**不改** `scope_type` 枚举、`user_quota_policies` 集合名与 `ANOMALY_STATUSES`。

## 四（补 9）、StaffDeck 整合特性（2026-11-09 新增，代码未开工）

> **来源**：`docs/MOGO-StaffDeck整合方案.md`（唯一正本，2026-11-09 代码级勘察，含 18 项逐项对照 / 四个立项项 / 三波次路线 / 附录 B 证据索引）。对照对象为 StaffDeck（面壁智能等开源的 AGPL-3.0 数字员工平台，同为 DSH 底座）——**许可证不兼容，只借鉴设计，禁止拷贝代码**（各 spec 已声明）。
>
> **性质**：050–053 为 StaffDeck 整合批次（2026-11-09 立项），**2026-11-09 本会话已按三波次实现**（050 27/27、051 29/30、052 22/22、053 29/29 勾选；余为 051 前端手工验收，如实留空）。与 032–044 AgentOS 批次同类正向 SDD：spec/plan/tasks/checklist 四件套先行；checklist 已于 2026-11-10 由 reviewer agent 代审并 100% 勾选（原生达标 5 项，其余经 spec「判定口径补充」R 条回填消解，无留空项）。形态边界遵循 ADR-7（移动端以 013 IM 入口覆盖）；不学 StaffDeck 的 admin/admin 默认口令等反模式。
>
> **关键代码事实（决定设计走向）**：① 010 引擎 `run_graph` 无 checkpoint/resume（`engine.py:84`）→ 050 需新建 `orchestration_runs` 运行持久化（也是 052 的地基）；② `position_roles` 已有能力白名单形态但属人类 RBAC → 051 新建 `employees` 实体而非改造岗位角色；③ `VALID_MODES` 现为六模式（044 后），052 扩为第 7 模式 `team`。
>
> **编号说明**：统计段对 049 的「详见四（补 8）」指向未单建节——049 行实际位于「四（补 7）」表内；本节沿用「补 9」编号避免与该既有引用冲突。

| 编号 | 特性 | 来源 | 优先级 | spec | plan | tasks | checklist | 一句话定位 |
|---|---|---|---|---|---|---|---|---|
| 050 | sop-human-handoff（SOP 转人工节点） | 整合方案 §4.1 | P0 | ✅ | ✅ | ✅ **27/27**（2026-11-09 落地） | ✅（16 项，2026-11-10 代审 16/16 + spec 回填） | SOP 流程中的 `human_approval` 节点：复用 `ApprovalRuntime` 签发/消费审批，新建 `orchestration_runs` 运行快照实现挂起-恢复（引擎首个持久化断点），超时 fail-closed、拒绝可走 `on_reject` 分支，039 画布补节点类型。**审批是节点类型不是文档模式，`VALID_MODES` 不扩展。** |
| 051 | digital-employee-profile（数字员工档案） | 整合方案 §4.2 | P0（B1）/ P1（B2） | ✅ | ✅ | ✅ **29/30**（B1 + B2 全链路 + E2E 行为验证；前端手工验收待人工） | ✅（17 项，2026-11-10 代审 17/17 + spec 回填） | 新建 `employees` 实体（能力白名单 + 知识库 + 记忆 scope + 模型配置 + Harness profile + SOP 绑定），员工 = 可对话的组织角色而非岗位 RBAC。B1：实体/会话绑定/门户；B2：IM 意图路由（`im_gateway/routing.py` 确定性关键词 + 默认兜底）、员工级 API Key（`api_keys.py` 哈希存储 + `X-API-Key` 认证 + `/employees/me/by-key`）、员工模板（依赖 053，已接线）、E2E 行为验证（`_bind_session_employee` 集成测试）。 |
| 052 | team-collaboration-mode（团队协作模式） | 整合方案 §4.3 | P1 | ✅ | ✅ | ✅ **22/22**（T015 首期软依赖、真挂起 P2 预留） | ✅（17 项，2026-11-10 代审 17/17 + spec 回填） | `VALID_MODES` 第 7 模式 `team`：leader 拆解/分派（竞标后置）+ 运行级黑板（作者/版本）+ 验收循环（accept/rework，默认 3 轮上限 1..5 钳制，到限 fail-closed）+ 经 050 决策口径内联接管（`_should_take_over` + `approval_hook` 决策覆盖 + `team.takeover` 审计；**非** `awaiting_approval` 跨进程挂起，真挂起按「接管 = 050 跨模式挂起，P2 预留」留二期，生产 `approval_hook` 首期未注入）。**硬依赖 050**（team 状态以自由形态嵌 050 `orchestration_runs` 快照，无新集合）。 |
| 053 | plaza-template-distribution（广场模板分发） | 整合方案 §4.4 | P1 | ✅ | ✅ | ✅ **29/29**（US1+US2+US3 P2 全落地） | ✅（17 项，2026-11-10 代审 17/17 + spec 回填） | `asset_type` 扩 `employee_template` / `sop_template`：克隆 = 深拷贝 + `template_ref`（副本可改原件只读），升级 = 手动整份替换 + 旧快照，SOP 发布过 032 评测门禁，凭证永不随模板复制（034 口径）。US3：副本使用须申领审批 fail-closed（`require_asset_use`）+ 调试标记 + 克隆数进 016。 |

**四包依赖关系**：**050 → 052 为硬依赖**（052 的黑板/验收状态嵌在 050 的 `orchestration_runs` 快照里，050 未落地 052 无法开工）；051 B1 独立可并行；053 的 SOP 模板独立、员工模板依赖 051 B1；051 B2 的员工模板消费依赖 053。**推荐节奏**（整合方案三波次）：Wave 1 = 050 + 051 B1（并行）；Wave 2 = 052 + 053 SOP 模板；Wave 3 = 051 B2 + 053 员工模板。

**与既有批次的关系**：050/052 扩展 010 引擎与 044 模式体系（050 加节点类型、052 加第 7 模式，039 画布同步）；051 与 006（岗位 RBAC）/019（Harness profile）/017（记忆 scope）为消费关系而非改造；053 扩展 045 资产中心与 016/018 市场，发布门禁走 032、凭证边界走 034。四包均**不改**既有六模式语义（044 FR-010 延续）。

## 五、规约完成度统计

- spec.md：001–048 全部完成（48 份；028 会话级轨迹双 tab、029 user-web SSO 接收方，均于 2026-10-15 新增；030 本体数据权限 / 031 模型供应商发现为回溯补规格；**032–044 为 2026-10-23 AgentOS 整合批次，13 份全新特性规约，详见「四（补 6）」；045 资产中心于 2026-10-29 立项落地；046–048（项目维度统一 / 配额可发现性 / 业务线维度删除）为 2026-10-31 口径收敛批次，代码于 2026-11-01 落地，详见「四（补 7）」**）；**050–053 为 2026-11-09 StaffDeck 整合批次（4 份全新特性规约，2026-11-09 已按三波次实现，详见「四（补 9）」），累计 54 份（含 049、055）**
- plan.md：001–048 全部完成（48 份；020 为技术化实施计划，022–026 为质量加固特性计划，027 为数据后端迁移计划，028 为路线 C 前端视图方案，029 为 SSO 接收方实施计划，032–044 为 AgentOS 整合实施计划，045 为资产中心方案 A+B，046–048 为口径收敛批次实施计划，其余技术契约齐全）；**050–053 为 StaffDeck 整合实施计划（4 份，2026-11-09，详见「四（补 9）」），累计 54 份（含 049、055）**
- checklist（需求质量门禁，`/speckit-checklist`）：001–028 完成（28 份，029 未建〔**2026-11-11 复核：029 的 `checklists/requirements.md` 已建成且 18/18 全勾；本句属 2026-10-24 历史快照口径，以磁盘实测为准**〕，`checklists/requirements.md`，reviewer-owned）；**001/002/007–021 共 17 份已 agent 代审 + FR 回填 + 跨特性双向声明，100% 勾选达标**；003–006（既有回溯）保留原始未勾状态；**022–026（质量加固）已于 2026-10-12 补齐 checklist（17–18 项/份，含 FR 覆盖、跨特性一致性、Non-Goals 边界与 OQ 待定标记），100% 勾选达标**；**027（数据后端迁移）于 2026-10-13 新建（35 项，勾选 33/35；未勾 2 项 CHK015 性能预算 / CHK027 索引验收口径 仍未定值——R2 已交付、R3 已按表结构扁平化推进，未依赖该阈值、未阻塞落地）**；**032–044（AgentOS 整合批次）13 份已于 2026-10-24 全部建成**（`specs/032-eval-gate/checklists/` … `specs/044-multi-agent-modes/checklists/`，各 15–16 项，四分类：完整性 / 清晰度 / 一致性 / 边界与歧义），**全部 100% 勾选达标**，13 份均经 agent 代审 + spec「判定口径补充」回填（R-1…R-16 逐条对应 CHK）。回填同时完成三件事：① 修正 spec 与代码不一致的路径/枚举（如 042 的 `ANOMALY_STATUSES` 不可复用、044 的 `contracts/` 目录不存在、043 的 `V3ItemKind` 无成本字段）；② 把先前含糊的口径定成可执行常量与判定序（阈值、归一化、钳制、fail-closed 分支）；③ 显式登记「首期未实现 + 建议落点」（040–044 原为代码零开工，已在本会话实现并勾选 tasks，各 spec 标注保留）；**045（资产中心）已于 2026-10-29 建成（19 项，四分类），100% 勾选达标**（spec/plan/tasks/quickstart 齐备，tasks 15/15，后端单测 `test_capability_assets_admin.py` 5 passed；032–048 批次 17 份 quickstart 已于 2026-11-04 补齐，与 001–030 同构）；**050–053（StaffDeck 整合批次）4 份于 2026-11-09 建成**（各 16–17 项，合计 67 项，四分类同 AgentOS 批次），**2026-11-10 已由 4 位 reviewer agent 代审完毕并 100% 勾选达标**（050 16/16、051 17/17、052 17/17、053 17/17；原生达标共 5 项，其余由 spec「判定口径补充」R 条回填消解，无留空项）。各 checklist 末尾均附「评审结论（2026-11-10 勾选，agent 代审 + spec 回填）」节，逐条给 CHK→R 映射与判定依据；生成规则 reviewer-owned、不预勾，勾选动作由 reviewer 完成，`/speckit-implement` 只读标记不改
- tasks（可执行任务，`/speckit-tasks`）：**001–048 共 48 份全部建齐**（001/002/007–021 的 17 份含 clarify 决策 + checklist 门禁 + 故事分阶段 + 并行点 + MVP，354 项全部勾选；**2026-10-11 新增 003/004/005/006 的 4 份**，共 141 项任务；**2026-10-11 新增 022–026 的 5 份**，共 357 项任务，覆盖 QualityForge 审计 283 个 P0/P1 缺陷；**2026-10-13 新增 027 的 1 份**，共 75 项任务（R1 T001–T068、R2 T069–T087），已全部勾选并附实测证据）；**2026-10-15 新增 028/029 的 2 份**——028 共 10 项已全部勾选（实现与自动化验证均完成，quickstart 的 6 步目视验证待用户在 dev 环境执行）；029 共 20 项已全部勾选并实现（2026-10-15，端点 + 换票 + 门户示例 + 前端换票闭环，api/security/core 回归全绿）；**2026-10-23 新增 032–044 的 13 份**（共 358 项）——**2026-10-24 状态：勾选 337/358**。已落地：032（22/22 完整实现）、033（22/22）、034（33/37，保留 T033–T036 需 staging 备份演练；本地段 `tests/test_drill_credential_scripts.py` 1 passed 已覆盖 dry-run→apply→verify→二次幂等→轮换，SC-005 段闭环）、035（31/35，T017 缺口于 2026-10-24 闭环：`adapters.py` 两处 `set_request_context` 改 `merge_request_context` + 新增 `tests/enterprise_capabilities/runtime/test_035_capability_attribution_scope.py` 7 passed（合并 11 passed）回归 971 passed；T031–T034 待 staging）、036（28/29，T018 skills 侧 FR-014 于 2026-10-24 端到端落地：新增 `services/admin-api/app/services/trust_rating/skill_visibility.py` + `routes/skills.py` 接线 + `tests/test_skill_l1_visibility.py` 8 用例合计 59 passed；T019/T020/T021/T027 前端于 2026-10-24 交付：`src/api/trustRatings.ts` + `src/views/trust-ratings/TrustRatingPage.vue` + `SkillsPage.vue` L1–L4 徽标 + `/trust-ratings` 路由 + `DashboardPage.vue` 评级分布卡，vue-tsc exit 0 + SFC 编译 3 个 .vue ok；仅 T028 E2E 待 staging）、037（29/31）、038（32/34，T022/T023/T024 前端于 2026-10-24 交付：`src/api/egress.ts` + `src/views/egress/{EgressAllowlistPage,EgressLogsPage}.vue` + `/egress/allowlist` `/egress/logs` 两条路由，vue-tsc exit 0 + SFC 编译 ok；T025 工具编辑页入口与 T032 E2E 待人工）、039（30/33，T028/T029 前端单测未落地、T030 E2E）；**2026-10-24 追加落地：040（18/20，T017 需真实模型凭证、T019 需与 008 联调）、043（20/21，T019 手工浏览器验收待人工）、041（23/24，T019 mock 全链路 E2E 于 2026-10-24 闭环：`services/chat-api/tests/test_connector_market_mock_e2e.py` 4 passed（本地 `ThreadingHTTPServer` + gitlab-api 模板）；T022 034 联调验收待 staging）、042（23/24，T023 手工联调待人工；SFC 编译与 vue-tsc 已过）、**044（26/26，多 Agent 轮询择优 / 辩论对质：010 引擎扩 `round_robin`/`debate` 两模式 + 新建 `contracts/orchestration.md` 六模式契约，新增测试 45 passed + 010 全量回归 136 + `competitor_deep_dive` 迁移后 28）**各份 tasks.md 末尾均附「验收状态（2026-10-24 交接复核）」节记录证据与未勾原因；**045（资产中心）2026-10-29 建成（15 项，全部勾选）**——`GET /api/v1/capabilities/list` 接口 + 前端 `AssetsPage.vue`/`useAssetCatalog.ts`/`adminAsset.ts` 互链 + 门户上架下拉 + 审批页资产视角卡片，后端单测 5 passed；**2026-10-31 新增 046/047/048 三份（046 34/34、047 30/30、048 13/13，代码 2026-11-01 落地，仅 046 T035 / 047 T031 两项手工浏览器验收待人工）**——项目维度统一 / 配额可发现性 / 业务线维度删除，详见「四（补 7）」；**2026-11-05 新增 049 一份（23/25，余 T022 全链路手工验证需 admin 会话与 A/B/C 三账号、T025 成员变更审计回归用例）**——项目成员与项目层配额收口，详见「四（补 8）」；**2026-11-09 新增 050–053 四份（050 27 项 / 051 30 项 / 052 22 项 / 053 29 项，共 108 项）**——StaffDeck 整合批次，详见「四（补 9）」；**2026-11-09 状态：050 27/27、051 19/30（B1 后端+前端+文档接线）、052 21/22（核心+文档接线）、053 26/29（US1+US2+文档接线）**，余为 051 B2 / 053 US3 P2 / Phase 3 收尾（checklist 待代审、E2E/手工验收待人工），如实留空；**2026-11-10 状态**：四份 checklist 代审 100% 达标（不计入 tasks 勾选），050 27/27、051 29/30（T028 浏览器目视仅部分完成、保持 `[ ]`）、052 22/22、053 29/29；T028 自动化证据补强 + 管理页/门户目视证实、会话选择仅证实下拉可展开与空态（4 张截图，控制台无 error、xhr/fetch 无 404），「下拉选中具体员工发起会话」从未验证且 200 依赖自签合成登录态（会话已删、当前不可复现），按 reviewer 修正保持 `[ ]` 留人工；**累计 54 份 tasks.md**
- **AgentOS 整合批次落地进度（2026-10-24 复核）**：Wave 1–2（032–038）+ Wave 3 首个特性（039）代码已由并行会话落地，本会话按 SDD 门禁逐份复核（生成 checklist → spec 回填 → 跑测试 → 勾 tasks）；**040（档位路由）、043（会话回放 Stage 1）、041（连接器市场）、042（三级配额）、044（多 Agent 模式）均已由本会话实现并勾选**，032–044 全部落地，无代码零开工特性。测试证据：032 `test_eval_gate.py` 31 项 + `test_skill_lifecycle.py` 3 项；033 `test_canary_ratio.py` 19 + `test_canary_shadow.py` 9；034 70 + 13（含新增 `test_migrate_tool_credentials.py` 9、`test_rotate_tool_credentials.py` 4）；035 8 + 4 + dashboard 回归 42；036 `test_trust_rating.py` 25；037 25 + 27；038 15 + 28 + 脚本沙箱回归 2；039 11；044 45 + 010 引擎全量 136（含 `competitor_deep_dive` 迁移回归 28）；040 19 + `tests/llm` 全量 90；041 `test_connector_market.py` 14 + 工具/资产回归 66；043 `tests/session-replay.test.ts` + `trajectory-view-tabs` 8；042 `test_quota_three_level.py` 13 + 13（双服务同内容）、`test_quota_projects.py` 9、`test_quota_unlimited.py` 9 与 `test_governance_us4_us5.py` 13 回归。全部前端改动经 `@vue/compiler-sfc` 3.4.38 编译校验通过（admin-web/user-web `vue-tsc --noEmit` 均 0 错误）。
- **2026-10-24 staging/E2E 缺口修复（第二批次）**：035 T017、036 FR-014 端到端 + 前端、038 前端、041 mock E2E、034 本地演练均已闭环（证据见各 tasks「验收状态」节与逐条勾选备注）；**仍待人工/staging 的 21 项**：034 T033–T036（staging 备份回滚/SC-002 注入回放/多副本轮换）、035 T031–T034、036 T028、038 T025/T032、039 T028–T030、040 T017/T019、041 T022、042 T023、043 T019。所有 staging 项均附执行步骤与判定口径（`docs/credential-key-rotation-drill.md` 与各 spec「判定口径补充」），未伪造勾选。

> **2026-11-04 全量复核（standard 深度 QA 审计）**：上段「2026-10-24 状态」快照中 032–044 的 tasks 部分计数（034 33/37、035 31/35、036 28/29、037 29/31、038 32/34、039 30/33、040 18/20、041 23/24、042 23/24、043 20/21）**现已全部闭合为 100%**（逐特性核验见 `deliverables/QA-AUDIT-STANDARD-2026-11-04.md` §2.1）。截至 2026-11-04：001–048 中仅 **024 deployment-hardening** 保留 7 项环境类演练未勾（112/119），其余 47 份 tasks.md 均为 100% 勾选。
> **2026-11-06 复核增补**：新增 **049 project-members**（含 spec/plan/tasks/quickstart/checklist 五件套）；017 进入 **B0–B7 阶段**（B0/B1 推送、B2–B4 代码落地未发布、B5 部分、B6 产出脚本/手册、B7 文档同步）。截至 2026-11-06：49 份 tasks.md 中 **46 份 100% 勾选**，仅 **3 份部分**——024（112/119，7 项环境类演练待远端/预发）、017（41/46，T031 E2E / T042 切换 / T043 049 回归 / T045 清理 / T046 部分待维护窗口）、049（23/25，T022 全链路手工验证 + T025 成员变更审计回归待执行）。详见 `deliverables/QA-AUDIT-STANDARD-2026-11-06.md`。
- 实现进度（`/speckit-implement`，2026-07-08）：**19 个特性全部已有实现核心/ MVP**——P0（001/007/008）完整 MVP；P1（002/009/010/011）核心；P2（012–019）核心全部落地。合计 **313 项新测试通过**（admin-api 89 + chat-api 224）。
  > ⚠️ **该结论已被推翻（2026-10-03 重检）**：它把"有纯逻辑代码 + 单测通过"当成了"已落地"。按今天的标准
  > （生产调用方 / 消费方 / 真实数据源 / 端到端可证伪）重检 20 个特性，结果为
  > **`landed` 0 · `partial` 10 · `hollow` 9**（高危缺口 ≥60 条）。详见
  > [`LANDING_AUDIT_2026-10-03.md`](./LANDING_AUDIT_2026-10-03.md)。**本文其余"✅/已实现"表述仅指文档层面完成度，不代表功能落地。**
- clarify（OQ 消解）：**001/002/007–020 + 022 + 023 + 025 + 026 共 20 份已消解**（003–006 既有回溯未做 clarify；021 未单列 clarify 节，其决策随 017 优化轮一并确定；024 无 open OQ，决策登记于 spec「Assumptions」节视同消解；025 的 OQ-1~OQ-5 早于 2026-10-11 消解但未计入，本行一并补记）。消解记录位置：001/002/007–011 在 spec 的 "Clarify 记录" 节；012–019 在 plan 的 "Open Questions（已 clarify 消解）" 节；020 与 022 在 tasks.md 的 "Clarify Decisions" 节（19 项 / 5 项）。关键消解：
  - 001：审批复用 `approval_runtime`（poll，5min 超时）；配额用 MongoDB（不引入 Redis）；PII 全局默认 + 租户可覆盖
  - 007：tenacity 既有依赖；退避 1.5s/30s/±10%/3 次；事件落 token_usage_logs
  - 008：人工介入率=审批挂起数；P50/P95 取 token_usage_logs.duration_ms；瓶颈 top-N；DashboardPage 加标签页
  - 002：独立 session_snapshots；熵 ≥3.5 + 前缀双判定；不引入 Redis；share 联动 006
  - 009：超时 5s；fail_closed 不可放行；首期仅 PreToolUse
  - 010：JSON 条件对象（禁代码 AST）；并行度 4；节点/模型重试分层；双轨迁移
  - 011：Jaccard ≥0.7 + 样本 ≥5 建 MR；14 天低采纳淘汰；与 016 共用标记位
  - 012–019：各自口径/阈值/依赖顺序已定（019 薄模式保留身份/RBAC/脱敏/审计/红线，可省审批/配额）
  - 022（2026-10-12）：OQ-1 MFA 通知通道未接入时降级为审计事件；OQ-2 首期 KMS 用环境变量 + 集成接口预留、Vault 可选；OQ-3 TLS 终结在反向代理层、应用层经 `SECURE_PROXY_SSL_HEADER` 感知；OQ-4 服务间首期内网隔离 + 独立凭证、mTLS 可选；OQ-5 CORS 白名单由环境变量配置且默认空
  - 023（2026-10-24）：OQ-1 日志后端 Loki；OQ-2 追踪后端 Tempo（OTel Collector）；OQ-3 熔断库 pybreaker；OQ-4 备份 = 本地磁盘主存 + S3 兼容对象存储异地（复用 oss2，未配桶降级本地-only 且 /ready 可见）；OQ-5 告警渠道 = IM webhook（复用 013）+ 邮件，电话/语音 Non-Goal；OQ-6 SLO = 99.9% / P99<3s / LLM 错误率<1%；OQ-7 RTO≤30min / RPO≤15min（MongoDB 数据面口径）；OQ-8 跨 AZ = 单宿主机演练 + 备份重建（验收文案如实标注非真实跨 AZ）
  - 026（2026-10-24）：性能预算阈值全部定值（对话 P95≤2s / 解析≤5s / 鉴权≤500ms / 包体积 500KB·300KB gzip / LCP≤2.5s / 命中率≥80% / 慢查询 100ms / maxTimeMS 5s / 连接池 100·10·30s·≤80% / 1000rps·队列 1000 / DB 熔断错误率>50% / P95 回归 +20% 判线）——默认可配，见 spec「Clarify 记录」预算表

## 五（补）、checklist 暴露的缺陷修正记录（✅ 已修，2026-07-08）

以下 5 处由 checklist 审阅暴露的 spec 缺陷已在对应 spec 正文订正，reviewer 审阅时直接确认即可：

| 缺陷 | 所在 | 类型 | 修正结果 |
|---|---|---|---|
| 001 Non-Goals 特性编号引用错配 | 001 CHK011 | 一致性 | ✅ 已订正：LLM 韧性→007、DAG→010、自进化→011、会话版本化→002（原误写 002/003/004/005） |
| 016 FR-4 与 clarify 矛盾 | 016 CHK006 | 一致性 | ✅ 已对齐：FR-4 + US3 改为"首期按租户，按比例/用户为后续扩展" |
| 017 FR-3 vs FR-5 默认策略矛盾 | 017 CHK002 | 一致性 | ✅ 已统一：按"单/多人会话"区分默认范围（单人 personal、多人 workspace） |
| 008 成本预测 N 值未定 | 008 CHK013 | 完整性 | ✅ 已补：N = 4 期（可配置 forecast_periods）+ clarify OQ-5 |
| 010 表达式语法错误策略未定 | 010 CHK013 | 完整性 | ✅ 已补：默认 fail_closed（跳过 + 审计）+ clarify OQ-5 + FR-4 同步 |

## 五（补2）、P0/P1/P2 checklist 评审 + FR 回填记录（2026-07-08，已全部消解）

按 `/speckit-checklist` 语义 agent 代审 15 份 checklist（001/002/007–019），**只勾真正达标项**；同时把 clarify 已定但未进 FR 正文的值 + 可消解的边界缺口回填进 spec。随后在"跨特性双向声明轮"中，把 15 份剩余未勾项（跨特性两两关系 + 特性自身缺口）全部消解，**该轮 15 份 checklist 全部 100% 勾选**（003–006 为既有回溯、未代审，保留原状态；截至 2026-10-06 已增至 17 份，见 §五）。

| 特性 | 勾选/总数 | 回填消解项 | 后续消解项（跨特性双向声明轮已清） |
|---|---|---|---|
| 001 gatekeeper | 15/18 | 逐层返回码、级联/回落、配额 MongoDB+UTC、预设组结构、审批 5min+poll+超时动作、R4 全能力管理员、删层重排、脱敏请求体前 | 25格矩阵完整表、001↔006、001↔019 |
| 007 llm-resilience | 10/15 | 主/备显式声明、降档=文本档位、agent_id 维度、成本单价取 008 MODEL_PRICES、退避默认值、仅文本模型、全故障聚合错误 | 降级原因枚举、007↔001 配额、重试取消、切换计量归属 |
| 008 ops-dashboard | 13/15 | 分摊字段、去重键、异常枚举、周期、人工介入率、P50/P95 源、top-5、容差、007 failover 字段对齐、最小角色、分维空态、时区、下钻脱敏 | 契约边界、月同比 |
| 002 session-versioning | 12/16 | 触发条件、resume seq、share 权限转移、co-presence 冲突、秘密判定、独立快照集合、审计字段、解引用定义、附件边界、乐观锁、share 失效、离线贡献 | 002↔001/009/011/005 |
| 009 hooks-interception | 11/16 | 三规则语义、作用域叠加、fail_closed、首期 PreToolUse、超时 5s、observe 强度、解析失败三类、拒绝语义、生效时机、求值顺序 | 五事件数据、009↔001/002/019、延迟预算 |
| 010 dag-orchestration | 13/16 | 节点数据传递、并发度 4、跳过追溯、阻塞闭包、JSON 条件、版本字段、环路径格式、双轨、语法错误、原子语义、supervisor 传播 | 010↔007/009/002、跨层并发预算 |
| 011 dream-cycle | 12/16 | 片段字段、双指标算法、测试定义、采纳率口径、friction 默认、MR 不直接合入、草稿vsMR、恢复路径、堆积上限、去重、生效范围、生成侧门槛 | 011↔004/002/016/010 |
| 012 a2a-agent-gateway | 13/15 | AgentCard 字段+skills[]、JSON-RPC 方法名、agent 路由、客户端超时/failover、Dify 优先、卡刷新触发、同租户边界、双向审计、错误码映射、幂等、鉴权枚举、外部注册 | 012↔001/018 |
| 013 multi-im-entry | 13/15 | 映射粒度 1:1、长响应分段、能力=Web 全量、租户级开关、首期飞书、纯文本+基础卡片、会话映射、@bot 主体、撤回不回改、离线降级、凭据注入、1会话1IM | 013↔001/002 |
| 014 business-semantic-index | 12/15 | 4 类实体+schema 可配、定时拉取、联查键、来源三级、首期 CRM、PII 走 001、数据源不可用、全量首刷、对齐失败降级、副本延迟标注 | 014↔005/015/001 |
| 015 knowledge-graph-layer | 12/15 | 实体/关系类型、跳语义+3 跳、三类约束、查询入口、迁移阈值、断裂判定、合并策略、防环、低置信门槛、矛盾不阻断、融合裁决 | 015↔005/014/001 |
| 016 skill-market-hardening | 13/15 | 异常口径、打分权重、租户灰度、降权行为、效果分口径、20% 回滚、0.4/7天、数据源、最小样本、稳定版本、恢复路径、多版本归集 | 016↔004/011 |
| 017 three-scope-memory | 12/15 | Workspace 粒度、默认策略、授权角色、衰减口径、三级可见性、001 治理点、离职处置、超限拒绝（旧版口径，v3 已改为超长优先分层）、多范围各存、检索过滤；**2026-10-05 优化轮新增密度轴（L0/L1/L2）+ 渐进检索 + mogo:// 地址 + 会话分层沉淀**，接 021 | 017↔005/002/006/021 |
| 018 capability-asset-registration | 12/15 | 契约四段、扫描目标、3 态、owner 粒度、自动/人工分工、多对多 skill_refs、下线审批、旧版可查、去重键、视图下钻、owner 转移 | 018↔004/012/001 |
| 019 harness-elastic-config | 13/15 | 厚/薄层集合、三维 profile、审计粒度+超时、默认厚、优先级、可省/不可省、最小审计四元组、工具调用级生效、配置权、过渡挂载、中途切换 | 019↔001/009 |
| 021 unified-context-address | 4/4 | 统一 mogo:// 寻址、TierAdapter 接口、委托式可见性、统一检索轨迹；首期 tenant=memory（接 017），resource/skill/session 按节奏接入 | 021↔017/002/009/005/014/015/004/018 |

**共性结论（2026-07-08 跨特性双向声明轮后）**：15 份 checklist 的剩余未勾项已全部消解——①**跨特性两两关系**在各 spec 的"跨特性关系（被依赖方视角）"节**双向声明**（001↔006/009/012/013/018/019，002↔009/011/013/017/005，004↔011/016/018，005↔014/015/017，006↔017/019，007↔010/001/008，009↔010/019，012↔018，014↔015）；②**特性自身缺口**回填 FR（001 的 25 格矩阵表、007 降级原因/取消/计量归属、009 五事件数据/延迟预算、010 跨层并发预算、008 契约边界）。**现 15 份 checklist 全部 100% 勾选，19 份 spec 契约无冲突，达 implement 就绪。**（2026-10-06 口径：21 份 spec / 17 份 checklist 全部完成，见 §五）

## 六、SDD 路径

- 既有回溯（003/004/005/006）：spec ✅ → plan ✅ → checklist ✅ → **tasks ✅（2026-10-11 补齐）**→ 后续按需补 `/speckit-analyze` + `/speckit-implement`
- 缺口 P0（001/007/008）：spec ✅ → plan ✅ → clarify ✅ → checklist ✅ → tasks ✅（本轮补齐）→ analyze → implement → converge
- 缺口 P1（002/009/010/011）：spec ✅ → plan ✅ → clarify ✅ → checklist ✅（已评审勾选）→ tasks ✅（本轮补齐）→ analyze → implement → converge
- P2 后置（012–019、021）：spec ✅ → plan ✅ → clarify ✅（012–019 记录在 plan 的 "Open Questions" 节）→ checklist ✅（已评审勾选）→ tasks ✅（17 份之一，本轮补齐）→ 按路线图节奏 implement
- 平台化 / 优化轮新增（020、021）：spec ✅ → plan ✅ → clarify ✅（020 记录在 tasks.md 的 "Clarify Decisions" 节）→ checklist ✅ → tasks ✅ → 已按 SDD 落地（020 平台化多租户、021 统一上下文地址空间）
- 质量加固（022–026，2026-10-11 新增）：spec ✅ → plan ✅ → tasks ✅ → quickstart ✅ → **checklist ✅（2026-10-12 补齐）** → 按审计修复波次 implement（Wave 1: 022 安全 → Wave 2: 023 可观测性 → Wave 3: 024 部署 → Wave 4: 025 API → Wave 5: 026 性能）
- 数据后端迁移（027，2026-10-13 新增）：**既有工作回溯补规格**——R1 代码先于 spec 落地（与 003–006 的处理方式一致）→ spec ✅ → plan ✅ → tasks ✅（75 项全部勾选）→ quickstart ✅ → checklist ✅（33/35；未勾 CHK015/CHK027 仍未定值）→ **R1 基础设施 / R2 兼容层接线 / R3 关系扁平化均已落地（R3 见 `r3-flatten/`）**
- AgentOS 整合（032–044，2026-10-23 新增）：**全新特性、代码未开工**——spec ✅ → plan ✅ → tasks ✅（全部未勾选）→ checklist 13 份已于 2026-10-24 全部建成且 100% 勾选 → 按整合方案 §5 三波次 implement（032–044 已全部落地）（Wave 1 治理闭环：032/033/034 → Wave 2 运营完整性：035–038 → Wave 3 生态体验：039–044）
- StaffDeck 整合（050–053，2026-11-09 新增）：**2026-11-09 已按三波次实现**（050 27/27、051 29/30、052 22/22、053 29/29 勾选）。**2026-11-10 收尾**：四份 checklist 经 reviewer agent 代审 100% 勾选达标并回填 spec「判定口径补充」；051 B2（IM 意图路由 / 员工 API Key / 员工模板上架）与 053 US3 P2（副本申领 037/001 / 调试工作区 / 质量信号进 016）代码及端点契约复核完成；051 T028 自动化证据补齐（SFC 10/10、双端 `vue-tsc` 0 错误、前端首页 200、6 个端点 401 鉴权生效），浏览器目视验收于 2026-11-10 用 `agent-browser` 部分完成（管理页/门户已证实、会话选择仅证实下拉可展开与空态，4 张截图，控制台无 error、xhr/fetch 无 404）；200 依赖自签合成登录态，收口后会话已删、:3200 已停，当前不可复现；用户实测 `:3000/admin-api/api/v1/employees` 404 已定位为 3000 nginx 静态服务无 `/admin-api` 反代（vite dev server 漂移至 3001），启动 8100 后 3001 与直连均 401、3000 仍 404，属部署层非代码缺陷，T028 经 reviewer 澄清修正后保持 `[ ]` 不虚勾（曾据初报勾 `[x]`，已回退）；052 T015 按用户口径「接管 = 050 跨模式挂起，P2 预留」由 R-4 定清首期软依赖边界。**2026-11-10 文档一致性收口**：050 代审附注登记的 4 项契约/实现不一致已核实为「文档写错、实现无缺陷」并全部消解（仅改文档、不动运行时代码）；010 契约标题/模式注释同步为七模式、§6 状态机与票据条款改为与 R-6/R-2 一致；052 OQ-1「或有限重试」与 053 待澄清节 OQ-1~OQ-4 的口径残留已同步。**下一步**：T028 人工目视验收（需真实登录态复现 200 + 验证「下拉选中具体员工发起会话」）、050 `_validate_050_shapes` 的 mode 限制校验（R-9 实现侧未兑现，现由 `RunDriver.start` fail-closed 兜底）、053 散落 clarify 残留收敛（含 FR-009，本轮未动）、052 真跨模式挂起二期实现、3000 nginx `/admin-api` 反代（部署层、另一会话在途）。
  - **022 Wave 1 进度（2026-10-12）**：Phase 0「安全基座」T001–T006 ✅（双服务 `app/security/` 6 模块 + 各 176 单测）；Phase 1「口令与 MFA 强制策略」T007–T013 ✅（新增 `mfa_gate.py` 组合层；admin-api 登录闸门 + `/mfa/verify` 限流与 90s 防重放 + 绑定/解绑审计与通知降级；双服务口令策略统一 ≥12 位、4 类取 3；+32 条 gate 集成测试；admin-api 641 passed / chat-api 2474 passed）；Phase 2「令牌与会话生命周期」T014–T022 ✅（双服务 access token TTL 收敛到 1h + 启动告警；`/auth/refresh` 打通一次性轮换 + 重放吊销整个 family；新增共享 `session_timeout.py` 落地空闲 30min / 绝对 24h 判定（admin-api 经 `deps` 覆盖全部需认证路由、chat-api 经 `resolve_session_user`）；新增 `service_token.py` + `gatekeeper.py` 实现服务间独立凭证与 `service_id`/`tenant_id`/`user_id` 三重绑定（未配置时回退静态共享密钥，灰度可回滚）；口令重置走一次性凭据 + 管理员代重置置 `must_change_password` 并 5h 兜底过期；+76 条安全用例；admin-api 760 passed / chat-api 2549 passed）；Phase 3「容器非 root + 服务身份最小权限」T023–T029 ✅（4 个 Dockerfile 非 root UID/GID 10001：admin-api / chat-api / document-parser 用 Debian `groupadd`/`useradd`，admin-web 基于 Alpine 用 BusyBox `addgroup`/`adduser`，另新增 `apps/admin-web/nginx-main.conf` 供非 root master 使用；docker-compose 8 个服务加固 `no-new-privileges` + `cap_drop ALL` + `read_only` + tmpfs，nginx 服务仅保留 `NET_BIND_SERVICE` 并额外挂载 `/var/cache/nginx` 与 `/var/log/nginx`，tmpfs 必须显式 `mode=`（Docker 默认 0755 非 root 写不进）；`bootstrap` 的 `umask 077 → 022` 保证非 root 容器能读 `runtime.env`；`ServiceTokenClaim` 新增 `scope` 权限码集合 + `gatekeeper` 端点注册表，`verify_service_call(required_scope=...)` 对 `insufficient_scope`/`unknown_scope` fail-closed；存储路径默认值改绝对路径、`admin_static_dir` 与 `ReportFileManager` 的 mkdir 失败降级告警；新增 `deploy/tests/test_container_hardening.py` 58 passed / 6 skipped；实测 admin-api 镜像在完整加固参数下 `id -u`=10001 且 uvicorn 启动至连 MongoDB 前 0 条权限错误，admin-web(nginx) 同等参数下 `http 200`；admin-api 772 passed / chat-api 2549 passed）；Phase 4「输入安全加固」T030–T035 ✅（chat-api SSO 票据 TTL 从 12h 收敛到 60s，新增 admin-api `POST /api/auth/sso/exchange`（HMAC 签名 + 过期校验，`hmac.compare_digest` 常数时间比较，fail-closed 401）+ accept-once 幂等（按票据 `session_id` 打 `exchanged` 标记，`upsert=True`，二次换票 401）；前端 user-web 用 `window.open(url,'_blank','state=...')` 传令牌，admin-web 从 `window.history.state` 读取并 POST 换票 —— 令牌不再进地址栏/历史/书签；QF-637 点名的 4 个 GET 写端点全部改造：GET 只读、写操作拆到显式 POST（`/auth/me/refresh-tenants`、`/sessions/{id}/read`、`/personal-knowledge/{id}/ack`、`/organizations/billing/init`）；新增 `deploy/tests/test_no_side_effects_get.py` 用 AST 静态扫描双服务全部 GET 路由函数兜底，任何 GET 函数体内出现 Mongo 写 API 即失败；新建双服务 `app/middleware/cors.py`：`allow_methods`/`allow_headers` 收敛为显式白名单，入口拒绝通配符（`*`/`*.example.com`/`http://a/*` 一并拦截 —— `allow_credentials=True` 下 Starlette 无法正确反射通配源），来源由 `CORS_ORIGINS` 配置、空列表为合法状态但告警可见；测试：`test_sso_token_not_in_url.py` 6 条 + `test_security_cors.py` 各 29 条（含真实 CORSMiddleware preflight：非白名单 origin 400、请求的头部不在白名单时预检 400 且不反射攻击头、通配源不被反射）+ `test_security_sso_exchange.py` 15 条；admin-api 816 passed（基线 772，+44））；Phase 5「数据安全与加密」T036–T045 ✅（新建 `deploy/nginx/nginx.conf` 作为 TLS 侧配置唯一事实来源：HTTP→HTTPS **301**（`/healthz` 例外供 LB 探针）、`ssl_protocols TLSv1.2 TLSv1.3`、仅 AEAD 密码套件、`ssl_session_tickets off`、HSTS（180 天 + includeSubDomains + preload）+ CSP/nosniff/frame-options、透传 `X-Forwarded-*`；`deploy/docker/nginx-https.conf` 保留为兼容入口并指向规范路径；docker-compose `gateway` 暴露 `${MOGO_HTTPS_PORT:-443}:443`，新增 `MOGO_NGINX_CONF` 实现挂载层切换（gateway 容器 `read_only` 无法运行时生成配置，证书缺失时 nginx 启动直接失败是预期行为，避免「以为开了 TLS 实际裸奔」）；T038–T041 复核确认已落位无需新增改动：`model_repository.py` 已落 `api_key_encrypted`/`api_secret_encrypted` + masked 展示值、`auth.py::_store_mfa_secret` 已落 `mfa_secret_encrypted`（AES-GCM, AAD=`mfa_secret`）+ `mfa_secret_hash`、`knowledge_settings.py` 已落 `apiKeyEncrypted`/`apiKeyMasked`、`org_user_repository.py` 只落 `password_hash`+`password_salt`；响应层全部走显式白名单序列化（`_format_account`、`_format_instance` 只吐 masked 值），白名单优于黑名单，新增字段默认不泄露；审计写入前 `redaction.redact(detail)` 已生效；T042：admin-api 放宽 prod 判定为 `production|prod|release` 别名并强制 `debug=False`（误配降级告警），chat-api 新增 `APP_ENV` + 全局 `@app.exception_handler(Exception)`（原缺失，prod 下只回 `Internal server error` 不回显 `str(exc)`），调试端点 `require_debug_mode` + `require_end_user_principal` 双闸门保留；T043 新建 `data/data-map.md`：4 张字段级 PII 表（L1–L4 等级 + 加密状态 + 处理依据 + 留存 + 删除入口）、存储位置与审计库分离、GDPR 数据主体权利矩阵（访问✅/更正✅/导出⚠️/删除✅级联/限制⚠️）、5 条合规差距清单（G1 账号级一键导出、G2 同意撤回流、G3 第三方 LLM 侧留存不可控、G4 生产须显式配 `MONGODB_AUDIT_DB`、G5 OSS 生命周期策略）；T044：`MIN_AUDIT_RETENTION_DAYS=180` + `normalize_retention_days()`（低于下限自动提升到 180 并告警，-1 禁用 TTL）、`ensure_indexes()` 注册 MongoDB TTL 索引 `audit_events_retention_ttl`、新增 `purge_expired()`（游标文档不参与判定，否则哈希链续写基准会被清掉）、新增 `get_audit_db()` 实现审计库分离（`ASKAI_ADMIN_AUDIT_DB`/`MONGODB_AUDIT_DB`，未配置回退业务库保持既有部署可用）；哈希链防篡改 `chain_hash`/`verify_chain`/`AuditChainBroken` 为 T006 既有能力；测试：`deploy/tests/test_data_security_us5.py` 23 条（TLS 7 + 密文存储 5 + 日志脱敏 3 + 审计 5 + 数据地图 2 + 仓库层明文扫描 1）；admin-api 816 passed；chat-api 2589 passed / 2 failed（2 条为其他会话在途的 `dsh_runtime/test_document_script_boundaries.py`，与本轮无关）；`docker compose config --quiet` 通过）；Phase 6「供应链安全」T046–T053 ✅（`quality-gate.yml` 的 `backend-quality` 作业新增 `pip-audit -r requirements.txt` 置于测试之前（依赖缺陷与代码缺陷是两条独立风险线，依赖树有问题不必再跑一遍测试）；trivy 已 SHA 固定并限定 `CRITICAL,HIGH` + `ignore-unfixed`；新增 `scripts/check-secrets.sh`（13 条高置信模式：PEM/AWS/GCP/GitHub PAT/Slack/Stripe/JWT/通用 secret 赋值，1 条低置信 40+ 位 base64 仅 `--all` 提示不阻断）+ `.githooks/pre-commit`（按 `git diff --cached` 范围扫，`SKIP_SECRETS_CHECK` 紧急绕过）+ `supply-chain-gate` 作业全量 `--all` 扫描；两条防线互补：钩子拦不住「改了再改回」的历史密钥，CI 全量扫能拦；`container-release.yml` 新增作业级 `permissions`：`validate-release`/`plan-release` 只读，`publish-candidates` 持 `packages: write` + `id-token: write` 但**无** `contents: write`（无法推 tag 或改 workflow 绕过审批），`promote-release` 绑定 `environment: production` 触发仓库环境保护规则（可要求人工审批）+ 限定 `github.event_name == 'push'`；新增 `scripts/check_action_pinning.py` 把「发布关键动作必须 SHA 固定」变成可执行政策（MUST_PIN 8 个 / TAG_OK 12 个 / 迁移期豁免 6 个），`quality-gate.yml` 接入阻断；6 个 Docker action 因当前环境无法访问 GitHub API 解析 tag→SHA，登记为 RR-001 迁移期豁免；发布路径已有 `provenance: mode=max` + `sbom: true` + `attest-build-provenance` + 二次构建可复现性校验；新增 `docs/security/VULNERABILITY_POLICY.md`（CVSS+可达性双维度分级：CRITICAL 7 日/HIGH 30 日/MEDIUM 下 minor/LOW 下 major，11 字段工单模板、处理流程、公告时机）+ `docs/security/SECURITY_ADVISOIR_TEMPLATE.md` + `docs/security/RESIDUAL_RISK.md`（四要素强制：风险接受人+临时缓解+重审 ≤90 日+补偿性控制；失效规则：到期未续自动失效、缓解措施移除立即失效、累计 ≥3 条触发架构复盘）；`SECURITY.md` 追加 §6 详细政策索引与 §7 供应链防线矩阵；测试：`deploy/tests/test_supply_chain_us6.py` 22 条（CVE 阻断 5 + 权限分离 5 + 密钥钩子 7 + 容器非 root 交叉引用 1，含 6 类密钥模式的**真实脚本运行**正向验证与干净代码反例验证）；`test_data_security_us5.py` + `test_supply_chain_us6.py` 合计 45 passed；`scripts/check_action_pinning.py` exit=0；`docker compose config --quiet` 通过）；Phase 7「收尾与全量验证」T054–T058 ✅（`deploy/tests/test_performance_us7.py` 7 条：口令校验 p95（PBKDF2-100k）、完整登录链路 p95（哈希+令牌+序列化）、JWT 解码与拒绝 p95、CORS 预检与拒绝 p95，阈值设为目标 2 倍以吸收 CI 抖动，作用是回归检测；新增 `docs/security/SECURITY_CONFIGURATION.md`：8 个子域（令牌/超时/CORS/审计/调试/加密/TLS）每项含默认值+范围+说明，附配置验证脚本；QF 基线自检：022 覆盖 17 个 QF 条目（P0 4 + P1 13），QF-634 SSO 换票→T030、QF-637 GET 无副作用→T032、QF-635 CORS→T033/T034、QF-650/652/654/656 密钥权限与加密→T003/T038/T039、QF-655 静态加密→T038/T039、QF-561 服务身份→T028、QF-674/676 审计防篡改+库分离→T044、QF-703 安全公告→T051、QF-712 全链路加密→T036/T037、QF-714 Cookie 安全→T036 nginx、QF-679 依赖扫描→T046、QF-681/682/702 漏洞政策→T051/T052；QF-707/QF-710（备份加密/灾备演练）与 QF-660/QF-662（响应权限裁剪/非生产脱敏）已全部关闭（见 QF 关闭轮次）；quickstart 验证清单 22→28 项，测试命令含 US6/US7 + 供应链门禁；WORK_LOG 每 Phase 均已记录；验证：US3–US7 集成测试合计 104 passed；check_action_pinning.py exit=0；check-secrets.sh --all 通过）；**022 全部 7 Phase（T001–T058）完成**

> 注：「本轮补齐」= 2026-09 SDD 补全轮。clarify 消解记录位置说明：001/002/007–011 在 spec 的 "Clarify 记录" 节，012–019 在 plan 的 "Open Questions（已 clarify 消解）" 节，020 与 022 在 tasks.md 的 "Clarify Decisions" 节。023–026 的规约层 clarify 已全部消解（023 的 OQ-1~OQ-8 于 2026-10-24 经 `/speckit-clarify` 消解，见上方「⚠️ 落地口径更正」段；024/025/026 的待澄清项亦已定值），规约层阻塞解除，剩余缺口纯属实现排期。


> **📌 进度校正（2026-10-26 更新）**：024 **112/119**（Phase 1–11 完成，余 7 项 T081/T085/T086/T106/T107/B004/B005 为真实环境演练/真实 docker daemon 类任务，如实留空不勾）。023 已 126/126、025 已 52/52、026 已 56/57（余 T041 水平扩展压测需真实环境），均见上方表格对应行。

---

## 2026-11-11 复核增补（standard 深度全量 QA 审计 · 54 特性口径）

> 来源：`deliverables/QA-AUDIT-STANDARD-2026-11-11.md`。本轮按 `standard` 口径对
> `specs/[0-9][0-9][0-9]-*/` 全量重扫，**不沿用 11-06 / 11-09 旧数字**。

- 磁盘目录 **54 个**：001–053 + 055（055 菜单管理，2026-11-10 新增）；054 资源中心由其它会话在途，磁盘尚未落地，不计入。
- 五件套：`spec.md` / `plan.md` / `tasks.md` / `checklists/requirements.md` **54/54 齐备**；`quickstart.md` 修前 **49/54**（050/051/052/053/055 缺），本轮补齐后 **54/54**。
- `tasks.md` 勾选 **1681/1696 = 99.12%**；100% 勾选 **50** 个特性，部分勾选 **4** 个（017 / 024 / 049 / 051，共余 15 项，均为环境 / 维护窗口 / 人工凭据类保留）。
- 门禁清单：严格口径 **49 份 100% 勾选**；003–006 四份既有回溯未审（0 勾）；017 为 v3 Gate 四态表、无 checkbox。
- 版本口径：7 处版本来源 + `MCP_CLIENT_VERSION` + 3 份 OpenAPI `info.version` 全部 **0.2.8**，与 `git tag v0.2.8` 对齐；运行栈为 **k3s**（7 个业务 Pod 镜像均为 `v0.2.8`，其中 `admin-web` 于本轮 2026-11-11 重建含菜单方案未认证时序 401 修复）。
- 主键终态：2026-11-11 停机窗口完成全库归一，**只认 32-hex**（`docs/id-unification-hex32-runbook.md`）；040 的 spec / checklist 已同步去掉 24-hex 旧口径。
- 本轮修复：`tenant_purge` 补齐 050–053 引入的 7 个租户集合、051 新增审计事件断言、5 份 quickstart、README / INDEX / PPT / CHANGELOG 计数、`drift` / `verify` 在 k3s 栈下的假阳性守卫。
