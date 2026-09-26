# SDD 补强内容（P0/P1/P2）落地对照表

> 说明：最近推送的 SDD 补全代码（001–019 各特性 tasks.md 全部勾选）已落地为
> **服务 / 接口 / 数据 + 测试**。运行中的 Docker 镜像若不包含新代码，
> 部分条目需重建镜像（经典 builder：`DOCKER_BUILDKIT=0 docker build ...`，
> 见「构建与启动」节）后才在界面上可见。
>
> 状态图例：✅ 已实现（代码+测试）｜🖥️ 界面触点｜⚙️ 后台/协议层（无独立 UI）
>
> 「实现 vs 接线」口径（2026-09-25 核验 + 生产接线 + UI/业务调用点补齐）：✅ 表示「库代码 + 单测全绿」。
> **001（chat-api 运行时侧门禁挂载）、007（failover/降级/退避的生产调用点）、009（turn_admission 挂载 + 后端 CRUD + admin-web 钩子规则页 UI）、002（HTTP 端点 + user-web 会话版本化 UI）均已完成生产接线与 UI 落地**（详见 §4「接线状态」）。
> 001 FR-11 偏离（自建表 vs 复用 EnterpriseApproval）仍待用户拍板。
> 008 端点/前端、010 四模式引擎（competitor_deep_dive / a2a client 已接入）、011/016 共用 `marked_low_quality` 位、012–019 协议/服务层能力均已接入生产链路或具备生产调用点。
> 001 另有一处 spec 偏差：FR-11 要求「复用 `EnterpriseApproval`、不新建审批表」，实现为 admin-api 自建 `gate_approvals` 集合（状态机语义一致，建表未达标）。
> T999 横切审计（`services/feature_audit.py` + `services/feature_audit_bridge.py` + `im_gateway/audit.py` + `dream_cycle/evolution_audit.py`）：事件族 / sink 接口 / 路由到 001 审计流 / 单测完整；**各特性关键事件点已接 `emit_feature_event`**——015 KG mutation/audited、017 memory.promoted、018 asset.registered/status.changed、012 a2a.outbound/denied、014 entity.indexed、016 skill.quality.marked（admin-api 静默降级）。

## 0. 速查总表

| 优先级 | 特性 | spec | 实现模块（chat-api / admin-api） | 测试 | 界面触点 |
|---|---|---|---|---|---|
| P0 | 001 gatekeeper | 001 | `governance/{risk,pii,permission_grants,layers/*}.py` + `routes/governance.py`（admin-api） | 治理矩阵/PII/US4-US5/polish 全绿 | 工具管理风险格、审批中心、配额、审计 |
| P0 | 007 网关韧性 | 007 | `llm/resilience/{degradation,failover,pricing,metering,retry}.py` + `llm/instrumented_client.py`（注：instrumented_client 在 `app/llm/`，非 `resilience/` 子目录）+ `configured_models.get_llm_client_by_model_id` 已接 `ResilientLLMClient`（生产生效，FR-9 单实例 no-op） | `tests/llm/` 韧性 39 项（test_resilience 25 + test_resilience_metering 14）；**failover/降级/退避已在生产 LLM 调用路径生效**（`configured_models` 按同 main_id+capability 的 active 实例优先级包进 `ResilientLLMClient`）；401/403 不重试（FR-4）；成本计量复用 008 MODEL_PRICES（FR-5）；新增 6 项单测全绿 | 驾驶舱「成本」标签（降级事件时间线） |
| P0 | 008 驾驶舱 | 008 | `app/api/dashboard_usage.py` + `app/api/dashboard_metrics.py` + `routes/dashboard.py`（admin-api）+ `DashboardPage.vue`（admin-web `src/views/dashboard/`） | `test_dashboard_selfcheck.py` 10 项 + routes 6 项 + metrics 24 项；端点已接入生产 | 驾驶舱四维标签页 |
| P1 | 002 会话版本化 | 002 | `session_versioning/{co_presence,share,audit}.py` + `/api/sessions/{id}/commit|versions|share|redeem|revoke|co-presence`（chat-api `dsh_session_versioning.py`）+ user-web `SessionVersioningDrawer.vue` | `test_session_us5_and_polish.py` 8 项 + 端点 5 项全绿；**HTTP 端点 + user-web 会话版本化 UI（版本历史/分享/在线成员 + 5s 心跳）已接入生产** | 会话页：版本历史/分享/在线成员 |
| P1 | 009 钩子拦截 | 009 | `dsh_runtime/hooks/{integration,lifecycle,store,guard}.py` + `turn_admission.run_pre_tool_use`（生产挂载）+ admin `/api/hooks/rules` CRUD（chat-api `dsh_hooks.py`）+ admin-web `HookRulesPage.vue` | `test_hooks_009.py` 17 项 + 挂载 18 项全绿；**引擎已挂 PreToolUse 门禁 + admin-web 钩子规则页已落地**（浏览器实测 CRUD 跑通） | 管理后台 → 钩子规则（`/hooks/rules`） |
| P1 | 010 DAG 编排 | 010 | `orchestration/{graph,conditions,engine,supervisor,topo,registry,loader}.py` + `services/dag/{skip,retry,builder_migrate}.py`（`loader.py` 为 YAML 编排加载器，案例二依赖，原表漏列已补） | DAG 25 + 编排既有测试；已接入生产（`research/competitor_deep_dive.py`、`a2a/client.py`） | 管理后台 → 编排定义 |
| P1 | 011 Dream 自进化 | 011 | `services/dream_cycle/{runner,friction,mr,deprecation,evolution_audit}.py` | dream 系列 32 项 | 管理后台 → 自进化（低采纳检测/MR） |
| P2 | 012 A2A 网关 | 012 | `a2a/{protocol,agent_card,client}.py` | `test_a2a_client_012.py` 7 项 | ⚙️ 协议层（JSON-RPC 端点/AgentCard） |
| P2 | 013 多 IM 入口 | 013 | `im_gateway/{router,bindings,webhook,audit}.py` | im_gateway 既有 + T999 审计 | ⚙️ 渠道管理（wecom/feishu 路由） |
| P2 | 014 语义索引 | 014 | `services/business_semantic_index.py`（复用 005 检索） | 014/017 合并测试 | 知识库检索结果带来源锚点 |
| P2 | 015 知识图谱 | 015 | `knowledge_graph/{store,query,consistency}.py` | KG 既有 + T999 审计 | ⚙️ 知识图谱查询 |
| P2 | 016 Skill 加固 | 016 | `skill_lifecycle/service.py` + `dream_cycle/deprecation.py`（共用 `marked_low_quality`） | skill 系列测试 | Skill 管理（打分/回滚/低质标记） |
| P2 | 017 三域记忆 | 017 | `memory/{scope,lifecycle,retrieval}.py` | 014/017 合并测试 | 记忆管理（personal/workspace/org） |
| P2 | 018 能力资产 | 018 | `services/capability_assets.py` | `test_capability_asset_us2.py` 7 项 | 能力资产治理视图 |
| P2 | 019 弹性配置 | 019 | `harness_config/{profile,layer_switch,floor,gate_adapter}.py` | harness_config 既有测试 | 配置中心（profile/层开关/合规底线） |

横切：T999 审计统一走 001 落点（`im_gateway/audit.py` + `services/feature_audit.py`）；
T998 契约见 `contracts/{orchestration,self-evolution,session-versioning-contract,harness-config,a2a-gateway}.md`。

---

## 1. P0 — 生产底座

### 1.1 001 门禁治理（六层门禁）
| 功能 | 界面位置 | 代码位置 | 说明 |
|---|---|---|---|
| 风险分级 R0–R4（L1–L5×R0–R4 共 25 格） | 管理后台 → 工具管理 → 工具详情 | admin-api `governance/risk.py` | 每个工具按 autonomy×risk 落格；高风险显示审批/只读/拒绝策略 |
| PII + 会话秘密脱敏 | 管理后台 → 审计日志 / 导出物 | admin-api `governance/pii.py` + chat-api 会话共享 secret 过滤 | 身份证/邮箱/手机/银行卡/密钥 × mask/remove/hash/abstract；`secret`/`password` 字段不出库 |
| 审批中心（人工介入） | 管理后台 → 审批/待办 | admin-api `governance/layers/approval.py` | 敏感操作生成审批单，5min 超时自动拒绝；审批记录进审计 |
| 配额管理 | 管理后台 → 配额 | admin-api `governance/layers/quota.py` | 租户级调用/token 限额，超限 429 + 降级事件 |
| 显式授权（permission grants） | 管理后台 → 授权管理 | admin-api `governance/permission_grants.py` + `layers/rbac.py` | RBAC 权限码并集 + 显式授权，fail-closed |
| 配置变更审计 | 管理后台 → 审计日志 | admin-api `governance/config.py` | 配置变更留 001 审计落点 |

> 偏差注（2026-09-25 核验）：FR-11 要求「复用 `EnterpriseApproval`、不新建审批表」，实现为 admin-api `governance/layers/approval.py` 自建 `gate_approvals` 集合（状态机语义 pending→approved/denied/expired、poll、5min TTL、token 哈希、一次性消费均一致，但「不新建审批表」未达标）；`EnterpriseApproval` 实际位于 `chat-api/app/enterprise_capabilities/tools/contracts.py`。

### 1.2 007 LLM 网关韧性
| 功能 | 界面位置 | 代码位置 | 说明 |
|---|---|---|---|
| 模型降级链（高性能→中档→轻量） | 驾驶舱「成本」标签 | `llm/resilience/degradation.py` | 可重试失败逐档降级并发降级事件；401/403 立即中止；链耗尽抛 `DegradationError` 明确报错不静默 |
| 主→备 failover + 指数退避 | 驾驶舱「质量」标签 | `llm/resilience/failover.py` + `retry.py` | 退避 1.5s/30s/±10%/3 次；事件落 `token_usage_logs` |
| 成本计量 + 价目表 | 驾驶舱「成本」标签 | `llm/resilience/{pricing,metering}.py` | 与 008 同源 `MODEL_PRICES`（¥/1M）；每次调用 token 成本估算 |

### 1.3 008 运营驾驶舱（四维）
管理后台 → 驾驶舱：`DashboardPage.vue` 五个标签页
| 标签 | 内容 | 代码位置 |
|---|---|---|
| 总览 | 调用量/失败率/活跃用户/成本核心指标卡 | `routes/dashboard.py` `overview()` |
| 成本 | 各模型占比、部门/智能体分摊、预测（N=4 移动平均）、降级事件时间线 | `build_cost_section` + `forecast_cost` |
| 使用 | 调用时序（日/周/月粒度）、去重活跃用户、Skill/检索频次 top-N | `dashboard_usage.py`（T014/T015） |
| 质量 | 成功率/P50/P95/异常率、人工介入率（=审批挂起数） | `dashboard_metrics.py` 质量段 |
| 趋势 | 环比/同比 delta、瓶颈 top-N（stage/model 维度） | `bottleneck_top_n` + 前端 `.trend-deltas` |
租户隔离与空态兜底：T024 跨租户 403；T025 空租户返回 `empty_*_section`（前端空态文案不崩）。

---

## 2. P1 — 可靠性与会话级

### 2.1 002 会话 / 工作流双版本化
> 接线状态（2026-09-25 生产接线后刷新）：服务层（`session_versioning` 包）已落地并通过 49 项测试；**HTTP 端点 `/api/sessions/{id}/commit|versions|share|redeem|revoke|co-presence` 已建（`dsh_session_versioning.py`）+ user-web 会话版本化 UI（`SessionVersioningDrawer.vue` + `api/sessionVersioning.ts`，含版本历史/分享/在线成员 + 5s 心跳，接入 `ChatWindow.vue`）均已落地**，`latestSeq` 取 `Math.max(versions[末].seq, props.latestSeq)` 精确对齐。
| 功能 | 界面位置 | 代码位置 | 说明 |
|---|---|---|---|
| 会话 commit / 快照 | 会话页 → 版本历史 | `session_versioning`（linear timeline + snapshot commit，seq 乐观锁） | 每次 commit 生成线性时间线；可回看任意版本 |
| 会话交接（share） | 会话页 → 分享 | `session_versioning/share.py`（US4） | 300s 一次性 token；编辑/只读角色；过期/撤销/已兑换 → 空态 |
| 多人协同在线 | 会话页 → 在线成员 | `session_versioning/co_presence.py`（US5） | Mongo 短轮询心跳 + 在线态 TTL；并发编辑线性合并（无 Redis） |
| 会话事件审计 | 管理后台 → 审计日志 | `session_versioning/audit.py` | enter/leave/commit/resume/share/dereference 进 001 落点 |
| 工作流级版本化 | 编排定义（GraphSpec） | 010 `orchestration/registry.py`（T003/T021） | 定义带 version；`update()` 版本递增 + 归档旧版可回看；定义期 fail-closed 校验 |

### 2.2 009 钩子拦截
> 接线状态（2026-09-25 生产接线后刷新）：钩子引擎 + admin `/api/hooks` CRUD 端点已落地并通过 43 项测试；**运行时已挂载（`turn_admission.run_pre_tool_use` 挂 PreToolUse 钩子门禁，`dsh_chat`/`dsh_execution` 传入 `tool="dsh_turn"` 上下文）；admin-web 钩子规则页（`/hooks/rules` 路由 + `HookRulesPage.vue` + `api/dsh_hooks.ts`，naive-ui 表格+表单）已落地**，浏览器实测全链路 CRUD 跑通。
| 功能 | 界面位置 | 代码位置 | 说明 |
|---|---|---|---|
| PreToolUse 三种规则 | 管理后台 → 钩子规则 `/api/hooks` | `dsh_runtime/hooks/integration.py` + admin `routes/hooks.py` | `deny_tool` / `require_field` / `observe`；作用域 tool > session > tenant；CRUD + 作用域查询 |
| 会话生命周期四事件 | ⚙️ 运行时 | `dsh_runtime/hooks/lifecycle.py` | SessionStart / PostToolUse / SessionEnd / MemoryCommit；禁用 → 返回 None |
| 钩子审计 | 管理后台 → 审计日志 | `dsh_runtime/hooks/integration.py` `audit_hook_execution` | `hook.executed` / `hook.denied` 复用 001 落点（无新集合） |
| fail-closed + 延迟预算 | ⚙️ 运行时 | `dsh_runtime/hooks/guard.py` | 任何异常 → 拒绝；多钩子累计 > 5s 预算 → fail-closed（FR-13） |

### 2.3 010 DAG 编排引擎
| 功能 | 界面位置 | 代码位置 | 说明 |
|---|---|---|---|
| 四模式编排 | 管理后台 → 编排定义 | `orchestration/{engine,supervisor,topo}.py` | sequential / supervisor / hybrid / graph；拓扑排序 + 环检测 |
| 条件跳过 | ⚙️ 引擎事件 | `services/dag/skip.py`（T013-T015） | 受限 JSON 条件运行时求值；真→跳过（可传导下游）/假→运行/语法错→fail-closed；跳过追溯记录 |
| 节点级重试 | ⚙️ 引擎事件 | `services/dag/retry.py`（T016-T017） | 指数退避 base/factor/cap；`delegate_model_backoff` 分层不重复（007 管模型退避） |
| 双轨迁移 + 等价回归 | ⚙️ 内容规划 | `services/dag/builder_migrate.py`（T018-T019） | content-builder semantic/structured/fallback 三路径搬 DAG；`builder_equivalent` 新旧路径 0 破坏 |
| 并发预算 | ⚙️ 网关 | 007 调度器（FR-12） | 多 DAG 并行受 007 并发预算约束，超限排队不超网关 |

### 2.4 011 Dream 自进化
| 功能 | 界面位置 | 代码位置 | 说明 |
|---|---|---|---|
| 经验沉淀（friction 触发） | 管理后台 → 自进化 | `dream_cycle/friction.py` + `runner.py` | retry/fallback/timeout 信号捕获 → 候选排名校验 |
| 周期扫描 → Skill 草稿 + 自动 MR | 管理后台 → 自进化 | `dream_cycle/mr.py` | Jaccard≥0.7 且样本≥5 为高置信 → draft→MR；低置信不产 MR；目标 `specs/004.../drafts` |
| 低采纳自动淘汰 | 管理后台 → 自进化 | `dream_cycle/deprecation.py` | 14d / ≥20 曝光 / <10% 采纳 → 退役；与 016 共用 `marked_low_quality` 位；restore 可恢复 |
| 全链路审计 + 可配置 | 管理后台 → 审计日志 | `dream_cycle/evolution_audit.py` | capture/generate/mr/deprecate/restore 事件；`EvolutionConfig` 阈值可配 |

---

## 3. P2 — 规模化生态

| 功能 | 界面位置 | 代码位置 | 说明 |
|---|---|---|---|
| 012 A2A 出站调用 | ⚙️ 协议层 | `a2a/{protocol,agent_card,client}.py` | `message/send` JSON-RPC + task id 幂等；30s 超时 + failover + 007 退避；治理拒绝 `-32000` 不重试不 failover；AgentCard Dify-first 字段映射 |
| 013 多 IM 入口 | 渠道管理 | `im_gateway/{router,bindings,webhook}.py` | ChannelRouter 注册/启用/停用；停用渠道已有绑定置只读；会话-渠道绑定 |
| 014 业务语义索引 | 知识库检索结果带锚点 | `services/business_semantic_index.py` | 客户/订单/产品/文档/工单指针索引（不写业务库）；检索复用 005 客户端，命中带 citation（`type:id#chunk`） |
| 015 知识图谱层 | ⚙️ 图谱查询 | `knowledge_graph/{store,query,consistency}.py` | 节点/边 + 多跳遍历（CycleGuard）+ 互斥/传递/基数约束（冲突标记不阻断） |
| 016 Skill 市场加固 | Skill 管理 | `skill_lifecycle/service.py` + `dream_cycle/deprecation.py` | 质量打分 + 回滚 + 低质标记（与 011 共用位） |
| 017 三域记忆 | 记忆管理 | `memory/{scope,lifecycle,retrieval}.py` | personal/workspace/org 三域可见性 + 升级授权（full_access_admin）；30d 衰减 + 访问重置计时器；RAG 检索按 scope 过滤排序 |
| 018 能力资产注册 | 能力资产治理视图 | `services/capability_assets.py` | 契约四段 + 版本 + owner；扫描去重（端点+方法）；列表 + 详情下钻；状态 active/deprecated/offline + 审批；`a2a_exposed` 标记供 012 生成 AgentCard |
| 019 Harness 弹性配置 | 配置中心 | `harness_config/{profile,layer_switch,floor,gate_adapter}.py` | tenant > scene > global 覆盖链；层开关；合规底线（R4 恒 deny）不可被 profile 下探；接入 001 gatekeeper |

横切基础设施：
- **T999 审计**：`im_gateway/audit.py`（IM 事件）+ `services/feature_audit.py`（012/014/015/016/017/018 事件）统一进 001 落点。
- **T998 契约**：`contracts/orchestration.md`、`self-evolution.md`、`session-versioning-contract.md`、`harness-config.md`、`a2a-gateway.md`。
- **测试基线**：chat-api 313 项 / admin-api 236 项 / admin-web `pnpm build` 通过（`tests/llm/test_decision_turn.py` 为预存坏例已排除）。

---

## 4. 立即可见 vs 需要新代码

**立即可见（旧镜像已有核心端点）**：驾驶舱总览、工具管理/审批/配额/审计（001 端点）、会话页基础能力。
**需新代码镜像才可见**：P1 全部（钩子规则页、编排定义、自进化、会话版本/分享/在线）+ P2 全部条目 + 驾驶舱四维增强（成本/使用/质量/趋势标签）。

**接线状态（2026-09-25 核验 + 生产接线 + UI/业务调用点补齐）**：
- 001 六层门禁：admin-api 侧六层串行链 + R4 三层保险 + PII 四策略 + RBAC 三段式码已实现；**chat-api 运行时侧 `turn_admission.run_gate_plan` 已把 019 `build_gate_plan` 六层启用计划挂到工具调用路径（生产生效），审计层受 floor 约束强制开启，计划求值与门禁事件同落 001 审计流**；FR-11 偏离（`gate_approvals` 自建表 vs `EnterpriseApproval` 复用）仍待用户拍板。
- 007：**`configured_models.get_llm_client_by_model_id` 已按同 main_id+capability 的 active 实例优先级包进 `ResilientLLMClient`（生产生效，FR-9 单实例 no-op），failover/降级/退避在真实 LLM 调用路径上生效**；401/403 不重试（FR-4）；成本计量复用 008 MODEL_PRICES（FR-5）；新增 6 项单测。
- 009：**钩子引擎已挂载到 `turn_admission.run_pre_tool_use`（生产生效，fail-closed），`dsh_chat`/`dsh_execution` 传入 `tool="dsh_turn"` 上下文；后端 `/api/hooks/rules` CRUD 已建（009 T015 / US4）；命中/被拒经 `audit_hook_execution` 落 001 审计流**；**admin-web 钩子规则页 UI 已落地**（`/hooks/rules` 路由 + `HookRulesPage.vue` + `api/dsh_hooks.ts`，naive-ui 表格+表单，typecheck 通过）；新增 18 项单测。
- 002：**`session_versioning` 包已接 HTTP 端点（`/api/sessions/{id}/commit|versions|share|redeem|revoke|co-presence`，生产生效）；share 一次性核销 TTL 默认 300s，过期/失效返回空态；co-presence 无 Redis（Mongo + 短轮询）**；**user-web 会话版本化 UI 已落地**（`SessionVersioningDrawer.vue` 侧边抽屉 + `api/sessionVersioning.ts`，含版本历史/分享/在线成员 + 5s 心跳，接入 `ChatWindow.vue`，typecheck 通过）；新增 5 项单测。
- T999 审计：**`feature_audit_bridge` 已把 012/014/015/016/017/018 特性事件路由到 001 `position_role_audit_logs`（生产生效），未知 feature/event 抛错 fail-closed；无 DB 时 buffer 不丢事件**；**各特性关键事件点已接 `emit_feature_event`**——015 KG `add_node`/`add_edge`→`kg.mutated`、`check_all`→`kg.audited`；017 `promote_to_org`→`memory.promoted`；018 `register`→`asset.registered`/`set_status`→`asset.status.changed`；012 `A2AClient.send`→`a2a.outbound`/`a2a.denied`；014 `BizEntity` 构造→`entity.indexed`；016 admin-api `mark_low_quality`→`skill.quality.marked`（静默降级）；新增 6 项集成测试。

## 5. 构建与启动（OrbStack buildx 受限时的经典 builder 路径）

OrbStack 的 buildx 在 `~/.docker/buildx/` 被 macOS provenance 锁定时，`./movo build`
会报 `failed to update builder last activity time ... operation not permitted`。
绕过方式：用经典 builder 逐镜像构建，并打运行时前缀标签：

```bash
export PATH=/usr/local/bin:$PATH; export DOCKER_BUILDKIT=0
# 以 chat-api 为例（admin-web / gateway / dsh-runtime-host 同理，--build-arg 见 docker-compose.build.yml）
docker build -f services/chat-api/Dockerfile \
  --build-arg INSTALL_SYSTEM_DEPS_AT_BUILD=true \
  --build-arg INSTALL_PLAYWRIGHT_AT_BUILD=true \
  --build-arg PLAYWRIGHT_WITH_DEPS=true \
  -t movo-chat-api:latest -t ghcr.io/himovo/movo-chat-api:latest \
  services/chat-api
# document-parser 构建中 Docling 模型下载偶发失败时，可跳过该镜像（继续用旧 ghcr 镜像）
./movo up    # compose 用 --pull never 复用本地 ghcr.io/himovo/movo-* 标签镜像
```

## 6. 验证清单（新镜像启动后）

1. 管理后台 → 驾驶舱：确认五个标签页（总览/成本/使用/质量/趋势）+ 空态兜底文案。
2. 工具管理 → 打开任一工具：查看风险格（R0–R4）+ 审批策略。
3. 钩子规则（`/api/hooks`）→ 新建 `deny_tool` 规则，会话中触发该工具，验证拒绝 + `hook.denied` 审计。
4. 会话 → commit → 版本历史（线性时间线）；share 生成一次性 token；在线成员心跳。
5. 编排定义 → 建 graph 模式 DAG：条件跳过（真/假/语法错三态）+ 节点重试（退避）。
6. 自进化 → 低采纳 Skill 检测 + 改进 MR（Jaccard≥0.7 & 样本≥5）+ 退役/恢复。
7. 能力资产 → 治理视图（列表 + 详情下钻）+ 状态审批 + `a2a_exposed` 标记。
8. 审计日志 → 确认 `hook.executed/denied`、会话事件、`a2a.*`、`entity.*`、`asset.*` 事件落 001 落点。

### 6.1 核验结果（2026-09-24，逐镜像重建 + 服务层运行时验证 + admin/朱军峰 凭据 API 级界面端点核验）

> 浏览器 provider 未注册（`browser_open` 报 "no usable browser provider is registered"），改用用户给定凭据做 **API 级界面端点核验**：admin（`admin`/`1qaz2wsx#EDC`）登录 admin-api、朱军峰（`zhujunfeng@bonc.com.cn`/同密码）登录 chat-api。各落点（端点 + 数据 + 服务层运行时 + 演示数据）全部通过。

| 步骤 | 核验层 | 结果 | 证据 |
|---|---|---|---|
| 1 驾驶舱 | 端点（已登录）+ 前端源码 | ✅ | `GET /admin-api/api/dashboard/overview` 已登录 200，顶层 billing/health/metrics/assets/quality/trend/usage/todos/recentActivity 九段齐备；`DashboardPage.vue` 五标签（overview/cost/usage/quality/trend）在 admin-web 镜像 dist 内；造数后 calls24h=59、p50Ms/p95Ms/趋势环比出数 |
| 2 风险格 | 端点（已登录）+ 数据 | ✅ | `GET /admin-api/api/api/governance/autonomy-matrix` 已登录 200，L1–L5×R0–R4 矩阵 + canonical 齐备；mongo `autonomy_matrix` 25 行；路由双前缀（`/admin-api/api/api/...`）确认 |
| 3 钩子规则 | 端点全链路（已登录） | ✅ | `POST /rules`（deny_tool）201 → `GET /rules` 200（含该规则）→ `GET /rules/{id}` 200 → `GET /scope?tool=dangerous_tool` 命中 → `DELETE` 204；修复 motor 异步 bug 后全链路通过（此前 500） |
| 4 会话版本化 | 服务层运行时（DB 模式） | ✅ | 容器内 `ShareStore.create_share` token + `is_active()`；`CoPresence` 双用户心跳→`online()={u1,u2}`；`merge_messages` 线性时间线 [1,2,3,4,5,6]；演示数据 `session_shares` ×1 已造 |
| 5 DAG 跳过/重试 | 服务层运行时 | ✅ | `evaluate_skip` 三态（true→skip / false→run / 语法错→fail-closed skip）；`run_node_with_retry`（RetryPolicy 指数退避）成功 1 次、失败后 3 次成功、耗尽 succeeded=False |
| 6 Dream 自进化 | 服务层运行时 | ✅ | `detect_low_adoption`（≥20 曝光 & <10% 采纳 & 14d 窗口）命中/不命中均正确；`mark_deprecated` 置 `marked_low_quality`；`deprecation_flow` → action=deprecated；`restore` 清除标志 |
| 7 能力资产 | 服务层运行时（DB 模式） | ✅ | `register`→`governance_view`（3 条演示数据）→`governance_detail`（契约下钻）→`set_status(offline, approver)` 审批→`mark_a2a_exposed`；非法状态抛 ValueError |
| 8 审计落点 | 端点（已登录）+ 服务层 | ✅ | `GET /admin-api/api/system-audit/logs` 200，hooks/skills/tools 管理事件落 001 落点；`record_feature_event` 覆盖 012/014/015/016/017/018 事件族经 sink 落 001 落点；未知 feature/event 拒绝不误吞 |

**P1/P2 各条目落点核验（容器内服务层，均导入成功）**：
- P1 009 钩子拦截：`dsh_runtime/hooks/{integration,lifecycle,store,guard}.py` + admin `routes/hooks.py` 全链路通过。
- P1 010 DAG 编排：`orchestration/{graph,conditions,engine,supervisor,topo,registry}.py` + `services/dag/{skip,retry,builder_migrate}.py`。
- P1 011 Dream 自进化：`services/dream_cycle/{runner,friction,mr,deprecation,evolution_audit}.py`。
- P2 012 A2A 网关：`a2a/{protocol,agent_card,client}.py`，`build_agent_card` 端点就绪。
- P2 013 多 IM 入口：`im_gateway/{router,bindings,webhook,audit}.py`，`ChannelRouter`/`SessionBindingRegistry`。
- P2 014 语义索引：`services/business_semantic_index.py`（`BusinessSemanticIndex`/`SemanticHit`/`ENTITY_TYPES`）。
- P2 015 知识图谱：`knowledge_graph/{store,query,consistency}.py`（`KgStore`/`MultiHopResult`/`CycleGuard`）。
- P2 016 Skill 加固：`skill_lifecycle/service.py` + `dream_cycle/deprecation.py` 共用 `marked_low_quality`。
- P2 017 三域记忆：`memory/{scope,lifecycle,retrieval}.py`（`MemoryScope`/`ORG_PROMOTION_ROLES`/`SCOPE_VISIBILITY`）。
- P2 018 能力资产：`services/capability_assets.py`（修复后 DB 模式全链路通过）。
- P2 019 弹性配置：`harness_config/{profile,layer_switch,floor,gate_adapter}.py`，`r4_always_denied`/`assert_floor_intact` 合规底线验证通过。

**本轮发现并修复的 motor 异步 bug（4 处）**：同步方法直接调用 motor 异步 db（未 `await`）→ 500 / 写入静默丢失：
1. admin-api `app/services/hooks_store.py`（6 CRUD 方法改 async + `routes/hooks.py` 6 处 `await`）——修复前 `GET /api/api/hooks/rules` 500；
2. chat-api `app/dsh_runtime/hooks/store.py`（同型 7 方法改 async + `tests/test_hooks_009.py` 3 项测试改 async）；
3. chat-api `app/services/capability_assets.py`（`CapabilityAssetRegistry` 9 方法改 async + DB 模式 `governance_view` 从库回灌 + `tests/services/test_capability_asset_us2.py` 7 项测试改 async）；
4. chat-api `app/services/session_versioning/share.py` + `co_presence.py`（`ShareStore` 4 方法 + `CoPresence` 5 方法改 async，修正 `ShareStore.to_document(share)` 传参错误 + `tests/services/test_session_us5_and_polish.py` 同步更新）。

另修 admin-api `app/api/routes/dashboard.py` `_duration_ms`/`_duration_percentiles_fallback` 的 `int(row.get("start_time"))` 对 BSON datetime 报错（500）→ 新增 `_to_ms()` 归一化（兼容 epoch int 与 datetime）。

**测试基线**：admin-api 236 项全过；chat-api 非 e2e 1808 项全过（排除预存坏例 `tests/llm/test_decision_turn.py` 与 4 个 dsh_runtime e2e 文件——stash 对照确认 e2e 失败为预存环境依赖，与本次改动无关）。

**镜像重建**（经典 builder `DOCKER_BUILDKIT=0`）：admin-api `babb202a`、chat-api `0877b010`，均 `--force-recreate` 重启 healthy，修复已确认带进容器。

**演示数据**（均带 `demo_seed: true` 标记，可一键清理 `db.<coll>.deleteMany({demo_seed:true})`）：tools ×3、skills ×3、`token_usage_logs` 24h 窗口 ×60、`capability_assets` ×3（对齐 registry schema）、`session_shares` ×1。造数后驾驶舱各段（metrics/quality/usage/trend）均出数。

**遗留说明**：
- 步骤 1/2/3 的「界面点击」与步骤 4–7 的「UI 触发」需浏览器实操（当前会话浏览器 provider 未注册，故用 API 级端点 + 服务层运行时等价验证）；端点/数据/服务层/演示数据全部通过。
- chat-api 镜像必须 `--no-cache` 重建才真正包含 SDD 模块；本轮修复已 `--force-recreate` 重启，确认带进容器。
