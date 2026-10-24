# 特性规约总览（SDD Index）

> 📌 **口径提示（2026-10-05 更新）**：本文件记录的是 **spec/plan/checklist/tasks 的文档完成度**。
> **2026-10-03 落地审计**（`LANDING_AUDIT_2026-10-03.md`）判定 `landed` 0 · `partial` 10 · `hollow` 9，
> 该审计的**全部高危缺口已在 2026-10-03 至 2026-10-05 期间修复**（见各特性"已修"条目）。
> **017（three-scope-memory）与 021（unified-context-address）** 在 2026-10-05 优化轮完整实现：
> 密度轴 L0/L1/L2、渐进检索、`mogo://` 统一地址空间、四根适配器（memory/resource/skill/session）、
> 会话沉淀接线 —— 均已通过测试（2146 + 433 + 22 = 2601 项全绿，2026-10-05 基线）并具备生产接线。
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
> **2229 + 433 + 22 = 2684 项全绿**（chat-api / admin-api / document-parser）；specs 目录已达
> **21 个特性**（含 021），其中 **17 份 `tasks.md` / 354 项全部勾选**。本文件下方的
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
| 017 | three-scope-memory（叠加密度轴 L0/L1/L2 + 检索轨迹 + 会话结合，详见 021） | 清单 13 | P2 | ✅ | ✅ |
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
| 023 | observability-resilience（可观测性与韧性） | 74 个 P0/P1 缺陷：日志/追踪/指标/告警/容错/恢复 6 域 | P1 | ✅ | ✅ | ✅ | 🔨 **13/126**（Phase 1 基座已落地：T001–T005 公共基座 services/common/ 三模块 + 三服务 vendored 副本 + 字节一致性 CI 门禁；T006–T008 三服务 6 依赖钉扎；T009–T013 可观测性栈（--profile observability 门控，默认部署形态不变）+ deploy/ 全量配置。OQ-1~OQ-8 已于 2026-10-24 消解——可直接继续 Phase 2+） |
| 024 | deployment-hardening（部署与发布） | 42 个 P0/P1 缺陷：部署安全/制品/灰度/回滚/灾备 5 域 | P1 | ✅ | ✅ | ✅ | 🔨 **18/119**（**Phase 1 已落地**：T001–T010 既有能力核实 + T012 脚本门禁扩展 + T014 compose user: 字段 + T015 安全基线校验 + T016–T018 基线工具链 + T019 mogo baseline 子命令；T011 需 docker run 实证，余 US2–US4 未开工） |
| 025 | api-contract-hardening（API 契约与语义） | 50 个 P0/P1 缺陷：语义/错误/契约/演进 4 域 | P1 | ✅ | ✅ | ✅ | 🔨 7/52（**Phase 1 已落地**：T001–T007 错误结构统一 + trace_id + CI 唯一性门禁，三服务全量测试通过，2026-10-24；余 US1–US4 未开工） |
| 026 | performance-scalability（性能与扩展性） | 51 个 P0/P1 缺陷：基线/DB/缓存/前端/扩展性 5 域 | P1 | ✅ | ✅ | ✅ | 🔨 **5/57**（**Phase 1 已落地**：T001–T005 模块骨架——cache/manager.py、perf_baseline.py、perf_budget.py、api/middleware/perf.py、benchmarks/ 目录结构；US1 性能基线未开工） |

> 背景：QualityForge standard 深度全量 QA 审计（964 项，pass 298 / blocked 442 / fail 162 / na 59 / verified 3）发现的 P0/P1 代码级缺陷与基础设施缺口。283 个缺陷需建能力（022-026 覆盖），其余 341 个为流程/测试/文档缺口（不需 spec，直接修复）。详见 `.qualityforge/QUALITYFORGE-REPORT.md`。
>
> **⚠️ 落地口径更正（2026-10-24 QA R11）**：022–026 的 **checklist（需求质量门禁）100% 勾选**与 **tasks（实现任务）落地** 是两件事，不能混用。实际状态：022 已完整落地（58/58）；**023 / 024 / 025 / 026 四个特性当时代码未开工（tasks 勾选 0/126、0/119、0/52、0/57，合计 0/354）**。因此「所有特性全流程已就绪」的宣称对这 4 个特性**不成立**，本轮发布范围不含它们；其覆盖的 QualityForge 缺陷仍以「已立项、未实现」登记。阻塞原因须逐特性区分，不可一概写作「待 OQ-1~OQ-8」：023 原有 8 个 open OQ（日志/追踪后端、熔断库、备份存储、告警渠道、SLO、RTO/RPO、跨 AZ 方式），**已于 2026-10-24 全部消解**（决策见其 spec「Clarify 记录」与 tasks「Clarify Decisions」：Loki / Tempo / pybreaker / 本地磁盘+S3 兼容异地 / IM webhook+邮件 / 99.9%·P99<3s·LLM错误率<1% / RTO≤30min·RPO≤15min / 单宿主机演练如实声明）；025 的 OQ-1~OQ-5 早于 2026-10-11 消解完毕；024 无 open OQ（全部决策登记于 spec「Assumptions」节，checklist CHK017 已核对）；026 的预算阈值已于 2026-10-24 定值（spec「Clarify 记录」预算表）。**四者规约层阻塞全部解除，剩余缺口纯属实现排期**——按 tasks.md Phase 1 起可直接开工。

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

**跨批次依赖关系**（本批次内部）：032 产出评测数据 → 036 消费（自动降级）；034 凭证加密 → 041 验收依赖；035 单条成本透出 → 043 成本行展示（未落地时降权）；033 扩展 016、035 扩展 008、042 扩展配额体系、044 扩展 010（均含"同步更新被扩展特性 spec/契约"的联合改动点，见各 tasks）。

**落地节奏**（整合方案 §5 三波次）：Wave 1 治理闭环 = 032+033+034；Wave 2 运营与产品完整性 = 035+036+037+038；Wave 3 生态体验 = 039–044 按资源选做。

## 五、规约完成度统计

- spec.md：001–044 全部完成（44 份；028 会话级轨迹双 tab、029 user-web SSO 接收方，均于 2026-10-15 新增；030 本体数据权限 / 031 模型供应商发现为回溯补规格；**032–044 为 2026-10-23 AgentOS 整合批次，13 份全新特性规约，详见「四（补 6）」**）
- plan.md：001–044 全部完成（44 份；020 为技术化实施计划，022–026 为质量加固特性计划，027 为数据后端迁移计划，028 为路线 C 前端视图方案，029 为 SSO 接收方实施计划，032–044 为 AgentOS 整合实施计划，其余技术契约齐全）
- checklist（需求质量门禁，`/speckit-checklist`）：001–028 完成（28 份，029 未建，`checklists/requirements.md`，reviewer-owned）；**001/002/007–021 共 17 份已 agent 代审 + FR 回填 + 跨特性双向声明，100% 勾选达标**；003–006（既有回溯）保留原始未勾状态；**022–026（质量加固）已于 2026-10-12 补齐 checklist（17–18 项/份，含 FR 覆盖、跨特性一致性、Non-Goals 边界与 OQ 待定标记），100% 勾选达标**；**027（数据后端迁移）于 2026-10-13 新建（35 项，勾选 33/35；未勾 2 项 CHK015 性能预算 / CHK027 索引验收口径 仍未定值——R2 已交付、R3 已按表结构扁平化推进，未依赖该阈值、未阻塞落地）**；**032–044（AgentOS 整合批次）13 份已于 2026-10-24 全部建成**（`specs/032-eval-gate/checklists/` … `specs/044-multi-agent-modes/checklists/`，各 15–16 项，四分类：完整性 / 清晰度 / 一致性 / 边界与歧义），**全部 100% 勾选达标**，13 份均经 agent 代审 + spec「判定口径补充」回填（R-1…R-16 逐条对应 CHK）。回填同时完成三件事：① 修正 spec 与代码不一致的路径/枚举（如 042 的 `ANOMALY_STATUSES` 不可复用、044 的 `contracts/` 目录不存在、043 的 `V3ItemKind` 无成本字段）；② 把先前含糊的口径定成可执行常量与判定序（阈值、归一化、钳制、fail-closed 分支）；③ 显式登记「首期未实现 + 建议落点」（040–044 原为代码零开工，已在本会话实现并勾选 tasks，各 spec 标注保留）
- tasks（可执行任务，`/speckit-tasks`）：**001–044 共 44 份全部建齐**（001/002/007–021 的 17 份含 clarify 决策 + checklist 门禁 + 故事分阶段 + 并行点 + MVP，354 项全部勾选；**2026-10-11 新增 003/004/005/006 的 4 份**，共 141 项任务；**2026-10-11 新增 022–026 的 5 份**，共 357 项任务，覆盖 QualityForge 审计 283 个 P0/P1 缺陷；**2026-10-13 新增 027 的 1 份**，共 75 项任务（R1 T001–T068、R2 T069–T087），已全部勾选并附实测证据）；**2026-10-15 新增 028/029 的 2 份**——028 共 10 项已全部勾选（实现与自动化验证均完成，quickstart 的 6 步目视验证待用户在 dev 环境执行）；029 共 20 项已全部勾选并实现（2026-10-15，端点 + 换票 + 门户示例 + 前端换票闭环，api/security/core 回归全绿）；**2026-10-23 新增 032–044 的 13 份**（共 358 项）——**2026-10-24 状态：勾选 337/358**。已落地：032（22/22 完整实现）、033（22/22）、034（33/37，保留 T033–T036 需 staging 备份演练；本地段 `tests/test_drill_credential_scripts.py` 1 passed 已覆盖 dry-run→apply→verify→二次幂等→轮换，SC-005 段闭环）、035（31/35，T017 缺口于 2026-10-24 闭环：`adapters.py` 两处 `set_request_context` 改 `merge_request_context` + 新增 `tests/enterprise_capabilities/runtime/test_035_capability_attribution_scope.py` 7 passed（合并 11 passed）回归 971 passed；T031–T034 待 staging）、036（28/29，T018 skills 侧 FR-014 于 2026-10-24 端到端落地：新增 `services/admin-api/app/services/trust_rating/skill_visibility.py` + `routes/skills.py` 接线 + `tests/test_skill_l1_visibility.py` 8 用例合计 59 passed；T019/T020/T021/T027 前端于 2026-10-24 交付：`src/api/trustRatings.ts` + `src/views/trust-ratings/TrustRatingPage.vue` + `SkillsPage.vue` L1–L4 徽标 + `/trust-ratings` 路由 + `DashboardPage.vue` 评级分布卡，vue-tsc exit 0 + SFC 编译 3 个 .vue ok；仅 T028 E2E 待 staging）、037（29/31）、038（32/34，T022/T023/T024 前端于 2026-10-24 交付：`src/api/egress.ts` + `src/views/egress/{EgressAllowlistPage,EgressLogsPage}.vue` + `/egress/allowlist` `/egress/logs` 两条路由，vue-tsc exit 0 + SFC 编译 ok；T025 工具编辑页入口与 T032 E2E 待人工）、039（30/33，T028/T029 前端单测未落地、T030 E2E）；**2026-10-24 追加落地：040（18/20，T017 需真实模型凭证、T019 需与 008 联调）、043（20/21，T019 手工浏览器验收待人工）、041（23/24，T019 mock 全链路 E2E 于 2026-10-24 闭环：`services/chat-api/tests/test_connector_market_mock_e2e.py` 4 passed（本地 `ThreadingHTTPServer` + gitlab-api 模板）；T022 034 联调验收待 staging）、042（23/24，T023 手工联调待人工；SFC 编译与 vue-tsc 已过）、**044（26/26，多 Agent 轮询择优 / 辩论对质：010 引擎扩 `round_robin`/`debate` 两模式 + 新建 `contracts/orchestration.md` 六模式契约，新增测试 45 passed + 010 全量回归 136 + `competitor_deep_dive` 迁移后 28）**各份 tasks.md 末尾均附「验收状态（2026-10-24 交接复核）」节记录证据与未勾原因
- **AgentOS 整合批次落地进度（2026-10-24 复核）**：Wave 1–2（032–038）+ Wave 3 首个特性（039）代码已由并行会话落地，本会话按 SDD 门禁逐份复核（生成 checklist → spec 回填 → 跑测试 → 勾 tasks）；**040（档位路由）、043（会话回放 Stage 1）、041（连接器市场）、042（三级配额）、044（多 Agent 模式）均已由本会话实现并勾选**，032–044 全部落地，无代码零开工特性。测试证据：032 `test_eval_gate.py` 31 项 + `test_skill_lifecycle.py` 3 项；033 `test_canary_ratio.py` 19 + `test_canary_shadow.py` 9；034 70 + 13（含新增 `test_migrate_tool_credentials.py` 9、`test_rotate_tool_credentials.py` 4）；035 8 + 4 + dashboard 回归 42；036 `test_trust_rating.py` 25；037 25 + 27；038 15 + 28 + 脚本沙箱回归 2；039 11；044 45 + 010 引擎全量 136（含 `competitor_deep_dive` 迁移回归 28）；040 19 + `tests/llm` 全量 90；041 `test_connector_market.py` 14 + 工具/资产回归 66；043 `tests/session-replay.test.ts` + `trajectory-view-tabs` 8；042 `test_quota_three_level.py` 13 + 13（双服务同内容）、`test_quota_projects.py` 9、`test_quota_unlimited.py` 9 与 `test_governance_us4_us5.py` 13 回归。全部前端改动经 `@vue/compiler-sfc` 3.4.38 编译校验通过（admin-web/user-web `vue-tsc --noEmit` 均 0 错误）。
- **2026-10-24 staging/E2E 缺口修复（第二批次）**：035 T017、036 FR-014 端到端 + 前端、038 前端、041 mock E2E、034 本地演练均已闭环（证据见各 tasks「验收状态」节与逐条勾选备注）；**仍待人工/staging 的 21 项**：034 T033–T036（staging 备份回滚/SC-002 注入回放/多副本轮换）、035 T031–T034、036 T028、038 T025/T032、039 T028–T030、040 T017/T019、041 T022、042 T023、043 T019。所有 staging 项均附执行步骤与判定口径（`docs/credential-key-rotation-drill.md` 与各 spec「判定口径补充」），未伪造勾选。
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
| 017 three-scope-memory | 12/15 | Workspace 粒度、默认策略、授权角色、衰减口径、三级可见性、001 治理点、离职处置、超限拒绝、多范围各存、检索过滤；**2026-10-05 优化轮新增密度轴（L0/L1/L2）+ 渐进检索 + mogo:// 地址 + 会话分层沉淀**，接 021 | 017↔005/002/006/021 |
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
  - **022 Wave 1 进度（2026-10-12）**：Phase 0「安全基座」T001–T006 ✅（双服务 `app/security/` 6 模块 + 各 176 单测）；Phase 1「口令与 MFA 强制策略」T007–T013 ✅（新增 `mfa_gate.py` 组合层；admin-api 登录闸门 + `/mfa/verify` 限流与 90s 防重放 + 绑定/解绑审计与通知降级；双服务口令策略统一 ≥12 位、4 类取 3；+32 条 gate 集成测试；admin-api 641 passed / chat-api 2474 passed）；Phase 2「令牌与会话生命周期」T014–T022 ✅（双服务 access token TTL 收敛到 1h + 启动告警；`/auth/refresh` 打通一次性轮换 + 重放吊销整个 family；新增共享 `session_timeout.py` 落地空闲 30min / 绝对 24h 判定（admin-api 经 `deps` 覆盖全部需认证路由、chat-api 经 `resolve_session_user`）；新增 `service_token.py` + `gatekeeper.py` 实现服务间独立凭证与 `service_id`/`tenant_id`/`user_id` 三重绑定（未配置时回退静态共享密钥，灰度可回滚）；口令重置走一次性凭据 + 管理员代重置置 `must_change_password` 并 5h 兜底过期；+76 条安全用例；admin-api 760 passed / chat-api 2549 passed）；Phase 3「容器非 root + 服务身份最小权限」T023–T029 ✅（4 个 Dockerfile 非 root UID/GID 10001：admin-api / chat-api / document-parser 用 Debian `groupadd`/`useradd`，admin-web 基于 Alpine 用 BusyBox `addgroup`/`adduser`，另新增 `apps/admin-web/nginx-main.conf` 供非 root master 使用；docker-compose 8 个服务加固 `no-new-privileges` + `cap_drop ALL` + `read_only` + tmpfs，nginx 服务仅保留 `NET_BIND_SERVICE` 并额外挂载 `/var/cache/nginx` 与 `/var/log/nginx`，tmpfs 必须显式 `mode=`（Docker 默认 0755 非 root 写不进）；`bootstrap` 的 `umask 077 → 022` 保证非 root 容器能读 `runtime.env`；`ServiceTokenClaim` 新增 `scope` 权限码集合 + `gatekeeper` 端点注册表，`verify_service_call(required_scope=...)` 对 `insufficient_scope`/`unknown_scope` fail-closed；存储路径默认值改绝对路径、`admin_static_dir` 与 `ReportFileManager` 的 mkdir 失败降级告警；新增 `deploy/tests/test_container_hardening.py` 58 passed / 6 skipped；实测 admin-api 镜像在完整加固参数下 `id -u`=10001 且 uvicorn 启动至连 MongoDB 前 0 条权限错误，admin-web(nginx) 同等参数下 `http 200`；admin-api 772 passed / chat-api 2549 passed）；Phase 4「输入安全加固」T030–T035 ✅（chat-api SSO 票据 TTL 从 12h 收敛到 60s，新增 admin-api `POST /api/auth/sso/exchange`（HMAC 签名 + 过期校验，`hmac.compare_digest` 常数时间比较，fail-closed 401）+ accept-once 幂等（按票据 `session_id` 打 `exchanged` 标记，`upsert=True`，二次换票 401）；前端 user-web 用 `window.open(url,'_blank','state=...')` 传令牌，admin-web 从 `window.history.state` 读取并 POST 换票 —— 令牌不再进地址栏/历史/书签；QF-637 点名的 4 个 GET 写端点全部改造：GET 只读、写操作拆到显式 POST（`/auth/me/refresh-tenants`、`/sessions/{id}/read`、`/personal-knowledge/{id}/ack`、`/organizations/billing/init`）；新增 `deploy/tests/test_no_side_effects_get.py` 用 AST 静态扫描双服务全部 GET 路由函数兜底，任何 GET 函数体内出现 Mongo 写 API 即失败；新建双服务 `app/middleware/cors.py`：`allow_methods`/`allow_headers` 收敛为显式白名单，入口拒绝通配符（`*`/`*.example.com`/`http://a/*` 一并拦截 —— `allow_credentials=True` 下 Starlette 无法正确反射通配源），来源由 `CORS_ORIGINS` 配置、空列表为合法状态但告警可见；测试：`test_sso_token_not_in_url.py` 6 条 + `test_security_cors.py` 各 29 条（含真实 CORSMiddleware preflight：非白名单 origin 400、请求的头部不在白名单时预检 400 且不反射攻击头、通配源不被反射）+ `test_security_sso_exchange.py` 15 条；admin-api 816 passed（基线 772，+44））；Phase 5「数据安全与加密」T036–T045 ✅（新建 `deploy/nginx/nginx.conf` 作为 TLS 侧配置唯一事实来源：HTTP→HTTPS **301**（`/healthz` 例外供 LB 探针）、`ssl_protocols TLSv1.2 TLSv1.3`、仅 AEAD 密码套件、`ssl_session_tickets off`、HSTS（180 天 + includeSubDomains + preload）+ CSP/nosniff/frame-options、透传 `X-Forwarded-*`；`deploy/docker/nginx-https.conf` 保留为兼容入口并指向规范路径；docker-compose `gateway` 暴露 `${MOGO_HTTPS_PORT:-443}:443`，新增 `MOGO_NGINX_CONF` 实现挂载层切换（gateway 容器 `read_only` 无法运行时生成配置，证书缺失时 nginx 启动直接失败是预期行为，避免「以为开了 TLS 实际裸奔」）；T038–T041 复核确认已落位无需新增改动：`model_repository.py` 已落 `api_key_encrypted`/`api_secret_encrypted` + masked 展示值、`auth.py::_store_mfa_secret` 已落 `mfa_secret_encrypted`（AES-GCM, AAD=`mfa_secret`）+ `mfa_secret_hash`、`knowledge_settings.py` 已落 `apiKeyEncrypted`/`apiKeyMasked`、`org_user_repository.py` 只落 `password_hash`+`password_salt`；响应层全部走显式白名单序列化（`_format_account`、`_format_instance` 只吐 masked 值），白名单优于黑名单，新增字段默认不泄露；审计写入前 `redaction.redact(detail)` 已生效；T042：admin-api 放宽 prod 判定为 `production|prod|release` 别名并强制 `debug=False`（误配降级告警），chat-api 新增 `APP_ENV` + 全局 `@app.exception_handler(Exception)`（原缺失，prod 下只回 `Internal server error` 不回显 `str(exc)`），调试端点 `require_debug_mode` + `require_end_user_principal` 双闸门保留；T043 新建 `data/data-map.md`：4 张字段级 PII 表（L1–L4 等级 + 加密状态 + 处理依据 + 留存 + 删除入口）、存储位置与审计库分离、GDPR 数据主体权利矩阵（访问✅/更正✅/导出⚠️/删除✅级联/限制⚠️）、5 条合规差距清单（G1 账号级一键导出、G2 同意撤回流、G3 第三方 LLM 侧留存不可控、G4 生产须显式配 `MONGODB_AUDIT_DB`、G5 OSS 生命周期策略）；T044：`MIN_AUDIT_RETENTION_DAYS=180` + `normalize_retention_days()`（低于下限自动提升到 180 并告警，-1 禁用 TTL）、`ensure_indexes()` 注册 MongoDB TTL 索引 `audit_events_retention_ttl`、新增 `purge_expired()`（游标文档不参与判定，否则哈希链续写基准会被清掉）、新增 `get_audit_db()` 实现审计库分离（`ASKAI_ADMIN_AUDIT_DB`/`MONGODB_AUDIT_DB`，未配置回退业务库保持既有部署可用）；哈希链防篡改 `chain_hash`/`verify_chain`/`AuditChainBroken` 为 T006 既有能力；测试：`deploy/tests/test_data_security_us5.py` 23 条（TLS 7 + 密文存储 5 + 日志脱敏 3 + 审计 5 + 数据地图 2 + 仓库层明文扫描 1）；admin-api 816 passed；chat-api 2589 passed / 2 failed（2 条为其他会话在途的 `dsh_runtime/test_document_script_boundaries.py`，与本轮无关）；`docker compose config --quiet` 通过）；Phase 6「供应链安全」T046–T053 ✅（`quality-gate.yml` 的 `backend-quality` 作业新增 `pip-audit -r requirements.txt` 置于测试之前（依赖缺陷与代码缺陷是两条独立风险线，依赖树有问题不必再跑一遍测试）；trivy 已 SHA 固定并限定 `CRITICAL,HIGH` + `ignore-unfixed`；新增 `scripts/check-secrets.sh`（13 条高置信模式：PEM/AWS/GCP/GitHub PAT/Slack/Stripe/JWT/通用 secret 赋值，1 条低置信 40+ 位 base64 仅 `--all` 提示不阻断）+ `.githooks/pre-commit`（按 `git diff --cached` 范围扫，`SKIP_SECRETS_CHECK` 紧急绕过）+ `supply-chain-gate` 作业全量 `--all` 扫描；两条防线互补：钩子拦不住「改了再改回」的历史密钥，CI 全量扫能拦；`container-release.yml` 新增作业级 `permissions`：`validate-release`/`plan-release` 只读，`publish-candidates` 持 `packages: write` + `id-token: write` 但**无** `contents: write`（无法推 tag 或改 workflow 绕过审批），`promote-release` 绑定 `environment: production` 触发仓库环境保护规则（可要求人工审批）+ 限定 `github.event_name == 'push'`；新增 `scripts/check_action_pinning.py` 把「发布关键动作必须 SHA 固定」变成可执行政策（MUST_PIN 8 个 / TAG_OK 12 个 / 迁移期豁免 6 个），`quality-gate.yml` 接入阻断；6 个 Docker action 因当前环境无法访问 GitHub API 解析 tag→SHA，登记为 RR-001 迁移期豁免；发布路径已有 `provenance: mode=max` + `sbom: true` + `attest-build-provenance` + 二次构建可复现性校验；新增 `docs/security/VULNERABILITY_POLICY.md`（CVSS+可达性双维度分级：CRITICAL 7 日/HIGH 30 日/MEDIUM 下 minor/LOW 下 major，11 字段工单模板、处理流程、公告时机）+ `docs/security/SECURITY_ADVISOIR_TEMPLATE.md` + `docs/security/RESIDUAL_RISK.md`（四要素强制：风险接受人+临时缓解+重审 ≤90 日+补偿性控制；失效规则：到期未续自动失效、缓解措施移除立即失效、累计 ≥3 条触发架构复盘）；`SECURITY.md` 追加 §6 详细政策索引与 §7 供应链防线矩阵；测试：`deploy/tests/test_supply_chain_us6.py` 22 条（CVE 阻断 5 + 权限分离 5 + 密钥钩子 7 + 容器非 root 交叉引用 1，含 6 类密钥模式的**真实脚本运行**正向验证与干净代码反例验证）；`test_data_security_us5.py` + `test_supply_chain_us6.py` 合计 45 passed；`scripts/check_action_pinning.py` exit=0；`docker compose config --quiet` 通过）；Phase 7「收尾与全量验证」T054–T058 ✅（`deploy/tests/test_performance_us7.py` 7 条：口令校验 p95（PBKDF2-100k）、完整登录链路 p95（哈希+令牌+序列化）、JWT 解码与拒绝 p95、CORS 预检与拒绝 p95，阈值设为目标 2 倍以吸收 CI 抖动，作用是回归检测；新增 `docs/security/SECURITY_CONFIGURATION.md`：8 个子域（令牌/超时/CORS/审计/调试/加密/TLS）每项含默认值+范围+说明，附配置验证脚本；QF 基线自检：022 覆盖 17 个 QF 条目（P0 4 + P1 13），QF-634 SSO 换票→T030、QF-637 GET 无副作用→T032、QF-635 CORS→T033/T034、QF-650/652/654/656 密钥权限与加密→T003/T038/T039、QF-655 静态加密→T038/T039、QF-561 服务身份→T028、QF-674/676 审计防篡改+库分离→T044、QF-703 安全公告→T051、QF-712 全链路加密→T036/T037、QF-714 Cookie 安全→T036 nginx、QF-679 依赖扫描→T046、QF-681/682/702 漏洞政策→T051/T052；QF-707/QF-710（备份加密/灾备演练）与 QF-660/QF-662（响应权限裁剪/非生产脱敏）已全部关闭（见 QF 关闭轮次）；quickstart 验证清单 22→28 项，测试命令含 US6/US7 + 供应链门禁；WORK_LOG 每 Phase 均已记录；验证：US3–US7 集成测试合计 104 passed；check_action_pinning.py exit=0；check-secrets.sh --all 通过）；**022 全部 7 Phase（T001–T058）完成**

> 注：「本轮补齐」= 2026-09 SDD 补全轮。clarify 消解记录位置说明：001/002/007–011 在 spec 的 "Clarify 记录" 节，012–019 在 plan 的 "Open Questions（已 clarify 消解）" 节，020 与 022 在 tasks.md 的 "Clarify Decisions" 节。**023–026 的 clarify 仍待补**（其 checklist 已标出 023 有 8 个 OQ、024/025/026 的待澄清项，需 `/speckit-clarify` 消解后方可进入 implement）。
