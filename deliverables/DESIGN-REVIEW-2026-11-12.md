# 通用设计复审报告 — 业务流 / 数据流 / 审批流

**日期**：2026-11-12 09:52–10:xx CST
**代码基线**：`main` @ `c5315231`（`docs: 补入 MongoDB ↔ 远端 PanWeiDB 数据差异比对报告`）
**工作区基线**：`git status --porcelain` 仅 3 个未跟踪项（`artifacts/`、`scripts/rebuild_servebay_indexes.py`、`scripts/sync_mongo_to_servebay.py`），**无已跟踪文件改动**，本轮不触碰它们。
**复审性质**：静态只读。四维度并行代码勘察 + 主会话对高危项逐行复核。**未运行 pytest、未连接生产库、未做浏览器验收、未修改任何代码**。
**标记**：★ = 主会话已打开源码逐行核实；未标记项来自代码勘察，结论方向可信但建议落回归用例时再校验一次。

---

## 0. 复审口径：与既往 QA 审计的区别

`deliverables/QA-AUDIT-STANDARD-2026-11-11.md` 与 `specs/INDEX.md` 的口径是**文档齐备度 + tasks 勾选率**（54 特性、五件套 54/54、`1681/1696 = 99.12%`、50 个特性 100% 勾选）。本次复审**不核对勾选**，只问三件事：

1. **链路是否闭合**——从真实入口到真实执行体，中间有没有断掉的接线；
2. **通用设计是否只有一个内核**——同一语义（审批、主键、配额、错误码、fail-closed）是否只有一份权威实现；
3. **设计声称与代码实况是否一致**——spec/契约写「已落地」「统一」「fail-closed」，代码是否兑现。

**结论先行**：规约层几乎全绿，但运行链路层存在**三处结构性断链**与**一类系统性缺省放行**。文档完成度高的特性（尤其 050 / 052）恰恰是链路最不闭合的特性。二者不矛盾，但**勾选率不能替代链路闭合性验收**。

| 级别 | 条数 | 含义 |
|---|---|---|
| **P0** | 2 | 生产链路不可用，且会造成不可逆状态 |
| **P1** | 10 | 设计缺陷 / 数据面风险，需本迭代处理 |
| **P2** | 5 | 设计债与文档口径，需收敛但不阻断 |

---

## 1. 审批流（最高危维度）

### P0-1 ★ 审批决策在真实 DB 语义下必然抛错，且先不可逆删除待办

**证据**：
- `services/chat-api/app/orchestration/run_store.py:187-201` `claim_pending()` 用 `find_one_and_update(..., return_document=True)` 执行 `$unset: {pending_approvals.<node_id>}`，随后从**返回文档**里取 `todo`。
- `services/admin-api/app/core/pg_compat.py:1873,2083-2096` `_return_after(True) -> True` → 返回**更新后**文档；motor/pymongo 的 `ReturnDocument.AFTER` 同义。两个后端都是 AFTER，字段已被 `$unset`，`todo` 恒为 `None` → 抛 `RunStoreError("待办不存在或已被消费")`。
- `services/chat-api/app/orchestration/human_approval.py:358` `decide()` 调用 `claim_pending()` 后继续签发/消费票据，该异常会中断整个决策流程。
- `services/chat-api/tests/orchestration/fixtures/memory_db.py:131-139` 的 fake 忽略 `return_document`、恒返回更新前快照 → `test_run_store.py:91` 假绿。

**比「决策失败」更严重的是副作用**：`$unset` 已落库，运行仍停在 `awaiting_approval`，但 `list_todos()`（`:263`）与 `scan_timeouts()`（`:313`）都看不到该待办 → 运行成为**既不可决策、也不超时、也不可改派的僵尸**。
另 `run_store.py:237-238` 注释写「`find_one_and_update` 在 motor 返回 pre-update」，与同文件 `:194` 的 `return_document=True` 自相矛盾，是这条 bug 的认知来源。

**建议**：改为 `return_document=False`（BEFORE）取回 todo 再原子消费，或把消费改为带 `revision` 条件更新并返回消费前快照；**必须用真实 motor + 真实 pg_compat 各写一条回归用例替换 fake**，用例断言「决策成功后待办消失、失败时待办仍在」。

### P0-2 ★ 050 审批链路整体未接线：UI、执行体、调度三头断

| 断点 | 证据 | 实况 |
|---|---|---|
| 前端入口 | `apps/` 全量检索 `orchestration-runs` / `/todos` **零匹配**；`apps/user-web/src/api/orchestration.ts` 只做 `/orchestrations` 定义 CRUD | 审批人看不到 SOP 待办、无法提交决策；`RunDriver.decide` 无生产调用方 |
| 节点执行体 | `services/chat-api/app/api/endpoints/orchestration_runs.py:42-62,182,236,310` | `set_run_runner()` 全仓无生产调用方，`effective_runner()` 恒返回 `_declarative_runner`（`echo: True`）。挂起/恢复验证的是空转状态机 |
| 定时调度 | `services/chat-api/app/main.py:534` 仅启动扫一次；常驻循环只有 receipt GC(60s)、memory decay(3600s)、`ttl_purge_loop`；`orchestration_runs.py:318-336` `recovery_sweep` 只由外部 POST 触发 | 无部署侧定时器时 24h 挂起永不超时、崩溃运行永不 `needs_review`，FR-006 fail-closed 形同虚设。`:335` 注释「定时器会再扫」但代码里没有定时器 |

**设计声称**：050 `spec.md` R-4「站内待办入口是唯一 guaranteed 触达」、R-5、tasks 27/27 勾选、checklist 16/16。
**实况**：R-4 指定的「复用既有审批页数据面」并不存在——唯一审批页 `PortalApprovalPage.vue` 走 `/api/v1/portal/approvals`（037 申领单），与 050 待办是两套数据面。

**建议**：短期二选一——① 补一个最小站内待办/决策页 + 进程内 `recovery_sweep` 定时任务 + 注入真实 runner；② 若定位为「离线能力/案例代码」，则在 050/052 spec 与 INDEX 中把宣称从「已实现」改为「引擎能力已实现，生产接线未交付」，并停发相关验收结论。**不要继续维持现状口径**。

### P1-1 ★ 审批不是「一个内核」，而是三套状态机 + 三处待办 + 两套身份口径

- 001 进程内票据：`services/chat-api/app/governance/approval_runtime.py:25-100`（used/denied dict）
- admin 侧审批层：`services/admin-api/app/governance/layers/approval.py:46-199`（`gate_approvals`，pending→approved→consumed、`token_hash`、036 双人复核）；`:173-180` 已把一步式 `validate_and_consume` 判为「no human approver」废弃，chat-api 却仍用它承载 050 分离语义，靠 `human_approval.py:341-345` 业务层自补
- 037 申领：`services/chat-api/app/services/portal/requests.py:74-79,478-565`（`portal_requests`，applied→granted→revoked）

三处待办端点并存（`orchestration_runs.py:201`、`portal_admin.py:441`、`gatekeeper_internal.py:220`）；037 的 `approver_id`（`requests.py:216-237`）与 admin 决策端 `PORTAL_APPROVE` 且**不校验 `actor == approver_id`**（`portal_admin.py:463-467,488-490`）是两套身份口径。

**影响**：超时、改派、审计、审批人解析的口径无法统一演进；任何一个治理修复都不能横向复用，且新增审批场景会继续复制第四套。

### P1-2 ★ 取消 / 决策 / 并行分支缺少「同一原子条件更新」仲裁

`run_store.py:294-309` `cancel()` 的 `update_one` 过滤条件只有 `{run_id}`，状态前置判断靠 `get_run()` 读-改-写（TOCTOU）；`:250-257` `set_status()` 无 `revision` 条件；`:203-207` `record_decision()` 无并发保护。`human_approval.py:389-396` 驳回（无 `on_reject`）直接置 `RUN_REJECTED`，不清空其余 `pending_approvals`。

**对照 spec R-13/R-14/R-15**：要求带 `status`/`revision` 前置条件、先落库者胜、驳回优先、禁止双重生效。这些判定序目前只落在文档里。并发下可出现「取消覆盖已生效决策」「终态被覆盖」「一分支驳回而另一分支待办仍在」。

### P1-3 ★ 050 事件未进 001 单一审计汇，审计链只对运行文档自洽

`chat-api/app/` 下 `gate_events` 的写入方有 employees、portal、ontology、session-versioning 等（`app/services/portal/requests.py:46,152-154` 明确写「与 001 同一审计汇」），**orchestration 目录零命中**。050 的 `run.*` / `approval.*` 只 `$push` 进 `orchestration_runs.events[]` / `decision_history[]`（`run_store.py:152-156,203-207,250-257,283-292`）。与 spec R-11「MUST 汇聚进 001 既有审计流、消费方按前缀区分」不符；跨能力对账时 SOP 审批是盲区。

### P1-4 改派出口残缺 + 审批人解析过窄

`run_store.py:277-292` `reassign()` 只 `$set` 改 `approver`，不改状态、不重生成 `resume_token` / `deadline`；`orchestration_runs.py:278,301` `resolve_review` 只收 `("skip","terminate")`，无 `reassign`；三端点均只判 `initiator_id == user`，无 admin 分支；`list_todos` 只查 `awaiting_approval`。审批人离职/停用触发 `needs_review` 后，新审批人看不到待办 → 流程死锁。另 `human_approval.py:343` 要求 `actor_id` 字面等于 `approver`，而 R-1 允许角色型审批人 → 角色型审批人永不可决策。

### P1-5 052「复用 050 审批」在生产默认旁路

`team.py:13-14,347-356`、`dispatch.py:256-266,340-350`：`run_team` 两处调用均不传 `approval_hook`（默认 `None`），注释自认「忽略接管走领导判定」；`RunDriver.start` 硬限 `mode == "graph"`（`human_approval.py:302-305`），`loader.py:375` 拒绝非 graph 审批节点 → 052 的「异步执行与人工接管消费 050 运行持久化」在代码上不成立。这是 052 spec 首期软依赖边界（T015 / R-4），但文档同时写着「硬依赖 050」，口径需要收敛。

---

## 2. 业务流（入口与状态机维度）

### P1-6 ★ 编排是旁挂子系统，不由对话主链路触发

`services/chat-api/app/dsh_runtime/chat_service.py` 全文只有 `prepare_turn`（`:104`），无 orchestration 引用；`/chat/completions` → `require_chat().prepare_turn/stream` → `DshTurnRunner` → 外部 DSH Agent Kernel。`app/orchestration/` 的生产引用只出现在 `orchestration_runs.py`、`orchestrations.py`、`research.py`、`competitor_deep_dive.py`。

**定性**：未必是 bug（编排可能设计为独立研究能力），但它是**入口设计缺口**——010/044/050/052 的七模式、挂起恢复、team 协作对终端主产品不可达，且 spec 将其描述为平台核心执行能力。

### P1-7 ★ 唯一生产编排调用点的 runner 是死代码

`services/chat-api/app/api/endpoints/research.py:84-87` 构造 `runner(node, context)` 并调用 `_default_sub_agent`，但 `:90-98` 的 `orchestrator.run(...)` **没有传它**；`competitor_deep_dive.py:165-174` 的 `create()` 未传 `sub_agents` → `self._sub_agents = {}`；`:246-248` `_run_node` 对每个节点抛 `no sub-agent registered`。结果该端点只能产出 `degraded` 报告，无真实技能执行。

### P1-8 引擎被固化成两套调度循环，新增模式默认不带持久化能力

`human_approval.py:21-24` 注释承认 `PausableDagEngine`「复制 `run_graph` 调度循环」以保六模式 bit-for-bit；`engine.py:40-41` 注明 `AWAITING` 仅子类产出。于是「进程内执行」与「持久化恢复」成为两套状态机：同一调度 bug 需双份维护，044 新增模式、052 team 都落在其中一侧。`app/services/dag/`（skip/retry/builder_migrate）无生产 import，与 `app/orchestration/` 形成第三套来源；`contracts/orchestration.md:11` 仍写四模式，与 `graph.py:13` 的七模式 `VALID_MODES` 不符。

### P1-9 七个模式中五个无生产触发入口

`dispatch.py:8-9` 自称统一分发；唯一生产调用点 `competitor_deep_dive.py:395` 的 YAML 恒为 `mode: graph`（`competitor_deep_dive.yaml:16`），dispatch 自注 supervisor/hybrid「no production call site（044 R-13）」，`run_team` / `run_debate` / `run_round_robin` 仅内部互调。这几模式目前只有单测覆盖。

---

## 3. 数据流（唯一权威来源维度）

### P1-10 ★ 兼容层能力缺口靠「调用点逐个绕开」，无清单、无静态守卫

`services/admin-api/app/core/pg_compat.py:1129` 用 `getattr(self, f"_stage_{name}")` 分派，实际只有 7 个处理器：`_stage_match/sort/limit/skip/count/group/project`（`:1141-1217`）。`$unwind` / `$facet` / `$lookup` / `$replaceRoot` 等一律运行期抛 `PgCompatUnsupported`。

**已有生产事故先例**：2026-11-12 上午 `topic_admission/rules.py` 的 `$unwind + $facet` 管道在 PanWeiDB 后端触发 500，修法是**改调用点为 `find_one` + Python 侧展开**，而非补齐兼容层（见 `.workbuddy-ai/memory/2026-11-12.md`）。全仓仍有 30 余处 `aggregate` 调用点，头部注释（`:30`）把已实现的 `bulk_write` 也列为未覆盖，唯一「清单」在 `tests/test_pg_compat.py:284`。

**影响**：Mongo 下正常、PanWeiDB 下运行期 500，CI 无法提前拦截；「改调用点绕开」会持续放大双后端行为分叉。
**建议**：把支持/不支持的聚合阶段与算子写成可枚举常量清单 + CI 静态扫描（扫描所有 `aggregate` 管道阶段），而不是继续打补丁。

### P1-11 ★ 时间有序 32-hex 主键契约被数十处 `uuid4().hex` 绕过

`services/admin-api/app/core/ids.py:18-20` 明确要求「避免 `uuid4().hex` 导致的顺序倒退」，`hex32_db.py:50` 只在缺 `_id` 时注入有序 ID；但 `skill_lifecycle.py:58,93`、`employees/repository.py:109`、`position_roles/repository.py:170`、`tenant_registry.py:94`、`eval_gate/*.py`、`knowledge_documents.py:810`、`capability_assets/registry.py:356` 等直接写无序 `uuid4().hex`。Mongo 侧 `Hex32Database`、PanWeiDB 侧 `pg_compat.py:93`、迁移脚本另有三套注入实现。

**影响**：凡以 `_id` 作高水位/分页游标的增量采集（审计、成本、事件流）会按字典序跳过「新写入但字典序更小」的记录，且是静默漏数据。需先确认实际使用 `_id > last_id` 游标的消费方清单再定修复范围。

### P1-12 兼容层写语义与 Mongo 不对等，幂等/乐观锁在 PanWeiDB 侧失效

`pg_compat.py:1706,1728,1834`：`ON CONFLICT (id) DO NOTHING` 忽略 rowcount 仍返回成功；`_update` 只刷新映射列，`column_map.py:19` 的 R3 扁平化列与 `doc` 可能分歧。依赖 `DuplicateKeyError` 做幂等/乐观锁的调用点（`rules.py:97`、`tenant_provisioning.py:166`、`directory.py:620` 等 ≥8 处）在 panweidb 后端行为不同。

### P1-13 ★ 用量日志静默丢账，而它是配额/成本/审计的唯一数据源

`services/chat-api/app/token_usage/dispatcher.py:43-55` 队列满直接 `return False`；`:87-93` 持久化异常只 `logger.exception` 后照常 `task_done()`，无重试、无死信、无对账；`:65-69` 扣点失败只记日志。`core/quota_policy.py:167` 按 `token_usage_logs` 聚合计量。

**影响**：成本报表（035/046）、配额扣减（042/049）、审计链同时缺账，且不可察觉。建议加失败计数指标 + 死信队列 + 定期对账。

### P1-14 同一逻辑双副本漂移：配额、价格、租户缺省

- **配额双副本**：`admin-api/app/core/quota_policy.py`（aware UTC、`:396` `points_unlimited` 默认 True）与 `chat-api/app/core/quota_policy.py:58`（`datetime.now(utc).replace(tzinfo=None)` naive UTC、`:398` 额外短路）已实质漂移；`tests/test_quota_consistency.py:38` 只锁返回键，不锁语义。同一租户在管理端与会话端可算出不同周期窗口/不限额结论。
- **租户缺省**：`chat-api/app/core/billing.py:53,78` 对 `tenant_id` 为 `default`/空整段跳过配额校验与扣点；`core/tenant.py:24` 把任意空值归一为 `default`，`tenant_scope_filter` 对 default 用 `$or` 吞入所有无 `tenant_id` 的历史行 → 归属丢失的数据既计入默认租户又不受额度约束。
- **价格表三副本**：`chat-api/app/llm/resilience/pricing.py:3`、`admin-api/api/routes/dashboard.py:40`、`analytics.py:24` 各写一份硬编码 `MODEL_PRICES`，另有 `services/model_pricing.py:39` 的 DB 动态定价完全不参与 `_cost_usd`；`docs/data-dictionary.md` 写 `cost_usd`，实际写 `cost_estimate_usd`。无跨服务一致性测试。

### P1-15 数据模型无单一权威来源；事件流两侧被直接清空

`docs/data-dictionary.md:5,80` 只枚举约 30 个集合，而 `tenant_purge.py`、`column_map.py` 各自维护 90+ 集合与列映射，新增集合无登记入口。`scripts/pg/migrate_ids_to_hex32_panweidb.py:366,424` 与 `scripts/migrate_ids_to_hex32.py:8` 均 `TRUNCATE` 事件流两表，且 verify 断言「事件流为空」；事件溯源历史两侧永久丢失且无回放/重建路径。（这是 11-12 停机窗口的既定决策，此处登记为设计债，非缺陷。）

---

## 4. 横切通用设计

### P1-16 ★ 缺省语义不统一：多处 fail-open 与宪法 fail-closed 冲突

| 位置 | 实况 |
|---|---|
| `admin-api/app/governance/risk.py:141-143` | `_canon()` 注释明写「never deny-by-default for unknowns」→ `return "allow"`；`:123-124,127-128` DB 异常回退 canonical |
| `admin-api/app/topic_admission/service.py:17-18,55` | `mode=off` → `allowed=True` |
| `admin-api/app/ontology_permission/service.py:103,107` | `enforce` 默认 False、`effectiveDefault=allow`（而 `specs/INDEX.md:149` 宣称「enforce=true 时缺省固定 deny」） |
| `chat-api/app/im_gateway/bindings.py:269-273` | `db is None` / `row is None` 均 `return True`，`im_gateway.py:69-71` 自认 fail-open |

对照 `.specify/memory/constitution.md` 原则 III、009 `spec.md:112-113`「超时/异常/规则解析失败一律 fail_closed」、020 spec「一律拒绝，不回退默认租户」。**这些不是主路径漏洞，但「未配置 / 未知 / 存储异常」三类旁路缺乏跨服务统一的、可机检的约束**，新增治理点会继续各写各的缺省值。

### P1-17 契约双权威且互相冲突

- `docs/error-codes.md:3` 自称「唯一权威字典」：`api.*` 小写 15 码、配额 429、`fields[]`/`error_detail`；
- `docs/api-specification.md:51-80`：`VALIDATION_ERROR` 大写、`details`/`request_id`、配额 402 `PAYMENT_REQUIRED`，且仍带「当前行为忽略 Accept 头」「QF-225 修复计划」等旧态描述。

`specs/INDEX.md:96` 宣称 025 52/52「错误码统一结构落地」，但消费方仍无唯一契约。`docs/api-versioning.md:28` 称三服务同型，实际 `ApiVersionMiddleware` 只在 `admin-api/app/main.py:172` 注册（全仓仅一份 `api_version.py`），chat-api / document-parser 只注册 `LegacyApiRedirectMiddleware`。

### P2-1 `specs/INDEX.md` 自身口径互斥，完成度不可复现

`:21,192,332` 写 032–044「代码尚未开工、tasks 全部未勾选」，`:263,266` 写「全部落地 / 100% 闭合」；`:333` 自列「050 R-9 实现侧未兑现」「052 真挂起二期」「053 clarify 残留」「3000 反代」，`:350` 同时给出 1681/1696、50 个 100%。同一文档并存多轮历史快照且未标注废弃，是「文档全绿掩盖接线缺口」的直接来源。

### P2-2 常量与版本多副本

`DEFAULT_TTL_SECONDS = 300.0` 至少 5 份（`services/common/cache_manager.py:23`、`cache_policies.py:17`、`admin-api/app/cache/manager.py:23`、`policies.py:17`、`chat-api/app/cache/policies.py:17`）；`IDLE_TIMEOUT_SECONDS` 两份。契约 `specs/025…/contracts/admin-api.yaml:2` 与 `api_version.py:24` 为 `1.0.0`，OpenAPI `info.version` 为 `0.2.8`，而 `INDEX.md:352` 称「7 处版本来源全部 0.2.8」——漏统计一套。

### P2-3 契约文档滞后

`contracts/orchestration.md:11` 仍描述四模式与 `app/services/dag/` 接口，与 `graph.py:13` 七模式不符；050 FR-010 补的 §6 是「只增不改」，导致同一文档新旧两层语义并存。

### P2-4 附带安全项（已知、部分已处置，非本轮结构性发现）

`docs/pending-review/03-secrets.yaml.real-secrets` 含明文私钥与生产口令、`deploy/production/deploy-remote.sh:71` 有弱口令默认值、`.env` 曾入库（历史提交 `3d728ee2`）。11-12 已补 `.gitignore` 规则使敏感文件与 5.4G 中间物不再出现于 `git status`，但**历史中的凭据不可撤回**，建议并行做凭据轮换，不列入本次设计复审整改主线。

---

## 5. 整改路线（按依赖顺序）

**当天（P0，止血）**
1. 修 `claim_pending` 的 `return_document` 语义；用真实 motor + 真实 pg_compat 各补一条「成功消费 / 失败不丢待办」回归用例替换 fake。**这是唯一会破坏数据的 bug，优先于一切文档修订。**
2. 对 050 做口径决策：补前端待办页 + 进程内 `recovery_sweep` 循环 + 注入真实 runner；或把 050/052 从「已实现」改标为「引擎能力已实现，生产接线未交付」。二选一，不要维持现状。

**本迭代（P1，收敛为单一内核）**
3. 把审批收敛为**一个内核**：统一票据/待办查询/审计出口（`gate_events`）/审批人解析；补 `revision` 原子条件更新仲裁（取消、决策、超时、驳回优先）；补 `reassign` 到 `resolve_review`。
4. 给 `pg_compat` 建**可枚举能力清单** + CI 静态扫描 `aggregate` 管道阶段，禁止「调用点逐个绕开」继续扩散；同时修 `ON CONFLICT DO NOTHING` 与 R3 双写幂等语义。
5. 统一 ID 生成器（禁业务层直接写 `uuid4().hex`）与用量日志失败可观测性（重试/死信/对账指标）。
6. 合并配额、价格、常量的双/多副本到单一模块，双服务以 import 而非复制共享；统一 `tenant_id` 缺省为拒绝而非 `default` 放行。
7. 把「异常/未知/未配置一律拒绝」写成跨三服务可机检约束（CI 静态门禁 + 统一缺省常量），并同步修订两份 API 权威文档、补 `API-Version` 中间件到另两个服务。

**设计债（P2）**
8. `specs/INDEX.md` 改为「单一当前态 + 历史快照附录」；`contracts/orchestration.md` 按七模式重写；`docs/data-dictionary.md` 与 `column_map.py` / `tenant_purge.py` 合并为可生成清单；补事件流历史重建/回放路径。

---

## 6. 复审局限

- 全程静态只读，**未执行任何测试**，所有结论为代码语义推断；P0-1 虽已逐行核实两个后端的 `return_document` 语义，仍建议以真实 DB 回归用例最终确认。
- 未连接远端 PanWeiDB / k3s 生产栈，未验证部署侧是否额外配了 `recovery-sweep` 定时器（若已配，P0-2 的第三项可降级）。
- 未逐一复核 P1-12 / P1-14 价格表、P1-15 数据字典等条目的全部调用点，落整改前请按证据路径再核一次。
- 本次结论针对 `c5315231`；工作区有其它会话在途的未跟踪文件，均未纳入复审。

---

## 7. 决议与执行记录（2026-11-12）

用户确认：**050 口径选「改宣称标注」**、**本轮范围只做 P0**；本迭代四项（审批单一内核、兼容层能力清单 + CI 静态扫描、统一 ID/配额/价格来源、异常未知一律拒绝的机检约束）拆为后续独立批次。

### P0-1 已修：`claim_pending` 的 BEFORE/AFTER 语义

- `services/chat-api/app/orchestration/run_store.py`：`claim_pending()` 由 `return_document=True` 改为 **`False`**（取更新前文档再原子消费），并补充 docstring 说明为何 AFTER 会造成「`$unset` 已落库但取不到 todo」的僵尸运行；`resume()` 里把 motor 返回 pre-update 的错误注释改为不依赖 BEFORE/AFTER 的正确描述。
- `services/chat-api/tests/orchestration/fixtures/memory_db.py`：`FakeCollection.find_one_and_update()` 不再是「恒返回更新前快照」的错误替身，改为忠实实现 `return_document`（默认 `False` = BEFORE，对齐 pymongo），从根上消除假绿。
- 新增 `services/chat-api/tests/orchestration/test_run_store_real_backends.py`：真实 motor（`real_mongo_db` 夹具，独立测试库）+ 真实 `app.core.pg_compat.PgDatabase`（独立 schema，teardown `DROP SCHEMA`）各一条 `claim_pending` 回归用例，另加一条纯逻辑用例锁死 fake 的 BEFORE/AFTER 语义。后端不可达时各自 skip，不伪造通过。

**验证**（本地 27017 Mongo + 临时 PostgreSQL 18.6 @ 55432，独立库/独立 schema，未碰任何开发或生产数据）：

```
tests/orchestration/test_run_store_real_backends.py + test_run_store.py → 12 passed
tests/orchestration/（全量）                                          → 201 passed
```

### P0-2 口径决议与同日后续变更

- **上午决议**：用户选「改宣称标注」，本会话把 050/052 spec 与 `specs/INDEX.md` 的性质说明改为 **「引擎能力已实现，生产接线未交付」**，逐条列明三项接线缺口；052 另更正「复用 050 审批节点跨模式挂起」在代码上不成立。
- **同日后续变更**：用户在并行会话改选「补齐生产接线」，并已交付最小闭环 —— user-web 站内审批待办/决策页（`ApprovalTodosPage.vue` + `api/orchestrationRuns.ts`）、`orchestration/production_runner.py` 经 LocalBridge 派发节点技能（无会话/未连接时诚实降级、不伪造输出）、`app/main.py` 启动时注入 runner + 60s 常驻恢复扫描；验收 `tests/orchestration/` **206 passed**（接线会话）/ 提交前真实 motor + 真实 pg_compat 复核 **207 passed**、user-web `vue-tsc` 0 错误。050 spec 性质说明已由该会话同步改为「生产接线最小闭环已交付」。
- **提交前口径统一（本会话）**：把 `specs/INDEX.md`、`specs/052-team-collaboration-mode/spec.md` 与本报告同步到上述事实，避免仓库内 050 spec 与其余文档互斥。050 最终口径 **「引擎能力已实现，生产接线最小闭环已交付」**；052 最终口径 **「引擎能力已实现，跨模式挂起未交付」**。画布「运行」按钮仍缺，运行经 API 发起，列为后续项。
- **报告正文 §0–§6 为上午复审当时的静态结论**，保留原文留档；接线补齐后的实况以本节与 050 spec ⑤ 为准。

### 仍未做（后续批次）

审批单一内核与 `revision` 原子仲裁、`pg_compat` 能力清单 + CI 静态扫描、统一 ID/配额/价格单一来源、跨服务 fail-closed 可机检约束、052 跨模式挂起、画布「运行」按钮。
