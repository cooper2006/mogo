# SDD 增强功能核验报告（主线一 / 主线二 / 2 案例）

> 核验日期：2026-09-25 · 核验人：DSH Agent
> 复核（2026-09-26 round 2）：接线回归全绿 + DSH 升级契约 5/5 + 多实例 sticky 路由核实；结论不变。
> 核验范围：README「主线一：spec-kit SDD」+「主线二：企业级功能补强（P0/P1/P2 共 15 项）」+「2 个案例」，对照 `docs/SDD界面呈现对照表.md` 与 `specs/001–019`。
> 方法：机械核验（文件树 / 勾选统计 / 阈值 grep）+ 子代理深入分块 + 全量测试实跑。未修改任何源码/规格文件（本条目除外）。

## 0. 结论速览

| 维度 | 结论 |
|---|---|
| 测试证据 | 两案例 **40 passed**（case1 15 + case2 25）+ 接线层 56 项 + 007 韧性 45 项 + DSH 契约 5/5 全绿；已知失败均为环境依赖（无 Node ≥22.19 / real_dsh 网关），非回归 |
| 主线一 SDD 骨架 | ✅ 真实落地（.specify/ 完整、19/19 spec+plan+checklist、15 份 tasks.md 100% 勾选） |
| 主线二 P0/P1/P2 | ✅ 库代码 + 单测全部达标；007/009/002/001 运行时接线与 UI 触点、T999 业务调用点**已全部落地**（pending-review 5 条 resolved，2026-09-25 生产接线轮）；仅 001 FR-11「不新建审批表」spec 偏离已由用户拍板接受并修订 spec |
| 2 个案例 | ✅ 全落地（Skill 资源齐全、YAML 落地、AC↔test 一一映射、离线可跑） |
| 文档精度 | ⚠️ 若干声明与实际存在偏差（详见 §4），多为文档表述不精确，非功能性缺失 |

---

## 1. 主线一：spec-kit SDD 开发规范

**真实落地（✅）**
- `.specify/` 骨架完整：`memory/constitution.md`（含 Agent 操作规则 14 条 / 工作区与删除边界 / 质量门禁 SDD 流程 + /speckit-checklist + /speckit-analyze）、`templates/`（5 模板）、`scripts/bash/`（6 脚本）、`workflows/speckit/workflow.yml` + `workflow-registry.json`、`integrations/`。
- 19/19 特性均有 `spec.md` + `plan.md` + `checklists/requirements.md`。
- **15 份存在的 tasks.md 全部 100% 勾选（合计 260 项）**；003–006（既有回溯规约）无 tasks.md，INDEX.md 已自证说明。
- checklist 勾选：001/002/007–019 共 15 份 100% 勾选；003–006 保留原始未勾状态（INDEX.md 第 54 行明确）。
- 抽查 001/010 spec.md 内容详实（各 5 US / 11–12 FR + Clarify 消解记录），非空壳。
- 顶层 `contracts/` 5 份（T998 契约：orchestration / self-evolution / session-versioning / harness-config / a2a-gateway）+ 4 个 spec 内 `contracts/`（001/007/008/009）。

**偏差（⚠️，文档表述不精确，非功能缺失）**
1. README「All 19 features have every task checked off」把 003–006 计入；实际 **15/19** 有 tasks.md，003–006 无。
2. README「每个特性含 contracts/」夸大成 19/19；实际仅 **9/19** 有契约件（4 个 spec 内 + 5 份顶层），10 个特性（003/004/005/006/013/014/015/016/017/018）无。
3. 文件名：README 写 `checklist.md`，实际是 `checklists/requirements.md`。
4. INDEX.md 第 55 行「tasks 001–019 全部完成（19/19）」与实际 15/19 不符（INDEX 自相矛盾）；第 57 行「各 spec 新增 Clarify 记录节」实际仅 001/002/007–011（7 份）有该**标题节**，012–019 的 clarify 消解放在 `plan.md` 的「Open Questions（已 clarify 消解）」节（位置不一致，但消解本身 15/19 完成）。

---

## 2. 主线二：企业级功能补强（P0/P1/P2）

**测试全绿证据**
- chat-api：1562 passed（排除预存坏例 `tests/llm/test_decision_turn.py` 与 dsh_runtime e2e 目录）。
- admin-api：236 passed（与 SDD 对照表「admin-api 236 项」完全一致）。
- P0/P1 专项 359 项（chat 233 + admin 126）全过；P2 专项 262 项全过。

**逐特性核验（✅ 库代码 + 单测达标；❌/⚠️ 为接线层缺口）**

| 特性 | 状态 | 关键证据 | 缺口 |
|---|---|---|---|
| 001 门禁治理 | ✅ 库/⚠️ 接线 | 六层串行链 identity→rbac→redaction→approval→quota→audit（短路 + audit 层总是执行 FR-9）；R4 三层保险（matrix 全 R4=deny / risk.py 读库前硬 deny / 路由 400）；PII 四策略齐全；RBAC 三段式权限码 | chat-api 侧 `gate_adapter.py` 注释「001 gatekeeper is not yet wired（clarify OQ-3）」，运行时工具调用走 chat-api 自有 governance；**001 FR-11 偏离**：spec 要求「复用不新建审批表」，实现自建 `gate_approvals` 集合 |
| 007 网关韧性 | ✅ 库/⚠️ 接线 | 降级链耗尽抛 `DegradationError` 不静默；401/403 立即中止；tenacity 指数退避 1.5s/30s/±10%/3 次；`MODEL_PRICES` 成本计量 | **failover/降级/退避库代码与 39 项单测齐全，但生产 `InstrumentedLLMClient` 仅用 `estimate_cost`，无 failover/降级调用点**；真实 LLM 调用不触发韧性（唯一复用点在 `a2a/client.py` 的 `run_with_retry`） |
| 008 驾驶舱 | ✅ 实现 | `routes/dashboard.py::overview()` 九段齐备（含四维）；`DashboardPage.vue` 五标签页 overview/cost/usage/quality/trend 齐备；40 项测试过 | 无 |
| 009 钩子拦截 | ✅ 库/⚠️ 接线 | 三规则 deny/require/observe；tool>session>tenant；5s 延迟预算 + fail-closed；五事件；001 审计落点；43 项测试过 | **引擎未被运行时挂载（`turn_admission.py` 未 import hooks，engine 全仓零调用点）；admin-web 无钩子规则页（SDD 声称有）** |
| 010 DAG 编排 | ✅ 实现 | 四模式 graph/sequential/supervisor/hybrid；拓扑 + 环检测（`A→B→C→A`）；条件跳过三态 fail-closed；节点指数退避；102 项测试过 | 无（生产接线：`competitor_deep_dive.py` + `a2a/client.py`） |
| 002 会话/工作流版本化 | ✅ 库/⚠️ 暴露 | commit 线性时间线 + 乐观锁；share 一次性 300s TTL + 过期/撤销/已兑换空态；co-presence Mongo 心跳无 Redis；工作流定义版本化；49 项测试过 | **`session_versioning` 包零外部引用、无 HTTP 端点、无前端 UI** |
| 011 Dream 自进化 | ✅ 实现 | Jaccard≥0.7 / 样本≥5 / 14d / ≥20 曝光 / <10% 采纳 阈值全部与 spec 一致；32 项测试过 | 无 |
| 012 A2A 网关 | ✅ 实现 | 30s 超时 / JSON-RPC 三方法 / `-32000` 治理拒绝短路 / 幂等 task id；31 项测试过 | 无 |
| 013 多 IM 入口 | ✅ 实现 | ChannelRouter 注册/启用/停用 + 会话-渠道绑定 + webhook HMAC + 300s 防重放；32 项测试过 | 无 |
| 014 业务语义索引 | ✅ 实现 | 实体指针索引（read_only 绝不写业务库）+ citation 锚点 `type:id#chunk`；测试过 | 无 |
| 015 知识图谱 | ✅ 实现 | 节点/边 + 多跳遍历 CycleGuard（默认 3 跳）+ 互斥/传递/基数约束标记不阻断；测试过 | 无 |
| 016 Skill 市场加固 | ✅ 实现 | 效果打分 0.5/0.3/0.2 + 低质 0.4 持续 7d + 灰度 20% 回滚/20 样本；**与 011 共用 `marked_low_quality` 位（grep 确认两侧同键）** | 无 |
| 017 三域记忆 | ✅ 实现 | personal/workspace/org + 升级授权 `full_access_admin` + 30d 衰减 + scope 过滤 RAG 排序；测试过 | 无 |
| 018 能力资产注册 | ✅ 实现 | 四段契约 input/output/errors/sla + 扫描去重 + 治理视图 + `a2a_exposed` 标记；测试过 | 无 |
| 019 Harness 弹性配置 | ✅ 实现 | scene>tenant>tool 覆盖链 + 层开关 + **R4 恒 deny 合规底线（`r4_always_denied`/`assert_floor_intact`）**；测试过 | 019 接入 001 走过渡适配器（gate_adapter），因 001 运行时未接线 |

**横切发现**
- **011/016 共用 `marked_low_quality` 标记位 — ✅ 成立**（deprecation.py 与 scoring.py 同字符串键）。
- **T999 审计 — ⚠️ 框架就绪、生产未接线**：`feature_audit.py` 事件族覆盖 012/014/015/016/017/018，`im_gateway/audit.py` 覆盖 013，`evolution_audit.py` 覆盖 011，sink 接口 + 测试完整；但**全部业务代码（friction/mr/runner/router/webhook/kg/memory/capability_assets/skill_lifecycle）无任何一处调用 `record_feature_event`/`record_im_event`/`audit_capture` 等**，审计 helper 仅被定义与单测，生产层未接入 001 落点。

**文档路径精度偏差（⚠️，非功能缺失）**
- `instrumented_client.py` 实际在 `chat-api/app/llm/`（非 SDD 所述 `llm/resilience/`）。
- `dashboard_usage.py` 实际在 `admin-api/app/api/`；`app/api/dashboard_metrics.py` 是 SDD 完全未提及的模块。
- 001 FR-11 引用的 `EnterpriseApproval` 实际在 `enterprise_capabilities/tools/contracts.py:56`，非 FR 所述路径。
- 010 编排包还有 SDD 漏列的 `loader.py`（YAML 加载器，案例二依赖）。
- SDD 数字：`tests/llm/` 韧性实际 **39 项**（25+14），SDD 写 47 项。

---

## 3. 2 个案例

**案例一：客户反馈智能分诊（单智能体）— ✅ 全落地**
- Skill 资源齐全：`skills_specs/customer_feedback_triage/` 含 `SKILL.md`（frontmatter 同时声明 `name: customer_feedback_triage` 内置 id + `packageName: customer-feedback-triage` 可安装包名，满足 docs/cases/README.md 双命名约束）、`templates/triage_report.md`、`templates/action_items.csv`、`scripts/severity_heuristics.py`、`validation.yaml`。
- 运行时 `app/cases/customer_feedback_triage.py`（`run_triage` / `DefaultPiiRedactor` / `P0_APPROVAL_THRESHOLD`）。
- `validation.yaml` 把 §6 的 AC-1..AC-8 **一一映射到具体测试函数名**（契约不可静默漂移）。
- 测试 `tests/cases/test_customer_feedback_triage.py` **15 项全过**：500 条预算内 / P0 召回 / PII 零泄漏 / 可逆占位 / 审批触发与不触发 / token 成本 / 审计完整 / commit 后可 resume / skill 包过 validator / 必需章节 / CSV 可解析 / 去重 / validation.yaml 映射完整。

**案例二：竞品深度调研（多智能体 DAG graph）— ✅ 全落地**
- 编排 YAML 落地 `app/enterprise_capabilities/research/orchestrations/competitor_deep_dive.yaml`：4 个分析节点并行 + report_synthesis 等待全部；`financial_analysis` 条件跳过（私有公司）；`report_synthesis` 条件跳过（<3 子节点完成→降级报告）；`data_contract` 上游 output_key 传递；`failure_propagation` + `audit` 声明。由 `orchestration/loader.py` 加载并 `OrchestrationDefinition.validate()` 校验拓扑 + 条件语法。
- 5 个子 Skill 全部存在：market_intelligence_v1 / product_analysis_v1 / financial_analysis_v1 / sentiment_monitor_v1 / report_synthesis_v1（+ 风格约束 deep_research_report_style_v1）。
- 测试 `tests/orchestration/test_competitor_deep_dive.py` **25 项全过**：并行执行 / 总耗时预算 / 环检测拒绝 / 私有跳过财务 / 跳过极性 / 节点重试 + 指数退避 + 2 次 attempt 事件 / 合成跳过/执行 / 证据可追溯 + 反向查 / 风格契约 / 成本按 node 可查 / commit-share-resume / YAML 加载校验 / 数据契约匹配 / 失败传播+审计 / 编译拒绝不支持语法 / 子 Skill 声明 subagent 契约 / 降级报告点名跳过节点。

**离线声明核验**：两案例测试均离线可跑（LLM 边界用 FakeNarrator、PII 用确定性本地 redactor、table 输入喂 records；grep 确认无网络/LLM 调用），与 README「cover by end-to-end tests that need neither an external LLM nor network access」一致。

---

## 4. 偏差项总览（按严重度）

**功能性缺口（若 README「implemented」按「已接入生产路径」理解则不成立）**
1. 007 网关韧性 — failover/降级/退避**零生产调用点**，真实 LLM 调用不触发。
2. 009 钩子拦截 — 引擎**零生产调用点**、未挂载运行时；admin-web 无钩子规则页。
3. 002 会话版本化 — `session_versioning` 包**零引用、无端点、无 UI**。
4. 001 六层门禁 — chat-api 运行时侧未接线（gate_adapter 注释自认「not yet wired」），工具调用走 chat-api 自有 governance。
5. 001 FR-11 — 自建 `gate_approvals` 集合，未遵守 spec「不新建审批表」。
6. T999 审计 — 框架完整但生产业务代码未接线。

**文档表述不精确（README/SDD/INDEX 声明 vs 实际）**
- 主线一：tasks 15/19（非 19/19）；contracts 9/19（非 19/19）；checklist 文件名；clarify 记录位置 P1/P2 不一致；INDEX.md 自相矛盾。
- 路径精度：instrumented_client / dashboard_usage / dashboard_metrics / EnterpriseApproval / 010 loader.py。
- 数字：`tests/llm/` 韧性 39 项（非 47）。

**未发现任何「声明存在但代码/测试完全缺失」的硬缺口** —— 15 项能力的库代码与单测全部真实存在且全绿；缺口集中在「生产接线」与「文档精度」两层。

## 5. 建议与处置状态（2026-09-25 更新）

**文档精度修正 — ✅ 已执行**（用户确认订正后）：
1. README（EN/ZH）：「All 19 features have every task checked off」改为「15 份 tasks.md（260 项）全部勾选，003–006 既有回溯无 tasks.md」；「每个特性含 contracts/」改为「顶层 5 份 T998 契约 + 4 个 spec 内契约（9/19 特性有契约件）」；`checklist.md` 改为 `checklists/requirements.md`；15 项能力的「已实现」表述加「库代码 + 单测」口径说明并指向 SDD 对照表 §4 接线状态。
2. `docs/SDD界面呈现对照表.md`：007 测试数 47→39；007/008/010 代码路径订正（instrumented_client 在 `app/llm/`；dashboard_usage/metrics 在 `app/api/`；DashboardPage 在 `src/views/dashboard/`；补列 `loader.py`）；§0 增加「实现 vs 接线」口径说明（001/007/009/002 库能力已落地 + 生产接线后续，011/016 共用位与 T999 未接线注明）；§2.1/§2.2 加 002/009 接线状态注；§1.1 加 001 FR-11 偏差注；§4 加接线状态补充。
3. `specs/INDEX.md`：第 55 行 tasks「19/19」改为「15 份全部完成（003–006 无 tasks.md）」；第 57 行 clarify「19 份」改为「15 份已消解，003–006 未做；记录位置 001/002/007–011 在 spec、012–019 在 plan」；§六 路径表与统计节对齐（003–006「无 tasks.md 保留原始状态」、P2「tasks ✅ 15 份之一」）。

**生产接线 / spec 偏离 — ⏸ 待用户拍板，已登记 `docs/pending-review/index.md`（5 条 open）**：
1. 007 网关韧性生产挂载（instrumented_client 接入 failover/降级/退避，或维持库能力并标注）。
2. 009 钩子引擎挂载 turn_admission + admin-web 钩子规则页。
3. 002 session_versioning 端点 + user-web 会话页 UI。
4. 001 chat-api 侧切 001 Gatekeeper + FR-11 二选一（接受 `gate_approvals` 自建表 / 复用 `EnterpriseApproval`）。
5. T999 审计业务模块接入 001 落点 + 端到端测试。

另注：`docs/企业级智能体功能补强规划.md` §六「落地进展」表含同类口径表述（spec/plan/checklist/tasks/clarify 19/19 齐全），**已在 2026-09-25 随本轮遗留项收尾订正**：第 187 行改为「spec/plan/checklist 19/19；tasks.md 15 份全部勾选（003–006 无 tasks.md）；clarify 消解 15 份」；第 194 行 007 测试数 47→39。

- 未改 services 源码；本文件仅在 `specs/019-harness-elastic-config/` 下。

## 复核（2026-09-26 round 2）

**任务**：对当前工作区（含 2026-09-25 后未提交的接线/品牌改动）重新核验「README 描述的增强功能是否符合 SDD 规范」，确认 2026-09-25 round 1 的结论仍然成立。

**方法**：逐项实测而非复述 —— 勾选统计（grep）、文件存在性检查、调用链 grep、关键测试实跑。

**证据**：

| 核验点 | 结果 |
|---|---|
| SDD 骨架 | `.specify/` 完整；19/19 spec + 19/19 plan；checklist 15 份代审 100%（003–006 保留原始未勾，INDEX 已声明）；15 份 tasks.md 全部勾选，合计 **270 项**（grep 实测，未勾选项 0） |
| contracts | 顶层 `contracts/` 5 份 T998 + 4 份 spec 内（001/007/008/009），共 9/19 特性有契约件 —— 与 README L72 口径一致 |
| 001 FR-11 拍板 | `specs/001-gatekeeper-governance/spec.md` L99/L145 已修订为「复用既有审批状态机（EnterpriseApproval 或自建 gate_approvals），不新建第二张审批表」，与 pending-review 台账 resolved 一致 |
| 007 生产接线 | `llm/configured_models.py:371/376` `get_llm_client_by_model_id` 构造 `ResilientLLMClient` ✅ |
| 009 挂载 + UI | `turn_admission.run_pre_tool_use` 挂载 ✅；`dsh_chat.py:188` / `dsh_execution.py:53` 传 `tool="dsh_turn"` ✅；admin-web 路由 `/hooks/rules`（`routes.ts:155-158`）→ `views/hooks/HookRulesPage.vue` + `api/dsh_hooks.ts` ✅ |
| 002 端点 + UI | `dsh_session_versioning.py` 6 端点（commit/versions/share/redeem/revoke/co-presence）✅；user-web `SessionVersioningDrawer.vue` + `api/sessionVersioning.ts` ✅ |
| T999 业务调用点 | `feature_audit_bridge.py` 落地；`emit_feature_event` 实查到 012 `a2a/client.py`、014 `business_index/entities.py`、015 `knowledge_graph/{store,consistency}.py`、017 `memory/scope.py`、018 `capability_assets.py`、016 admin-api `skill_market/scoring.py` ✅ |
| 多实例 sticky | `docker-compose.yml` L151-215 三 replica + nginx 一致哈希 LB；测试 `tests/dsh_runtime/test_multi_host_transport.py` + `test_gateway_step2.py` ✅ |
| 两案例 | 实跑 **40 passed**（case1 15 + case2 25，离线无 LLM/网络） |
| 接线层单测 | T999 bridge 18 / 002 session 8 / 007 wiring 6 / 009 hooks 17 / hooks_wiring 7 —— 全绿 |
| 007 韧性系列 | `tests/llm/` resilience 3 文件 **45 passed**（test_resilience 25 + metering 14 + wiring 6） |
| DSH 升级契约 | `test_dsh_upgrade_contract.py` **5/5**（matrix 0.1.7-rc.2 与 package.json 钉版一致） |

**已知失败（非回归）**：`tests/dsh_runtime/conversation_regression/` 3 项因本机无 Node ≥22.19 而 fail（harness 自检跳过），属环境依赖，与接线改动无关；`real_dsh` e2e 超时为既有基线同类失败。

**结论（不变）**：README 描述的增强功能**符合 SDD 规范** —— 每项增强均有对应 spec/plan/checklist/tasks 资产与测试证据；生产接线（001/007/009/002）与 UI 触点（钩子规则页、会话版本化抽屉）已闭合；pending-review 5 条全部 resolved。

**一处口径修正**：报告 §0 与 README L72「260 项」为旧数；grep 实测 15 份 tasks.md 勾选合计 **270 项**（001×32 / 002×22 / 007×25 / 008×27 / 009×19 / 010×22 / 011×19 / 012×12 / 013×12 / 014×13 / 015×12 / 016×13 / 017×13 / 018×14 / 019×15，未勾选项 0）。

## 7. 核验方法记录
- 机械核验：`.specify/` 文件树、`specs/*/tasks.md` 与 `checklists/` 勾选统计（grep -c）、阈值常量 grep。
- 子代理深入分块：主线一（结构/一致性）、主线二 P0+P1（代码 vs spec FR + 实跑）、主线二 P2（代码 vs spec 阈值 + 实跑 + 横切）。
- 全量测试：chat-api `venv/bin/python -m pytest tests`（1562 passed）；admin-api 借 chat-api venv 跑（236 passed）；两案例（40 passed）。
- 独立复核：六层串行链、R4 三层保险、PII 四策略、007 降级抛错、009 三规则/5s 预算、010 四模式/环检测、002 share 300s/co-presence、008 五标签页、T999 零调用点 grep。
