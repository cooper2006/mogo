# Spec 落地审计（2026-10-03，按"今天的标准"重检）

## 为什么重检

`INDEX.md` 的旧结论（2026-07-08）写着"**19 个特性全部已有实现核心/MVP**，合计 313 项新测试通过"。
但 2026-10 的 011/016 实践暴露：**该结论把"有纯逻辑代码 + 单测通过"当成了"已实现"**——
016 的效果分/灰度当初只是纯函数（无生产调用方），011 的采纳采集从未接线，002 的秘密过滤与审计同样零接线。

本文按**今天的标准**重新检查 `specs/` 下全部 20 个特性。

## 今天的标准（判定"真落地"的四条）

1. **生产接线**：核心符号有真实生产调用方——`grep` 命中 `app/` 业务路径（endpoint / service / runtime / lifespan），
   而**非仅** `tests/` 与包内 `__init__` 导出。
2. **消费方存在**：产出的数据 / 标记 / 事件 / 视图**有读取者并影响行为**（不是只写不读）。
3. **数据源真实**：依赖的输入**有真实来源**（不是"定义了参数但无人传"）。
4. **端到端可证伪**：有测试证明"输入 → 行为改变"，而非"函数返回了某个值"。

> **明确不采信 `tasks.md` 的 `[x]`**：16 份 tasks 全为 100% 勾选，而其中多个特性已被证明为 hollow。

判定档位：`landed`（四条全成立） / `partial`（主链路通但有明确缺口） / `hollow`（只有纯逻辑，无生产调用方或无消费方或输入无人提供）。

## 方法与独立抽查复核

**方法**：用 workflow 并行审计（每个 spec 一个 agent，另对非 `landed` 者做对抗性复核），
要求证据为 `file:line` / grep 事实。**并对关键结论做了独立人工抽查复核**（下表），确认非 agent 臆测。

| 结论 | 复核命令 | 结果 |
|---|---|---|
| 013 `im_gateway` 零生产 import | `grep -rn "im_gateway" app/ \| grep -v "app/im_gateway/"` | 空 ✅ |
| 014 `business_index` 零生产 import | `grep -rn "business_index" app/ \| grep -v "app/business_index/"` | 空 ✅ |
| 015 `knowledge_graph` 零生产 import | `grep -rn "knowledge_graph" app/ \| grep -v "app/knowledge_graph/"` | 空 ✅ |
| 017 `app.memory` 零生产 import | `grep -rn "app\.memory" app/ \| grep -v "^app/memory/"` | 空（包内自引用不算）✅ |
| 002 秘密过滤未接线 | `grep -n "secret\|placeholder\|redact" app/api/endpoints/dsh_session_versioning.py` | 空 ✅ |
| 002 审计未接线 | `grep -rn "record_session_event" app/` | 仅定义处 ✅ |
| 018 注册器零调用 | `grep -rn "CapabilityAssetRegistry\|discover_assets" app/` | 仅定义 + `__init__` 导出 ✅ |
| 016 灰度轴零调用 | `grep -rn "evaluate_canary\|apply_rollback" app/ \| grep -v "canary.py"` | 空 ✅ |
| 011 草稿/片段不落库 | `grep -n "insert_one\|update_one" app/services/dream_cycle/runtime.py` | 空 ✅ |
| 011 淘汰输入无人传 | `grep -n "run_once(" app/services/dream_cycle/runtime.py` | `:386` 仅传 config/sink ✅ |
| 019 `harness_mode` 无生产者 | `grep -rn "harness_mode" app/` | 仅 1 处读取 ✅ |
| 001 配额 resolver 无注入 | `grep -rn "limits_resolver" app/` | 仅定义处 ✅ |
| 001 `gate_events` 零读取 | `grep -rn "gate_events" app/` | 仅注释/定义/建索引/写入 ✅ |
| 020 chat-api 无 `unlimited` | `grep -n "unlimited" app/core/quota_policy.py` | 空 ✅ |

### 深挖验证（复杂推理链，逐环节核对）

对报告里**最严重且最影响决策**的几条结论做了逐环节独立验证（这些不是简单 grep，而是多跳推理）：

| 结论 | 验证环节 | 结果 |
|---|---|---|
| **001 RBAC 角色源断裂** | ① `tools.py:327` 取 `current_user["role_ids"/"roles"]` → ② `deps.py:_load_authenticated_account` 返回 `{**user, main_id, role_name, org_name, display_name}`，无这两字段 → ③ `org_user_repository.create_account` 写入字段表（`main_id/username/display_name/email/phone/group_code/role_name/status/...`）确无 `role_ids`/`roles`，**只有 `role_name` 字符串** → ④ `rbac.py:_role_documents` 对空 `role_ids` 直接 `return []`，且**无 `role_name` fallback** | **成立** ✅ 角色预设码恒空，生产必 fail-closed |
| **001 审批无恢复路径** | ① `tools.py:348/350` 只把 token 写进 HTTP 409 detail → ② `approval.py:147` 的恢复分支读 `ctx.annotations["approval_token"]`，全仓无生产者 → ③ `grep "\.deny("` 无调用方 | **成立** ✅ 触发审批即永久挂起 |
| **001 `gate_events` 零读者** | `grep -rn "gate_events" app/` → 仅注释/常量定义/建索引/写入，**无 find/aggregate** | **成立** ✅ |
| **003 锚点空心（中间段丢失）** | ① 解析侧**确实产出** `sourceAnchor`（`document_parsing_service.py:246/430`）→ ② 但 `vector_store.py` 中 `anchor/metadata/bbox` **零命中**（schema/upsert/GraphQL fields 均无）→ ③ 消费方 `citation_resolver` 读 `metadata.sourceAnchor` | **成立** ✅ 产出有、通道断、消费方永远拿空 |
| **020 配额不限额未贯通** | `chat-api/app/core/quota_policy.py:219 assert_quota_available` 仅 `status != active` 与 `remainingPoints <= 0` 两判断，**无 `unlimited` 短路** | **成立** ✅ 新租户成员发消息被 402 |
| **016 灰度轴零调用** | `grep "evaluate_canary\|apply_rollback" app/` 排除 `canary.py` 后为空 | **成立** ✅ |

### 反向验证（确认没有"其实 landed 却被误判"）

- **006 position-rbac-admin** 是全部 20 个中**最接近 landed** 的（报告判 `partial`）。独立核对：
  路由真实挂载（`api/router.py:14`）✅、前端真实调用（`apps/admin-web/src/api/positionRoles.ts:46-58`）✅、
  chat-api 真实强制（`turn_admission.py:201-212` 经 `MongoEmployeePolicyResolver`）✅。
  它仍判 `partial` 的原因成立——缺端到端可证伪测试（`test_position_role_service.py` 只覆盖 `_document` 纯函数），
  以及 `copy_role` 可绕过 FR-6 校验。
- **结论**：`landed = 0` 的判断成立——连最强的 006 都差在"端到端可证伪"这条硬标准上，非判定过严。

**回写**：结论已回写到被检查对象旁边，避免单读某个 spec 仍被"tasks 全勾"误导——
16 份 `tasks.md` 顶部 + 20 份 `checklists/requirements.md` 顶部 + 011 的 `checklists/implementation.md` 末尾。

## 总览（20 个特性）

**结论：`landed` 0 个 · `partial` 10 个 · `hollow` 9 个 · 高危缺口 ≥ 60 条。**
即：**没有任何一个特性达到"按今天标准的真落地"**。

| 特性 | 判定 | 一句话结论 |
|---|---|---|
| 001 gatekeeper-governance | **hollow** | 六层链只挂在 2 个管理面工具测试端点；RBAC 角色源断裂（`ctx.roles` 恒空）、配额层恒放行（`limits_resolver=None`）、脱敏改的是浅拷贝（明文照发后端）、`gate_events` 全仓零读者；chat-api 真实链路由 `gate_adapter` 显式标记未启用。 |
| 002 session-versioning | **hollow** | 有真实路由/前端/Mongo，但每条 FR 断在语义层：commit 是客户端自报元数据（从不读会话消息）、秘密过滤在 commit/share 调用次数为 0、resume 只返回一个 int 就被丢弃、share 兑换传 token 却按 share_id 查（必然失败）。 |
| 003 document-ingestion-delivery | partial | 解析/预览/检索/交付主链路真实跑通；但引用锚点从未进入向量库（US2 空心）、XLSX/PPTX 轻量回退不存在、解析核心零真实测试（两处引用均为 monkeypatch 打桩）。 |
| 004 skillhub-lifecycle | partial | 草稿→发布→快照→ZIP 校验安装主链路真落地（含岗位策略过滤）；但 FR-8 审计全轴零接线、FR-3 版本回看零消费方、FR-4 反馈无写入方。 |
| 005 knowledge-rag-research | partial | 带引用 RAG 问答、租户/组织授权过滤、个人知识目录+分享真实接线；但 US3 多轮研究的 `ResearchFocusBuilder` 全仓零调用、FR-10 审计零接线。 |
| 006 position-rbac-admin | partial | 角色 CRUD/绑定/审计 + chat-api 岗位策略强制真实接通（本批最强）；缺端到端测试，`copy_role` 可绕过 FR-6 校验，批量分配非原子。 |
| 007 llm-gateway-resilience | partial | failover/退避/成本计量在 `get_llm_client_by_model_id` 接上了（但仅作用于模型连通性测试路由，真实对话链路绕过）；降级链 `run_with_degradation` 零生产调用方。 |
| 008 ops-dashboard | partial | overview 端点 + 前端 quality/trend/usage 真实接线；成本维度后端 `build_cost_section` 零调用、`/overview` 不返回 cost 段、agent_id 无数据源。 |
| 009 hooks-interception | partial | PreToolUse 声明式规则真实接线并 fail-closed；但 `tool` 恒为硬编码 `"dsh_turn"`（按工具规则永不命中）、超时预算零接线、五事件只落地 1 个。 |
| 010 dag-orchestration-engine | **hollow** | 引擎代码完整（1243 行）且有可证伪测试，但唯一 app 内消费方 `competitor_deep_dive` 自身无人调用，无路由/Skill 入口，条件跳过与审计未接线。 |
| 011 dream-cycle-self-evolution | partial | friction 捕获链路真落地（lifespan 启动、读真实 projection、写 001 审计）；但经验片段与草稿不落库、MR 未创建、低采纳淘汰无生产输入，产出全空。 |
| 012 a2a-agent-gateway | **hollow** | 仅纯内存数据模型（AgentCard/JSON-RPC 形状/客户端骨架）；无 HTTP 端点、无真实传输、零生产调用方，A2A 对外互通不可达。 |
| 013 multi-im-entry | **hollow** | 仅纯逻辑内核（飞书解析/HMAC/nonce/分块/内存绑定）；无 webhook 路由、无出站投递、绑定无持久化，`im_gateway` 在 `app/` 零 import。 |
| 014 business-semantic-index | **hollow** | 仅 3 个纯数据模型/纯函数（约 351 行）+ 单测；连接器、增量拉取、检索消费方、`bizdata:read` 权限全部不存在。 |
| 015 knowledge-graph-layer | **hollow** | 仅纯内存图算法 + 单测；无 `extract.py`、无 `kg_nodes`/`kg_edges` 存储、无 API 入口、无 RAG 融合，图谱永远为空。 |
| 016 skill-market-hardening | partial | 效果分采集闭环（`skill.selected`→三维→标记→市场降权）真落地并有生产接线；但监控端点、版本维度、灰度/回滚整轴为空。 |
| 017 three-scope-memory | **hollow** | 三级 scope 模型与可见性纯函数 + 单测；`app.memory` 在 `app/` 零导入，`store.py`/`promote.py`/`sediment.py`/endpoint 全缺失。 |
| 018 capability-asset-registration | **hollow** | 仅纯 dataclass 注册逻辑 + 单测；无路由、`capability_assets` 集合无读取方，发现/治理/A2A 暴露/审计四条主链路全空壳。 |
| 019 harness-elastic-config | **hollow** | 仅"恒厚模式"计划求值挂上调用路径；`request` 从未传入 → `harness_mode` 恒 `thick`，薄模式不可达，`ProfileResolver` 零调用方，无 profile 存储与管理面。 |
| 020 platform-multi-tenancy | partial | 租户供给/平台管理员/生命周期/隔离守卫真实落地并接前端（本批质量最高）；但配额"不限额"只在 admin-api 侧，chat-api 执法路径无 `unlimited` 概念，真实用量下被 402 拦截。 |

## 高危缺口（按特性）

### 001 gatekeeper-governance（5）—— **已修 5/5（2026-10-03）**

> ① RBAC 角色源：员工侧由内部端点从 `end_user_position_roles` 解析；admin 侧回落到
>    `system:<main_id>:full_access_admin` 全权预设。
> ② 配额层：不再依赖从未存在的 `quota_limits`，改为注入 **020 真实 token 预算**检查器
>    （`build_layers` 默认安装）。
> ③ PII 脱敏生效：内部端点把脱敏后的 request 回传，`run_gate_plan` 经
>    `GatePlan.redacted_request` 暴露给调用方（**调用方采用后才完全生效**，见下方残留）。
> ④ 审批：拆成 `ApprovalRegistry.decide`（**审批人** pending→approved/denied）+
>    `consume`（申请者凭**已批准**票一次性放行）；新增审批人端点
>    `POST /internal/gatekeeper/decide` 与待办收件箱 `GET /internal/gatekeeper/approvals`。
>    **修掉了"自产自销"缺陷**——原 `validate_and_consume` 允许申请者凭自己的 token 直接放行，
>    等于没有人工审批。
> ⑤ `gate_events` 消费方：新增 `GET /internal/gatekeeper/events` 查询端点；并修掉
>    `Gatekeeper._record` 丢弃 audit 返回值的缺陷（审计落库失败现在真的 fail-closed）。
> **新增接线**：001 六层链已从 chat-api 员工侧经内部端点真实调用（此前是空壳计划）。
> **残留**：③ 的脱敏产物需 DSH 工具分发层采用 `GatePlan.redacted_request` 才端到端生效
> （详见 WORK_LOG）。
- **RBAC 第 2 层数据源断裂**：`tools.py:327` 取 `current_user["role_ids"/"roles"]`，但 `deps.py` 返回的账户 dict 无该字段 → `ctx.roles` 恒空 → `rbac.py` 短路后仅剩 explicit grants，生产上必然 fail-closed。真实映射 `end_user_position_roles` 在 `governance/` 下零引用。
- **配额第 5 层恒放行**：`layers/__init__.py:30` 无参构造 → `limits_resolver=None` → `quota.py:106` 直接 `return {}` → `ALLOW("no quota limits configured")`。plan 声称的 `quota_limits` 集合全仓 0 命中。
- **PII 第 3 层产出无消费方**：`tools.py:333` 传入 `dict(payload)` 浅拷贝，`redaction.py` 只改拷贝；`tools.py:304/315` 仍发原始 `payload` → FR-7 不成立，明文照发后端。
- **审批挂起无恢复路径**：`approval_token` 仅写出（`tools.py:348/350`），无消费者；`ApprovalRegistry.deny()` 无调用方，`gate_approvals` 无读取路径。
- **审计第 6 层只写不读**：`gate_events` 全仓无 `find/aggregate`，且与 `system_audit_logs` 并非同一落点（与 `audit.py` 自称不符）。

### 002 session-versioning（5）—— **FR-7/8/11 + share 兑换已修（2026-10-03，见 WORK_LOG 续十三）**

> **已修**：
> - **FR-7/8 秘密过滤**：commit 端点对 `summary`+`content` 跑 `detect_secrets`→可逆占位符，
>   原文仅存 `session_secret_refs`（owner/admin 作用域）；新增 `GET /sessions/{id}/secrets/{token}`
>   解引用端点（仅 owner 或 `system:<main>:full_access_admin`，每次解引用落审计；拒绝也审计）。
> - **FR-11 审计**：commit/resume/share/dereference 均经 001 审计流（`position_role_audit_logs`）
>   落 `session.<event>` 事件。
> - **share 兑换必败 bug**：`ShareStore._load` 改按 `share_id`/`token` `$or` 查（原只按 share_id 查
>   token，必 404）；share 视图暴露 `token`（active 时）。
>
> **仍待修（002 剩余 3 条，P0 最后一公里/P1）**：
> - commit 仍是客户端自报元数据（端点不读 `chat_messages`，真实 seq 由 `sessions.py` 独立定）；
>   服务端未主动读 `chat_messages` 兜底脱敏。
> - `preview` 仍硬编码 None（`SnapshotStore.preview()` 零调用）。
> - resume 仍只返回 int（`resumeSessionFrom` 前端零调用者，不写状态）。
- **FR-7/FR-8 秘密过滤零接线**：`dsh_session_versioning.py` 全文无 `secret/reference/placeholder/redact`；`snapshot.as_document()` 无消息正文字段——不是"过滤失效"而是"过滤对象不存在"。唯一相关测试是空断言。
- **commit 是客户端自报元数据**：端点只看 `CommitIn`（seq/trigger/summary/...），从不查 `chat_messages`；前端把 `messages.length` 当 seq 传。`preview` 被硬编码 `None`，`SnapshotStore.preview()` 零调用。
- **resume 零影响**：只 `return resumeAfterSeq`，不写任何状态；`resumeSessionFrom` 前端零调用者。真实 seq 由 `sessions.py _next_seq` 独立决定。
- **FR-4 乐观锁与 FR-11 审计均为纯逻辑**：`check_and_advance` 与 `record_session_event` 仅 tests 调用；002 未进 `FEATURE_AUDIT_EVENTS`。
- **share 兑换必然失败**：传入 token 却按 `share_id` 查。

### 003 document-ingestion-delivery（3）
- **引用锚点 end-to-end 空心**：producer 写 `metadata.sourceAnchor`，但 `vector_store.py` 的 schema/upsert/GraphQL fields 全无 anchor 字段，也没有 metadata 通道 → 消费方 `citation_resolver` 永远拿空。
- **XLSX/XLSM/PPTX 无解析分支**：`document_parsing_service.py` 里 `xlsx|xlsm|pptx` 零命中；`parse_with_fallback` 对它们直接 `raise`，与 spec 验收场景矛盾。
- **解析核心零真实测试**：两处引用均为 `monkeypatch` 打桩。

### 004 skillhub-lifecycle（4）
- **FR-8 审计零接线**：chat-api 四个 skill 端点 `grep audit` 0 命中；`FEATURE_AUDIT_EVENTS` 不含 004；admin-api 中间件只按路径首段推断 module。
- **FR-3 版本回看零消费方**：`fetchSkillReleases` 全仓零调用者，admin-web 无该函数。
- **FR-4 反馈与版本无关联**：`organization_skill_feedback` 查询键仅 `resource_id`，无 `release_id/version`。
- **FR-5 签名校验不存在**：`skill_packages/*` 无任何 signature/verify 代码，plan 的 OQ-1 自承未定。

### 005 knowledge-rag-research（3）
- **US3/FR-6 `ResearchFocusBuilder` 零调用**：仅 `__init__` 导出；实际注册的是另一套 `ProgressiveResearchAgent`（不读内部知识）。
- **FR-10 审计零接线**：`knowledge/` 与 `rag_service/` 下 `grep audit` 无命中。
- **US2/FR-5 组织级隔离未实现**：默认策略把非 personal 文档无条件放行，真实策略被 env 注入到专有模块。

### 006 position-rbac-admin（2）
- **`copy_role` 绕过 FR-6 校验**：`service.py:82-84` 直接序列化源角色，`tool_access_mode=='all'` 的 `tool_ids=[]` 被原样复制 → 复制出的角色零工具零技能且无报错。
- **批量分配非原子**：`position_roles.py:168-175` 先校验后逐用户 `delete_many+insert_many`，中途失败留下部分改动的无审计状态。

### 007 llm-gateway-resilience（4）
- **韧性接线错位**：`get_llm_client_by_model_id` 只被模型连通性测试路由调用；真实对话链路 `dsh_runtime/model_gateway/service.py:179` 直接 `build_llm_client_from_config`，绕过 `wrap_resilient`。
- **FR-7/11/13 事件字段端到端断裂**：`ResilientLLMClient` 未覆写 `consume_invocation_record` → 读取方恒得 `None`，`failover_from/to` 永远为空。
- **FR-12 取消信号未实现**：`resilience/` 与 `instrumented_client` 无 `CancelledError` 处理，取消被归类为可重试错误。
- **US3 流式绕过退避**：`astream` 路径无 `retry_with_backoff`。

### 008 ops-dashboard（3）
- **成本维度后端死代码**：`build_cost_section`/`forecast_cost`/`attribute_cost` 在生产 `app/` 零调用；`/overview` 不返回 `cost` 段。
- **前端成本页消费的是 trend 瓶颈数据**（自述注释），`costShare` 前端重算。
- **部门/智能体分摊缺失**：`agent_id` 无数据源（`TokenUsageRecord` 无该字段）。

### 009 hooks-interception（3）—— **①② 已修（2026-10-03，见 WORK_LOG 续十二）**

> ① `tool` 真值：**工具级 PreToolUse 已挂到真实工具调用点**——chat-api 的
>    `EnterpriseToolService._authorize`（工具网关 `POST /internal/dsh/tools/execute` 与
>    `/approval/request`）经 `run_pre_tool_use` 用真实 `toolName` + `arguments` 求值同一套
>    声明式规则；按工具名配置的 `deny_tool`/`require_field` 在**执行时刻**真正命中。
>    turn 级调用点（`dsh_chat`/`dsh_execution`）保留 dsh_turn 语义但补传了 `request`。
> ② `require_field` 可用：工具网关传真实 arguments；规则源加 per-tenant 2s TTL 缓存
>    （含负缓存）——热路径不再每次查 Mongo。
> ③ **仍待修**：FR-3 超时与 FR-13 延迟预算（`guard.py`/`timeout.py`）仅 tests 调用，
>    生产未接线。五事件仍只落地 PreToolUse。
- **`tool` 恒为 `"dsh_turn"`**：两个生产调用点硬编码，按工具名配置的 `deny_tool`/`require_field` 永不命中。
- **`require_field` 恒不可用**：两处调用均未传 `request=` → `payload` 恒空。
- **FR-3 超时与 FR-13 延迟预算零接线**：`guard.py`/`timeout.py` 仅 tests 调用。
- 附带：五事件只落地 PreToolUse。

### 010 dag-orchestration-engine（4）
- **核心零生产调用方**：`grep orchestration` 排除自身后仅命中一条注释；`DeepDiveOrchestrator` 仅 tests 引用。
- **唯一场景无产品入口**：无路由、未注册 capability、未从 `research/__init__` 导出。
- **FR-6 失败阻塞被绕过**：`competitor_deep_dive` 用 `_FailedNodeOutput` sentinel 伪装 success（其 docstring 自承）。
- 附带：早阻塞竞态、FR-7 审计无落库、FR-8 `dag_definitions` 不存在。

### 011 dream-cycle-self-evolution（4）
- **经验片段无持久化**：每 pass 新建内存 `FragmentStore()`；实测两次 pass 输出逐字节相同 → 跨 pass 无状态。
- **草稿/MR 不落库、无消费方**：`draft_ids` 只进返回 dict，从不调 004 `skill_lifecycle`。
- **MR 判定不走 `mr.py`**：`run_once` 用 `cluster.is_mr_eligible()`，`mr.py` 的 `generate_improvement_mr` 零调用。
- **淘汰链路输入无人提供**：`deprecations`/`restorations` 仅测试传，生产 `_loop` 不传；`record_exposure/adoption` 零生产调用。

### 012 a2a-agent-gateway（4）
- **入站面完全缺失**：无 `jsonrpc.py`、无 `api/endpoints/a2a.py`、`main.py` 未注册。
- **核心符号零生产调用方**：`from app.a2a` 仅命中 tests；`A2AClient(` 生产 0 处。
- **产出无消费方**：`AgentCard.as_dict()` 零外部调用；`/a2a/{tenant}/{id}` 无路由承接。
- **FR-6 双向门禁零接线**：a2a 内 governance 字样全是注释。

### 013 multi-im-entry（5）
- **零生产 import**：`from app.im_gateway` 在 `app/` 0 命中；全部 `ChannelRouter(` 实例化在 tests。
- **无入口 endpoint**：plan 要求的 `im_channels.py` 不存在，`main.py` 未注册 IM/webhook 路由。
- **无持久化**：`im_channels`/`im_session_bindings` 0 命中，`SessionBindingRegistry` 是进程内 dict。
- **webhook 接收端不存在** → 签名校验无保护对象。
- 附带：审计默认 sink 与代码不符、001 门禁依赖悬空。

### 014 business-semantic-index（4）
- **两套实现均零生产调用方**：`business_index` 包与 `services/business_semantic_index.py` 仅 tests 导入。
- **无输入来源**：plan 承诺的 `connectors/`、`entity_extract.py`、`incremental.py` 全部不存在。
- **产出无消费方**：`source_attribution`/`join_cross_system` 输出全仓零读取。
- **FR-9 权限零接线**：`bizdata` 全仓 0 命中。

### 015 knowledge-graph-layer（6）
- **零生产 import**（仅 tests）。
- **FR-10 存储承诺落空**：进程内 dict，`kg_nodes`/`kg_edges` 全仓 0 命中，包内 0 处 mongo 导入。
- **FR-1 抽取入口缺失**：无 `extract.py`，节点只能手工构造，`confidence` 恒 1.0。
- **FR-13 对齐是死字段**：`source_ref` 无生产读写，`biz_entities` 0 命中。
- **FR-2/8/9 无消费面**：无入口、不参与 RAG、`kg:read` 与 `kg_max_hops` 不存在。
- 附带：审计 fail-open 且测试断言恒真。

### 016 skill-market-hardening（6）
- **灰度/回滚整轴 zempty**：`evaluate_canary`/`apply_rollback` 生产零调用，无路由/调度/持久化。
- **plan 的 `skill_rollouts`/`skill_metrics` 集合从未创建**。
- **FR-7 审计大概率不落**：`scoring.py` 的 bridge import 被 `try/except ImportError` 吞掉。
- **FR-11 人工恢复无生产入口**。
- **FR-1/2 监控查询与异常下钻缺消费方**，耗时维度无采集。
- 附带：success 归因口径为会话级近似。

### 017 three-scope-memory（4）
- **`app.memory` 零生产导入**（仅 tests）。
- **plan 承诺的 endpoint/store/promote/sediment 全缺失**。
- **无 `memories` 存储** → 记忆无法写入或读取。
- 附带：会话沉淀与 RAG 接线不存在。

### 018 capability-asset-registration（5）
- **零生产调用方**：六个核心符号 grep 全 0；`CapabilityAssetRegistry(` 仅 tests（`db=None`）。
- **discover→register 链路断裂**：分属两服务且互不调用。
- **无输入来源**：无 OpenAPI/MCP 扫描器，只接收手工传入的 iterable。
- **治理视图无消费方**。
- 附带：`a2a_exposed` → 012 未接线。

### 019 harness-elastic-config（4）
- **两处生产调用点均未传 `request=`** → `harness_mode` 恒 `thick`，薄模式不可达。
- **`ProfileResolver` 零生产调用方**，`harness_profiles` 存储不存在。
- **产出无消费方**：`run_gate_plan` 返回值被丢弃，`skipped_layers` 不驱动任何跳过（审批/配额照跑）。
- **FR-7/FR-9 未实现**：无 CRUD 端点、无变更审计、无 RBAC 约束。

### 020 platform-multi-tenancy（3）
- **FR-035/036/037 未贯通**：chat-api `assert_quota_available` 无 `unlimited` 短路，`get_quota_summary` 无 `unlimited` 键 → 新租户成员发消息返回 402（供给侧只写 `points_unlimited`，chat-api 不读）。
- **plan 的"消除 114 处 `or \"default\"`"未执行**，数量增至 123。
- **FR-032 清理进度只存进程内存**，多副本/重启即丢（仓库注释自承）。

## 跨特性系统性模式（比单点缺口更重要）

1. **"纯逻辑孤岛"**：9 个 hollow 特性全为同一形态——`app/<feature>/` 内有完整的类/函数 + 单测，但**无任何 `app/` 业务路径 import**。测试通过率完全不能证明落地。
2. **"写了没人读"**：001 `gate_events`、004 release 列表、008 成本段、018 治理视图、003 锚点——产出有写入方但零消费方。
3. **"参数没人传"**：001 配额 resolver、009 `request=`、019 `harness_mode`、011 `deprecations`——接口定义了但生产调用点不提供。
4. **"标注未启用却当已完成"**：001 chat-api 侧 `gate_adapter` 明确注释 gatekeeper 未启用，而 INDEX 记为"已实现核心"。
5. **`tasks.md` 勾选系统性失真**：16 份 tasks 全 100% 勾选，与上述事实矛盾，**不能再作为落地证据**。

## 修正后的 SDD 状态口径

- **spec / plan / checklist / tasks 完成度**（文档层面）：维持 INDEX 原记录，**这一层是可信的**。
- **实现落地度**（本文新增维度）：`landed` 0 · `partial` 10 · `hollow` 9。
- **`specs/INDEX.md` §五 的"19 个特性全部已有实现核心/MVP"结论已被本文推翻**，后续引用应以本文为准。

## 建议的收敛顺序（按"缺口性质"而非特性编号）

1. **P0 修复"有链无源/无消费方"的真功能**（否则等于未实现）：001 的 RBAC 角色源、配额 resolver、PII 生效链路、审批恢复；002 的秘密过滤与审计；009 的 `tool` 真值与 `request=`。
2. **P0 接通"最后一公里"**：011 经验/草稿落库、003 锚点入向量库、004 审计与版本回看消费方、008 成本段与指标写入方。
3. **P1 纯逻辑孤岛接线或明确降级**：010/012/013/014/015/017/018/019 —— 要么接生产入口，要么在 spec 里显式降级为"未实现（设计已就绪）"，**不得再标"已实现核心"**。
4. **规格回写**：把上表与高危缺口回写各 spec 的 checklist/implementation，并统一口径（plan 声称的集合/端点若不存在，应订正或标注为待建）。

## 检查完成度声明（本轮边界）

**已覆盖**：
- `specs/` 下全部 20 个特性的落地判定（`landed` 0 / `partial` 10 / `hollow` 9）；
- 每个 hollow/partial 特性的高危缺口清单（含 `file:line`/grep 证据）；
- 14 条简单事实的独立抽查 + 6 条复杂推理链的逐环节深挖 + 1 条反向验证（确认无 landed 误判）；
- 结论回写到 16 份 `tasks.md` / 20 份 `checklists/requirements.md` / 011 `implementation.md`；
- 订正 `INDEX.md` 的失实结论并加口径提示。

**未覆盖（属"修复"而非"检查"）**：
- 未修改任何业务代码；
- 未逐条修复上表缺口，也未为修复排期；
- 判定基于静态代码核查（grep/阅读），未启动服务做运行时验证（本机 admin-api 的 `.venv-test` 与
  `motor` 在 Python 3.14 下不兼容，裸 import 不可行，仅 pytest 环境可用）。

**判定口径的可复现性**：所有结论的证据都是 `file:line` 或 grep 命令，任何人可按表复跑。
