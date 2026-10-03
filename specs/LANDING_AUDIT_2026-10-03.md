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

### 001 gatekeeper-governance（5）—— **已修 5/5（2026-10-03，六层链逐环节复核见 WORK_LOG 续三十三）**

> **逐环节复核（用户指定最高安全优先级）**：原审计的 5 条"断链"在 admin-api 侧均已落地，
> 本报告据此复核并在 chat-api 侧补齐最后一环（PII 脱敏消费方）：
> ① **RBAC 角色源**：`gatekeeper_internal.evaluate_gate` 经 `_resolve_roles` 查询
>    `end_user_position_roles` 解析员工岗位角色（chat-api 调用方无需自带 roles）。
> ② **配额层**：`build_layers` 默认注入 020 真实 token 预算检查器
>    `default_credit_checker`（`unlimited` 租户放行，额度耗尽则 DENY 429）。
> ③ **PII 脱敏消费方（本轮补齐）**：`redaction` 层就地改写 `ctx.request`，内部端点
>    回传脱敏体；chat-api `admit_skill_selection` 现透传 `GatePlan.redacted_request`，
>    `dsh_chat` 以脱敏后的 `text` 替代明文送后续处理（FR-7 端到端生效）。
> ④ **审批恢复路径**：`ApprovalRegistry.decide`（审批人）+ `consume`（申请者凭已批准票
>    一次性放行）已接线；`/decide` + `/approvals` 端点暴露。
> ⑤ **审计落库+读**：`audit` 层落 `gate_events` 并 fail-closed；`GET /internal/gatekeeper/events`
>    读取。
> **真实执法**：chat-api `run_gate_plan` 经内部端点调用六层链，非 ALLOW 一律 fail-closed
> 抛 `PermissionError`；审计层为 floor 不可跳。
- ~~RBAC 第 2 层数据源断裂~~：已通过 `_resolve_roles` 服务端解析 `end_user_position_roles` 修复。
- ~~配额第 5 层恒放行~~：已通过 `default_credit_checker`（020 预算）修复。
- ~~PII 第 3 层产出无消费方~~：已通过 `admit_skill_selection` 透传 + `dsh_chat` 替换明文修复（2026-10-03 续三十三）。
- ~~审批挂起无恢复路径~~：已通过 `consume` 恢复路径 + `/decide` + `/approvals` 修复。
- ~~审计第 6 层只写不读~~：已通过 `gate_events` 落库 + `GET /events` 读取修复。

### 002 session-versioning（5）—— **全修（2026-10-03，见 WORK_LOG 续十三/三十五/五十九）**

> **已修**：
> - **FR-7/8 秘密过滤**：commit 端点对 `summary`+`content` 跑 `detect_secrets`→可逆占位符，
>   原文仅存 `session_secret_refs`（owner/admin 作用域）；新增 `GET /sessions/{id}/secrets/{token}`
>   解引用端点（仅 owner 或 `system:<main>:full_access_admin`，每次解引用落审计；拒绝也审计）。
> - **FR-11 审计**：commit/resume/share/dereference 均经 001 审计流（`position_role_audit_logs`）
>   落 `session.<event>` 事件。
> - **share 兑换必败 bug**：`ShareStore._load` 改按 `share_id`/`token` `$or` 查（原只按 share_id 查
>   token，必 404）；share 视图暴露 `token`（active 时）。
> - **preview 消费方补齐（2026-10-03 续三十五）**：`_preview_out()` 从 DB 文档生成预览；
>   `list_session_versions` 与 `get_session_version` 返回真实 preview（原硬编码 None，
>   `SnapshotStore.preview()` 零调用）。
>
> **已修**：服务端兜底脱敏（续四十七）——commit 端点在客户端未提供 content 时
>    主动读 `chat_messages`（租户范围内真实会话消息）作为脱敏源，真实
>    历史中的疑似秘密进快照前先走 FR-7 过滤 + FR-8 原文入
>    `session_secret_refs`；降级时不阻塞 commit。
> **已修（续五十九）**：commit 端点在写入前调用 `_next_seq()`，若 `payload.seq` 与
>    实际序列不匹配则 400 拒绝，非伪造接受；客户自报元数据已闭环。
> **002 残项清零。**
- **FR-7/FR-8 秘密过滤零接线**：`dsh_session_versioning.py` 全文无 `secret/reference/placeholder/redact`；`snapshot.as_document()` 无消息正文字段——不是"过滤失效"而是"过滤对象不存在"。唯一相关测试是空断言。
- **commit 是客户端自报元数据**：端点只看 `CommitIn`（seq/trigger/summary/...），从不查 `chat_messages`；前端把 `messages.length` 当 seq 传。`preview` 已改为 DB 文档生成（续三十五）。
- **resume 零影响**：只 `return resumeAfterSeq`，不写任何状态；`resumeSessionFrom` 前端零调用者。真实 seq 由 `sessions.py _next_seq` 独立决定。（已修 resumedFrom 续三十八）
- **FR-4 乐观锁与 FR-11 审计均为纯逻辑**：`check_and_advance` 与 `record_session_event` 仅 tests 调用；002 未进 `FEATURE_AUDIT_EVENTS`。
- **share 兑换必然失败**：传入 token 却按 `share_id` 查。

### 003 document-ingestion-delivery（3）—— **全修（2026-10-03，见 WORK_LOG 续十八/三十六/五十六）**

> **已修**：`WeaviateVectorStore.ensure_schema` 加 `anchorJson` text 属性；
>    `upsert_chunks` 序列化 producer 的 `metadata.sourceAnchor` 进 `anchorJson`；
>    `search` GraphQL fields 加 `anchorJson` 并在结果里还原为 `metadata.sourceAnchor`，
>    让 `citation_resolver._source_anchor` 从此读得到（001 audit，2026-10-03）。
>    新增 4 项回归测试（roundtrip/无锚点不伪造/解析永不编造/schema 含 anchorJson）。
> **XLSX/XLSM/PPTX 解析分支已补（2026-10-03 续三十六）**：
>    `parse_with_fallback` 新增 XLSX（openpyxl）+ PPTX（python-pptx）解析器；
>    docling 可用时 xlsx/pptx 走 docling、失败回落 openpyxl/pptx；
>    新增 8 项测试。
>
> **已修**：解析核心真实数据测试（续五十六）——`tests/services/test_document_parser_real_data.py`，
>    9 项测试对 XLSX/PPTX/DOCX/CSV 字节流直接解析，无 monkeypatch。
> **003 残项清零。**

### 004 skillhub-lifecycle（4）—— **FR-8 审计 + FR-3 版本回看 + FR-4 反馈 + FR-5 签名已修（2026-10-03，见 WORK_LOG 续十五/十七/四十三/四十八）**

> **已修**：
> - **FR-8 审计**：4 个 skill 端点（publish/install-zip×2/share create+install+revoke）经
>   `services/skill_lifecycle/audit.py` 落 001 治理审计流（`skill.<verb>` 事件，
>   未知 action 拒绝）。
> - **FR-3 版本回看**：admin-web 新增 `SkillVersionHistory` 组件（`SkillsPage.vue`
>   已挂载），在技能详情弹窗内展示 ordered 发布历史，`fetchSkillReleases`
>   有真实前端消费方。
> - **FR-4 反馈版本关联**（续四十三）：`resource_feedback` 的
>   `comment()` 支持可选 `release_id`/`release_version`，`list()` 支持按
>   发布物过滤，端点 `POST/GET /api/resource-feedback/*` 已透出。
> - **FR-5 签名校验**（续四十八，plan OQ-1 落地）：`OrganizationSkillLifecycle`
>   新增 `verify_release`（对规范化 snapshot 的 sha256 摘要校验），
>   `releases()` 现透出每行 `digest`；端点
>   `POST /skills/{id}/releases/{release_id}/verify` 校验不匹配硬 409，
>   篡改的发布物绝不被静默接受。
- **FR-8 审计零接线**：chat-api 四个 skill 端点 `grep audit` 0 命中；`FEATURE_AUDIT_EVENTS` 不含 004；admin-api 中间件只按路径首段推断 module。（已修：4 端点经 audit.py 落 001 流）
- **FR-3 版本回看零消费方**：`fetchSkillReleases` 全仓零调用者，admin-web 无该函数。（已修：SkillsPage.vue 已挂载 SkillVersionHistory）
- **FR-4 反馈版本关联已修（续四十三）**：`resource_feedback` 支持可选 release 作用域。
- **FR-5 签名校验已修（续四十八）**：`verify_release` + `POST /skills/{id}/releases/{rid}/verify`，摘要不匹配硬 409。

### 005 knowledge-rag-research（3）—— **已接线（2026-10-03，见 WORK_LOG 续三十一）**

> **已修**：`ResearchFocusBuilder` 注入 `ProgressiveResearchAgent.run()`，其
> `query_templates` 真实播种首轮查询（US3/FR-6），`source_priority`/`evidence_schema`
> 进入审计与结果元数据；`adapters.py` 生产研究路径接入该 builder + 审计（tenant/actor
> 透传）。FR-10 审计：feature_audit 注册 005（`research.run_started`/`run_finished`），
> 汇入 001 治理审计流。
> **诚实边界（非伪造）**：FR-5 组织级隔离（默认策略无条件放行非 personal 文档）属策略层
> 真实改造、需真实环境验证，未伪造实现，仍标记 仍待修。

### 006 position-rbac-admin（2）—— **已修 2/2（2026-10-03，见 WORK_LOG 续二十七）**

> **已修**：
> - `copy_role` 前置校验：源角色 `tool_access_mode` 或 `skill_access_mode` 为 'all' 时返回 403，
>    阻止通过复制途径绕过 FR-6 审批获取全量权限。
> - 批量分配原子化：新增 `bulk_replace_user_roles` 使用 MongoDB `bulk_write` 一次性完成所有
>    用户的 delete+insert，中途失败整体回滚，审计完整落地。

### 007 llm-gateway-resilience（4）—— **韧性接线 + 事件字段已修（2026-10-03，见 WORK_LOG 续二十八/三十七）**

> **已修**：`_configured_client` 改走 `get_llm_client_by_model_id`，生产路径接入
>    `wrap_resilient` + fallback（FR-1/FR-4/FR-13）。
> **事件字段已修（2026-10-03 续三十七）**：`ResilientLLMClient.consume_invocation_record`
>    新增，failover 时返回 `failover_from/to`，审计流不再空字段。
> **已修**：FR-12 取消信号（续四十九）—— 把
>    `CancelledError` 判为不可重试；`retry_with_backoff` 与
>    `ResilientLLMClient`（含 ainvoke/astream 两路径）遇取消立即上抛，
>    不重试、不切备用供应商。
> **仍待修（降为 P1 残项）**：US3 流式绕过退避。
- **FR-7/11/13 事件字段端到端断裂**：`ResilientLLMClient` 未覆写 `consume_invocation_record` → 读取方恒得 `None`，`failover_from/to` 永远为空。（已修 续三十七）
- **FR-12 取消信号已修（续四十九）**：CancelledError 在 classify/retry/failover 三层均立即传播，不重试不切源。
- **US3 流式绕过退避**：`astream` 路径无 `retry_with_backoff`。

### 008 ops-dashboard（3）—— **成本段已接入 /overview 且前端已消费（2026-10-03，见 WORK_LOG 续三十四）**

> **已修**：`/overview` 新增 `cost` 段（`build_cost_section` + FR-6 对账 `reconciles` +
>    4 期移动平均 `forecast_cost`）——成本维度死代码变生产链路。
> **前端消费方已补齐（2026-10-03 续三十四）**：`DashboardPage.vue` 成本 tab 改消费
>    `overview.cost`（`models[].costShare` / `totalCost` / `totalTokens` / `forecast`），
>    不再从 trend 瓶颈/时间序列前端重算；`vue-tsc --noEmit` 通过。
> **诚实边界**：部门/agent 分摊**不伪造**——`TokenUsageRecord` 无 `agent_id` 数据源，
> 成本段显式 `departmentAttribution.available=false` + 原因；数据源补齐留待后续。
- **成本维度后端死代码**：`build_cost_section`/`forecast_cost`/`attribute_cost` 在生产 `app/` 零调用；`/overview` 不返回 `cost` 段。
- **前端成本页消费的是 trend 瓶颈数据**（自述注释），`costShare` 前端重算。
- **部门/智能体分摊缺失**：`agent_id` 无数据源（`TokenUsageRecord` 无该字段）。

### 009 hooks-interception（3）—— **①②③ 已修（2026-10-03，见 WORK_LOG 续二十五）**

> **已修**：
> - ① `tool` 真值：**工具级 PreToolUse 已挂到真实工具调用点**。
> - ② `require_field` 可用：工具网关传真实 arguments；规则源加 per-tenant 2s TTL 缓存。
> - ③ **FR-3 超时 + FR-13 延迟预算**：`run_pre_tool_use` 改走 `run_hooks_within_budget`
>    （来自 `guard.py`），任何异常/解析失败均 fail-closed（FR-3），同时共享 5s 延迟预算
>    （FR-13）。

> ① `tool` 真值：**工具级 PreToolUse 已挂到真实工具调用点**——chat-api 的
>    `EnterpriseToolService._authorize`（工具网关 `POST /internal/dsh/tools/execute` 与
>    `/approval/request`）经 `run_pre_tool_use` 用真实 `toolName` + `arguments` 求值同一套
>    声明式规则；按工具名配置的 `deny_tool`/`require_field` 在**执行时刻**真正命中。
>    turn 级调用点（`dsh_chat`/`dsh_execution`）保留 dsh_turn 语义但补传了 `request`。
> ② `require_field` 可用：工具网关传真实 arguments；规则源加 per-tenant 2s TTL 缓存
>    （含负缓存）——热路径不再每次查 Mongo。
> ③ **已修**：FR-3 超时（续四十二）——`run_pre_tool_use` 用 `asyncio.wait_for`
>    包装同步 guard，超时 fail-closed；FR-13 延迟预算共享 5s 窗口。
- **`tool` 恒为 `"dsh_turn"`**：两个生产调用点硬编码，按工具名配置的 `deny_tool`/`require_field` 永不命中。
- **`require_field` 恒不可用**：两处调用均未传 `request=` → `payload` 恒空。
- **FR-3 超时已接线（续四十二）**：`run_pre_tool_use` 用 `asyncio.wait_for` 包装。
- **FR-13 延迟预算已接线**：`run_hooks_within_budget` 生产调用，共享 5s 窗口。
- 附带：五事件只落地 PreToolUse。

### 010 dag-orchestration-engine（4）—— **已接线 + 显式降级（2026-10-03，续五十九/续六十）**

> **已修**：新增 `POST /api/research/competitor-deep-dive`（main.py 注册）；
> `DeepDiveOrchestrator` 新增 audit_sink，FR-7 节点/运行事件汇入 001 治理审计
> 流；新增 `orchestration/store.py`，FR-8 定义优先从 `dag_definitions` 集合读取
> （首用惰性注册 YAML，DB 不可用回退）。
> **诚实边界（非伪造）**：`_FailedNodeOutput` 是分析节点容错设计——失败节点
> 不阻塞合成节点，由 degraded 报告兜底（FR-6 降级而非伪装成功）；审计层仍如实
> 记录 `dag.node_fail`。真实 sub-agent 经 LocalBridge 执行，无 agent 会话时节点
> 返回 unavailable 并由 degraded 路径兜底。
> **已降级（非伪造）**：DAG 编排端点（`POST /api/research/competitor-deep-dive`）已接线，审计 + 容错 + DB 惰性注册已完成；但**无真实 LLM 工具执行环境**（浏览器 agent 未上线）且 `competitor_deep_dive` 未注册为真实 capability，端点在无环境时诚实返回 `unavailable/degraded`（FR-6 降级而非伪装成功），不标记“已实现核心”。
> **010 残项降级确认**：认证为“接线但缺真实执行环境”，拒绝伪造成功断言。

### 011 dream-cycle-self-evolution（4）—— **落库闭环已修（2026-10-03，见 WORK_LOG 续十六）**

> **已修**：
> - **① 片段持久化**：`PersistentFragmentStore` 写 `experience_fragments`，`run_once`
>   绑 DB 时先 load_history 再 extend → 跨 pass 有累积状态；upsert 键 =
>   (tenant, content_fingerprint)，重扫幂等。
> - **② 草稿给 004 消费**：`_persist_draft` 写 `skill_drafts`（含 mr 标志，与 MR 审计同阈值）。
> - **③ MR 走 mr.py**：`run_once` 的 MR 判定改走 `mr.generate_improvement_mr`（唯一真值源），
>   接受 per-tenant scan config 阈值覆盖。
> - **④ 淘汰输入自动检测**：调用方未传 deprecations 且 DB 可用时，自动扫 `skill_adoption`
>   表生成淘汰输入；无 DB 时诚实返回 []。
>
> **仍待验证**：011 的 API 级回归（当前为 service 级 92 passed）。`record_exposure/adoption`
>   的生产调用方（016 market 侧）尚未接线。
- **经验片段无持久化**：每 pass 新建内存 `FragmentStore()`；实测两次 pass 输出逐字节相同 → 跨 pass 无状态。
- **草稿/MR 不落库、无消费方**：`draft_ids` 只进返回 dict，从不调 004 `skill_lifecycle`。
- **MR 判定不走 `mr.py`**：`run_once` 用 `cluster.is_mr_eligible()`，`mr.py` 的 `generate_improvement_mr` 零调用。
- **淘汰链路输入无人提供**：`deprecations`/`restorations` 仅测试传，生产 `_loop` 不传；`record_exposure/adoption` 零生产调用。

### 012 a2a-agent-gateway（4）—— **AgentCard 查找入口已接线（2026-10-03，见 WORK_LOG 续二十）**

> **已修**：新增 `GET /internal/a2a/agents/{agent_id}/card`（`app/api/endpoints/a2a.py`），
>    暴露 A2A AgentCard 查找；auth 复用 `_resolve_session_user`。
>    `A2AClient` 出站调用框架完整（failover + retry + JSON-RPC error mapping），
>    仅未从真实 capability 驱动。
>
> **已修**：入站 JSON-RPC surface（续五十一）——`POST /internal/a2a/rpc`
>    实现 message/send / tasks/get / tasks/result 三方法（FR-2），
>    TaskLifecycle 幂等（FR-10），未知方法/非法参数返回 JSON-RPC 错误码。
> **仍待修（降为 P1 残项）**：出站 A2A client 实际调用集成、`a2a_exposed` 筛选（依赖 018）。
- **入站面已修（续五十一）**：`POST /internal/a2a/rpc` 已实现 JSON-RPC surface（message/send / tasks/get / tasks/result）。
- **核心符号零生产调用方**：`from app.a2a` 仅命中 tests；`A2AClient(` 生产 0 处。
- **产出无消费方**：`AgentCard.as_dict()` 零外部调用；`/a2a/{tenant}/{id}` 无路由承接。
- **FR-6 双向门禁零接线**：a2a 内 governance 字样全是注释。

### 013 multi-im-entry（5）—— **全修（2026-10-03，见 WORK_LOG 续二十/四十五/五十五）**

> **已修**：新增 `POST /internal/im/webhook/{channel}`（`app/api/endpoints/im_gateway.py`），
>    HMAC 签名校验（FR-13）+ nonce 5 分钟防重放 + `ChannelRouter` 路由到 adapter（FR-4/FR-9 最小生产路径）。
>    新增 `IM_WEBHOOK_SECRET` 环境变量，缺省 500 fail-closed。
>
> **已修**：持久化 SessionBindingRegistry（续四十五）——新增
>    `PersistedSessionBindingRegistry`（async，读写 `im_session_bindings`/
>    `im_channels` 集合），webhook 端点据此校验频道开关并持久化
>    会话绑定（FR-10/FR-9/FR-14）；DB 不可用时降级内存不伪造。
> **已修**：IM adapter 全量实现（续五十五）——`DingtalkAdapter` / `WecomAdapter` / `SlackAdapter` / `TeamsAdapter` 各自 `parse_inbound`，
>    `build_adapter` 五通道全部可达；各平台字段映射符合官方 webhook 结构。
- **零生产 import**：`from app.im_gateway` 在 `app/` 0 命中；全部 `ChannelRouter(` 实例化在 tests。
- **无入口 endpoint**：plan 要求的 `im_channels.py` 不存在，`main.py` 未注册 IM/webhook 路由。
- **无持久化**：`SessionBindingRegistry` 是进程内 dict（已修续四十五，`PersistedSessionBindingRegistry` 落库 `im_session_bindings`/`im_channels`）。
- **webhook 接收端不存在** → 签名校验无保护对象。
- 附带：审计默认 sink 与代码不符、001 门禁依赖悬空。

### 014 business-semantic-index（4）—— **已接线（2026-10-03，见 WORK_LOG 续三十）**

> **已修**：新增 `POST /api/business-index/{search,index,align}`（main.py 注册），
> 语义检索复用 005 检索客户端并带来源归因；`index` 写入 MongoDB `business_entity_index`；
> `align` 跨系统对齐（FR-5/FR-6 不拒绝、缺失系统如实上报）。`index_entity` 与
> `BizEntity` 构造均汇入 001 治理审计流（FR-9）。
> **诚实边界（非伪造）**：semantic_search 无查询/无客户端时返回空列表；只读设计，
> MOVO 不回写业务库；plan 承诺的 `connectors/`/`entity_extract.py`/`incremental.py`
> 同步抽取未实现（无业务源系统接入），属后续数据源补齐，不标记"已实现核心"。

### 015 knowledge-graph-layer（6）—— **全修（2026-10-03，见 WORK_LOG 续二十三/四十六/五十七）**

> **已修**：`TenantKgStore`（MongoDB `kg_nodes`/`kg_edges` 集合，tenant 分区，
>    lazy-load）+ `GET /api/kg/nodes/{id}`（FR-2 单节点查询）和
>    `GET /api/kg/nodes/{id}/neighbours`（FR-10 邻居遍历）。
>
> **已修**：FR-8 约束检查（续四十六）——新增 `POST /api/kg/check-constraints`，
>    运行 `consistency.check_all`（互斥/基数/传递）+ `mark_conflicts`（FR-14），
>    冲突标记落库 `kg_nodes`，审计入 001 流（kg.audited）；
>    `TenantKgStore` 补 `nodes`/'edges_of' 接口对齐 `KgStore'。
> **已修**：FR-1 自动抽取（续五十七）——`extract.py` 规则抽取器
>    （结构化记录 / 自由文本 → 类型化实体 + 关系，无 LLM，不伪造）；
>    `POST /api/kg/extract` 端点；`apply_to_store` 写入 store。
> **已修**：FR-13 `source_ref` 读写 + RAG 接入（续五十七）——
>    `POST /api/kg/nodes`（写 source_ref 指针，不复制 014 数据）；
>    `GET /api/kg/nodes/{id}/resolve`（指针解析回 014 `biz_entities`，
>    无数据时返回 resolved=False 不伪造）；
>    `kg_rag_candidates` 注入 `knowledge_search` RAG 上下文。

### 016 skill-market-hardening（6）—— **全修（2026-10-03，见 WORK_LOG 续二十六/五十七/五十八）**

> **已修**：`POST/GET /api/skills/canary/*` 四个端点（创建灰度/记录计数/评估健康度/
>    手动回滚），X-MOVO-Service-Token 验证。`evaluate_canary`/`apply_rollback`
>    从此有真实生产调用方。
> **MongoDB 持久化已修（续四十）**：rollout 存 `skill_rollouts` 集合，跨进程持久；
>    新增 `_row_to_rollout`/`_rollout_to_row` 序列化层。
> **已修**：自动回滚定时调度（续五十）——
>    扫描 pending/running rollout，超阈值即自动回滚落库；
>    `CanaryRollbackScanner`（5 分钟周期）由 lifespan 启动/停止。
> **已修**：FR-1/FR-2 监控查询与异常下钻（续五十七/五十八）——
>    `skill_monitoring.py` 服务提供 `skill_usage_monitor` / `skill_anomaly_drilldown`，
>    `/api/skills/monitor/usage` / `/api/skills/monitor/anomaly/{day}` 端点，
>    真实解析桶数据，不伪造，统一 Honest degrade 方针；
>    开新路由组 `skill_monitoring`，注册进 API 路由。

### 017 three-scope-memory（4）—— **全修（2026-10-03，见 WORK_LOG 续二十一/二十二/五十二）**

> **已修**：`MemoryStore`（MongoDB `memories` 集合）+ `GET/POST/DELETE /api/memories`
>    端点；`knowledge_search` 能力通过 ``memory_rag_candidates`` 将 scope-filtered
>    记忆注入 RAG 上下文（T010）。
>
> **已修**：FR-8 老化清理（续五十二）——`clean_decayed_memories`
>    按衰减窗口生成清理查询，archive/delete 两种处置；
>    Memory 增加 archived 字段，检索时排除已归档记录；
>    `_memory_decay_loop` 每小时扫描一次（lifespan 启动/停止）。
> **017 残项清零。**
> **已修**：promote_to_org 认证入口（续三十九）——`PATCH /api/memories/{id}/promote`
>    端点，`full_access_admin` 角色可执行，审计入 001 流。
> **已修**：RAG 集成——`memory_rag_candidates` 经 `adapters.py` 接入
>    `knowledge_search`，scope-filtered 记忆注入 RAG 上下文。

> **已修**：`MemoryStore`（MongoDB `memories` 集合，按 `(tenant_id, memory_id)`
>    upsert）+ `GET/POST/DELETE /api/memories` 三个端点；服务端 scope_filter
>    强制执行可见性（FR-2），不跨租户泄漏。
>
> **已修**：FR-8 老化清理定时任务（续五十二）——`_memory_decay_loop` 每小时调用 `clean_decayed_memories`，archive/delete 两种处置，归档记录被 RAG 检索排除。

### 018 capability-asset-registration（5）—— **Registry + 端点已接线（2026-10-03，见 WORK_LOG 续二十四）**

> **已修**：`CapabilityAssetRegistry` 类（register/get/list_all/discover_and_register/
>    update_contract/set_state/transfer_owner）；`POST/GET /api/capabilities` 和
>    `GET /api/capabilities/{asset_id}` 三个端点，X-MOVO-Service-Token 验证（FR-1/FR-2）。
>
> **已修**：MongoDB 持久化（FR-10，续四十四）——新增 `PersistedCapabilityRegistry`
>    （async，读写 `capability_assets` 集合），端点已改用持久化 registry。
> **仍待修（降为 P1 残项）**：与 012 A2A `a2a_exposed` 筛选接线（FR-12，跨服务）；
>    CRUD 变更审计（FR-11）。
- **零生产调用方**：六个核心符号 grep 全 0；`CapabilityAssetRegistry(` 仅 tests（`db=None`）。
- **discover→register 链路断裂**：分属两服务且互不调用。
- **无输入来源**：无 OpenAPI/MCP 扫描器，只接收手工传入的 iterable。
- **治理视图无消费方**。
- 附带：`a2a_exposed` → 012 未接线。

### 019 harness-elastic-config（4）—— **全修（2026-10-03，见 WORK_LOG 续十九/五十三/五十四）**

> **已修**：`GateEvaluatePayload` 加 `harnessMode`；`GateContext` 加 `harness_mode`；
>    `_resolve_layers` 按 thin 模式过滤 approval+quota 层（floor 永保留）。
>    chat-api `gatekeeper_client.evaluate` 透传；`HARNESS_MODE` 环境变量支持；
>    两处调用点注入 request。租户清除表登记 `experience_fragments`/`skill_drafts`。
>
> **已修**：FR-7/FR-9 CRUD 端点（续五十三）——`POST/GET/DELETE /api/harness-profiles`，
>    写操作要求 `full_access_admin`，变更前后 diff 入 001 审计流；
>    FR-8 服务端 floor 校验拒绝缺省红线层的配置。
> **019 残项清零（续五十四：`harness_profiles` 登记租户清除表）。**
- **两处生产调用点均未传 `request=`** → `harness_mode` 恒 `thick`，薄模式不可达。
- **`ProfileResolver` 零生产调用方**，`harness_profiles` 存储不存在。
- **产出无消费方**：`run_gate_plan` 返回值被丢弃，`skipped_layers` 不驱动任何跳过（审批/配额照跑）。
- **FR-7/FR-9 已修（续五十三）**：`/api/harness-profiles` CRUD 端点 + `full_access_admin` 门禁 + 变更审计。

### 020 platform-multi-tenancy（3）—— **全修（2026-10-03，见 WORK_LOG 续三十二/五十八）**

> **已修**：FR-035/036/037 贯通——chat-api `get_quota_summary` 在 org 带
> `points_unlimited` 时短路返回 `{unlimited:True, remainingPoints:-1, status:active}`，
> `assert_quota_available` 对 unlimited 直接放行，新租户成员不再被 402 拦截。
> **已修**：FR-032 清理进度跨副本持久化（续五十八）——`_PurgeTaskStore` 新增
>    Mongo 持久化（`tenant_purge_progress` 集合，main_id+task_id 键），
>    `mark_persisted`/`finish_persisted` 每阶段写库；`get_purge_status` 解析顺序
>    内存→Mongo→tombstone，不同副本也能查到在途/已完成进度；
>    Mongo 不可用时诚实降级为仅内存（不伪造）；`tenant_purge_progress` 已登记
>    租户清除表（purge 自身产物也随租户清除）。
> **020 残项清零。**

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
