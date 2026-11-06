# Tasks: Three-Scope Memory (personal / project / department) · v3 修订稿

**Input**: [`spec.md`](./spec.md)（v3 修订稿）、[`plan.md`](./plan.md)、[`design-2026-11-05-project-department-scopes.md`](./design-2026-11-05-project-department-scopes.md)（v3 权威设计）、[`rollout-017-d4-cutover.md`](./rollout-017-d4-cutover.md)（D4 发布手册）

**Prerequisites**: spec.md (required), plan.md (required), `specs/049-project-members/` 已落地、`Decisions/ADR-9`

**Status（2026-11-06）**: 决策全部闭环；**B0–B4 代码已落地并通过本地回归，B5 部分、B6 产出脚本/手册但切换未执行，B7 文档已同步、手工/维护窗口项待执行**。`[x]` 仅表示「有代码 + 有测试证据」；需要维护窗口、真实数据库或人工凭据的条目保持 `[ ]` 并注明原因，**不得预勾选**。

**实测基线（2026-11-06）**: chat-api 相关 **275 passed**、admin-api 治理端点 **35 passed**；admin-web / user-web `vue-tsc --noEmit` 均 exit 0；`scripts/migrate_017_scopes.py --self-test` 通过；两服务 `compileall` 通过。

**Checklist Gate**: `checklists/requirements.md` 已按 v3 重写为 Gate 清单（T039 的文档部分），旧版 100% 勾选不再作为依据。

**Organization**: 后端落点 `chat-api/app/memory/`、`chat-api/app/api/endpoints/`、`chat-api/app/enterprise_capabilities/runtime/`、`admin-api/app/api/routes/`；前端 `apps/admin-web/`、`apps/user-web/`；迁移 `scripts/`。

---

## 历史沿革（保留备注，不再作为任务依据）

- 2026-07-08 初版：T001–T011 勾选，后经 [`specs/LANDING_AUDIT_2026-10-03.md`](../LANDING_AUDIT_2026-10-03.md) 判定为 `hollow`（纯函数 + 单测，`app.memory` 零生产导入）。
- 2026-10-05 优化轮：T012–T018 落地密度轴（`tiering/address/sediment` + `store/retrieval/scope` 分层扩展 + 021 `context_space`），生产接线补齐（RAG 适配器 / CRUD / 衰减循环 / 会话沉淀 / 021 端点）。
- **v2 已修正的两处陈旧表述**（本轮不再沿用）：
  - ~~「009 `SessionEnd` → `on_session_end` 是已定义未接线的 seam」~~ → 实际已通过 `dsh_runtime/hooks/dispatcher.py` 接通，`lifecycle.py:85` 注入 `session_id`，`session_persistence_service.py:617-646` 消费；删除会话兜底沉淀在 `sessions.py:1356-1375`（原 T016 引用的 `998-1013` 行号已过期）。
  - ~~「管理端项目管理页无数据」~~ → 049 T004–T008 已修复，2026-11-06 实测网关 `projects-with-usage` 200 / 10 行；017 只做回归（SC-9）。
- 2026-11-05 代码检查发现 **P0 身份解析缺陷**：端点从 `resolve_session_user` 返回字典读取根本不存在的 `user_id` / `role` / `is_workspace_member`，导致 personal 记忆 `owner_id=""` 被同租户任意用户读取、workspace 记忆恒不可见、org 提升恒 403；`test_memory_endpoints.py` 的 12 项端点测试用伪造夹具因而假绿。该缺陷已由 **B1** 修复。

---

## 决策台账（v3 已闭环，执行时不得自行变更）

| 编号 | 裁决 |
|---|---|
| D1/D2 | 项目多人共享；会话默认 `project`（无有效项目上下文回落 `personal`） |
| **D3** | 部门可见性 = 所在部门 + 全部后代、不含祖先 |
| **D4** | `workspace/org → project/department` **直接改名，不设兼容过渡** |
| D5/D6 | 内嵌 `member_user_ids`；admin 同库直读 `projects`（049 已落地） |
| **D7/D8** | N2 `default` 隔离、N1 `project_owner_id` 消歧为**安全必项，不得裁剪** |
| **C-7** | 成员变更审计 `project.member.*` **首期必做** |

---

## Phase B0 — 决策闭环 ✅ 已完成（2026-11-06）

- [x] T001 记录 D3 / D4 / D7 / D8 / C-7 裁决，产出 v3 设计文档「决策闭环台账」（设计文档 §12）
- [x] T002 登记 N1 / N2 为强制安全约束；引用 `Decisions/ADR-9`，不再修订 ADR-8
- [x] T003 把 v3 细化为 `spec.md` 修订稿（A–J FR、SC-1~SC-15、数据流/业务流、落地状态）

## Phase B1 — P0 身份解析修复 ✅ 已完成（2026-11-06）

> 对应 `spec.md` §7 A-2 / A-3 / A-6、§9。**本批次未引入范围改名**，满足 D4「改名须一次性原子切换」的约束。已随提交 `91bf82d8` 推送 `mogo/main`。

- [x] T004 [P] 新增 `chat-api/app/memory/viewer.py`：`MemoryViewerContext`（frozen）+ `build_viewer_context()`（只认真实 `{session, user, tenant_id, org_id}` 契约，不回退 `user_id`）+ `resolve_viewer_context()`（HTTP）+ `resolve_viewer_from_identity()`（RAG，用 trusted ids）+ fail-closed 查询
- [x] T005 修 `api/endpoints/memory.py` 四个端点改走统一上下文；补全 `viewer_org_id` 透传
- [x] T006 修 `api/endpoints/context_space.py` 两个端点改走统一上下文
- [x] T007 修 `enterprise_capabilities/runtime/adapters.py::knowledge_search`：`context.get(...)` 对冻结 pydantic `CapabilityExecutionContext` 必然抛 `AttributeError` 且被 `except` 吞掉 → 改为 `resolve_viewer_from_identity()`；补齐 `viewer_org_id`；让 `memory_candidates` 真正进入返回载荷
- [x] T008 `memory/scope.py::visible_to` 增加空 `viewer_id` / 空 `owner_id` 的 fail-closed 防御（P0 纵深防御）
- [x] T009 [P] 回归测试：`tests/memory/test_memory_endpoints.py` 换真实 auth 契约 + 7 个越权/角色/成员用例；新增 `test_memory_viewer.py`（15 例）、`test_rag_viewer_wiring.py`（2 例）；`tests/context_space/test_context_endpoints.py` 同步换契约 + 透传断言
- [x] T010 实测：017/021 + `knowledge_search` 相关 **171 passed**；交叉回归 **81 passed**；`compileall` 通过

> B1 的 `visible_workspace_ids` / `viewer_org_id` 是过渡字段，已由 **B2/T016** 全量替换。

## Phase B2 — 范围模型 + D4 代码侧全量替换 ✅ 代码已落地（**不发布**）

> 本阶段产出**只在工作区、不上线**；与 B6 的数据迁移必须在同一维护窗口原子切换（J-6 / R15）。

- [x] T011 [P] **D4 全量替换（J-5）**：`MemoryScope` / `Visibility` / `SCOPE_VISIBILITY` / `Memory` dataclass、`sediment.py`、`retrieval.py`、`store.py`、`address.py`、`endpoints/memory.py`、`adapters.py`、`context_space/`、`contracts/memory-context-contract.md`、017 与 021 的 spec/plan/tasks/quickstart。全局扫描确认旧值仅残留在迁移脚本、改名对照与历史说明
- [x] T012 删除 `normalize_scope`、双写、三级字段回退、别名分支、`legacy_alias` 回显；`visible_to` 对未知 scope 直接 fail-closed（B-6）
- [x] T013 `visible_to(memory | dict, MemoryViewerContext)` 为唯一判据；021 `check_memory_visibility` 只转发 `memory_viewer`，不重写鉴权
- [x] T014 `visible_project_keys = {(project_id, project_owner_id)}`（C-1），排除 `"default"` 与 `archived`；写入时固化 `project_owner_id`（N1），`default` 显式 400 / 沉淀回落 `personal`（N2）
- [x] T015 `visible_department_ids`（A-4 / **D3**）：`end_user_org_relations` 不带 `status` 过滤（N3）+ `end_users.primary_org_id` → `org_units.path_ids` 后代展开，不含祖先，跨租户 fail-closed
- [x] T016 [P] `MemoryViewerContext` 补齐 A-1 目标态字段，替换 B1 过渡字段（新增 `project_context.py` 解析会话项目二元组）
- [x] T017 [P] 新增 `tests/memory/test_scope_visibility_v3.py`（21 例）覆盖可见性矩阵、跨租户 / 非成员 / 跨部门 / 同名 `project_id` / `default` 五类越权；**并收紧 admin 短路**：结构性不完整记录（空 owner / 缺 `project_owner_id` / `default`）即使 admin 也不可见

**阶段验收**：SC-4、SC-13 用例通过；SC-15 前半（旧字面量清理）完成。

## Phase B3 — 写入 / 沉淀 / 检索三条链路 ✅ 代码已落地

- [x] T018 `memories` schema 增 `project_id` / `project_owner_id` / `department_id`；`_row_to_memory` 与持久化文档同步
- [x] T019 写入端点：授权字段服务端解析、客户端传值忽略；`actual_scope` / `resolved_from` 回显（无 `legacy_alias`）；旧 scope / 旧字段 `400 scope_invalid`
- [x] T020 **D-6**：新增 `store.update_fields()` 走增量 `$set`，promote 与通用 PATCH 均保留 L0/L1/L2、provenance、`archived`、`project_owner_id`（修 `replace_one` 全量清空）
- [x] T021 会话沉淀 E-1~E-5：`project_context.py` 按 046 会话取值优先级取项目 + 反查 `projects.user_id` 固化二元组；`default` / 歧义 / 缺行回落 `personal`；`ended_at` 幂等；两处生产调用点（`session_persistence_service.py`、`sessions.py`）已接线
- [x] T022 **D-5**：`sediment.py` 四个函数默认注入 `NoopSessionSummarizer()`（原恒不传 summarizer 导致 L0/L1 恒空）；读时 `tier_content` 惰性补全在 store 侧接线并留观测日志
- [x] T023 检索 F-1~F-4：所有调用点传 `viewer=viewer`；`skipped` 非空且原因归类 `archived / unknown_scope / default_project_excluded / missing_project_owner / scope_invisible`；trace 随 payload 返回
- [x] T024 地址 F-5：`mogo://memory/project|department/...` 新段；旧段解析层 `ValueError`、HTTP 层 404；`uri()` 往返一致
- [x] T025 [P] 已落地：新增 `tests/memory/test_full_chain_integration.py` 单文件全链路用例，串联 **写入(create) → 沉淀(sediment) → RAG 检索 → 地址(mogo://memory 解析往返) → 提升申请(request) → admin 审批(approve) → 可见性复核**，并附「invalidated 记忆退出 RAG」分支（SC-5/6/7 由分段 + 该串联用例共同覆盖）。

## Phase B4 — 双端功能 ✅ 代码已落地（E2E 待补）

- [x] T026 admin `/memories`：`routes.ts` 新增路由、`MemoriesPage.vue` + `MemoryDetailDrawer.vue` + `MemoryApprovalDialog.vue` + `MemoryGovernancePanels.vue`（I-1）
- [x] T027 admin 可见范围配置 / 策略 / 配额（I-2）；配套新增 `admin-api/app/api/routes/memories.py` 治理端点（list / stats / detail / archive / restore / delete / approvals / policies）
- [x] T028 `SystemAuditPage.vue` 增加「记忆管理」module 过滤，纳入 `memory.*` 与 `project.member.*`（I-3）
- [x] T029 user 侧栏「我的记忆」：`MyMemoriesPage.vue` + `MemoryViewTabs.vue` + `MemoryDetailDialog.vue`，双 Tab / 搜索 / 增删改 / 提升申请（I-4，**不含成员编辑**）
- [x] T030 两端共用响应契约、分页（`page/page_size`）、错误语义、审计桥；不可见即 404；admin `get_current_admin_user` + 权限码 / user `require_end_user_principal`。**已修复 4 处运行时硬伤**：通用 `PATCH /{id}` 404、promote body/query 错位、user 端分页参数被忽略、admin `resolved_from` 恒缺
- [ ] T031 [P] **部分**：双端 `vue-tsc --noEmit` 均 0 错误、admin 治理端点 35 项单测通过；**真实浏览器 E2E 用例已落地**（`apps/user-web/e2e/memory-promote.spec.ts`、`apps/admin-web/e2e/memories-governance.spec.ts` + 各自 README），但**尚未执行**（需浏览器 + A/B/C/admin 凭据 + 起服，SC-11 用户侧交互待维护窗口验证）。

## Phase B5 — 治理 / 生命周期 / 组织变更 + C-7（部分）

- [x] T032 **C-7（必做）**：在 049 `patch_project` 按 `member_user_ids` diff 挂 `project.member.granted` / `project.member.revoked`；`emit_feature_event("049", ...)`，`update_one` 成功后发；失败只留观测日志不阻断 PATCH；未改 049 鉴权 / 去重 / 500 上限 / `default` 400 / 响应结构
- [x] T033 `feature_audit.py` 白名单：新增 `"049": ("project.member.granted", "project.member.revoked")` 分组 + 扩充 `"017"` 分组；与 T032 同批
- [x] T034 同步 `specs/049-project-members/{spec,tasks}.md`：新增 FR-011 与「017 C-7 增量」节（R16 防覆盖）
- [x] T035 已落地：新增 `app/memory/promotion.py` 状态机（`none→pending→approved|rejected`，owner 申请 / full_access_admin 通过·驳回）；chat-api `POST /{memory_id}/promote/request`（owner 发起，落 pending）；admin-api `GET /approvals`（待审批队列）、`POST /{memory_id}/approve`、`POST /{memory_id}/reject`；`stats.pending_approval` 改计真实 pending 数；前端契约补齐 `requestPromoteMemory` / `fetchAdminPendingApprovals` / `approveMemoryPromotion` / `rejectMemoryPromotion`。单测 `tests/memory/test_promotion_state_machine.py` + 端点用例 `test_promote_request_endpoint.py` 已绿。
- [x] T036 生命周期 H-1：`config.py` 新增 `MEMORY_DECAY_DAYS` / `MEMORY_DECAY_CLEANUP`，`main.py` 衰减循环注入；H-2：`store.list_for_viewer` 命中后按 `lifecycle.touch()` 语义持久化 `last_accessed_at`（失败只留日志）
- [x] T037 已落地：新增 `app/memory/offboarding.py`（`invalidate_user_memories` / `invalidate_project_memories` / `restore_user_memories`，按 N1 口径：`personal` 取 `owner_id`、`project` 取 `project_owner_id`，成员仅贡献的记忆不误伤）；`Memory` 增 `invalidated/invalidated_at/invalidated_reason` 三字段，`visible_to` / `scope_filter` 对 `invalidated` 记忆 fail-closed（退出活跃检索与 RAG）；admin-api 新增 `POST /governance/offboard`、`POST /governance/project-archive`（直接操作 `memories` 集合，不跨服务 import chat-api）。单测 `test_promotion_state_machine.py` 已覆盖失效可见性与 offboarding 计数。H-6 的 049 项目归档调用点需在 049 归档路径显式触发（跨特性，本文档已留集成点说明，未改 049 代码）。
- [x] T038 [P] C-7 审计回归 13 例（含审计桥异常不阻断、空 diff 不发、049 既有语义回归）；SC-8 相关用例由可见性矩阵覆盖

## Phase B6 — D4 迁移与原子切换（**维护窗口，未执行**）

> 无运行时兼容层：切换窗口内不得新旧实例并存；回滚必须「代码回退 + `--reverse`」成对执行。**以下脚本/手册仅产出，未连真实库、未执行 `--apply`。**

- [x] T039 新建 `scripts/migrate_017_scopes.py`：默认 dry-run、`--apply` 才落盘、可重入、`--reverse`；S1 scope 值 / S2 `$rename`+`$unset` / S3 `project_owner_id` 回填（多行或零行归档）/ S4 `default` 归档 / S5 部门节点校验 / S6 旧地址三清单 / S7 孤儿归档；`--self-test` 通过
- [x] T040 脚本不写 `projects` / `org_units` / `end_user_org_relations` / `chat_sessions`（`_assert_writable` 硬拦截）；`--reverse` 不撤销 S4/S7 的 `archived` 标记并打印 WARN
- [x] T041 新建 `rollout-017-d4-cutover.md`：M0–M4 全流程、成对回滚 SOP、三条铁律（不得新旧实例并存 / 回滚成对 / B2 代码与迁移同窗口）
- [ ] T042 **未执行**：切换演练、`--reverse` 演练与旧 scope / 旧字段 0 条对账（需维护窗口 + 真实数据库 + 写入冻结，SC-10 / SC-15 后半）。**手册已产出**：`cutover-drill-runbook.md` §T042 给出 dry-run/--apply/--reverse 四步 + 旧字面量 0 条对账清单。

## Phase B7 — 回归 / 文档同步 / 对账清理（部分）

- [ ] T043 **未执行**：049 回归 SC-9 的手工全链路步骤（配额 / 成员用量 / 归档），需 admin 会话与 A/B/C 账号凭据；自动侧 049 既有测试未在本轮重跑。**手册已产出**：`cutover-drill-runbook.md` §T043 给出配额/成员(C-7)/归档(H-3·H-6) 三步手工清单。
- [x] T044 [P] 文档同步（J-4）：`plan.md` / `quickstart.md` / `checklists/requirements.md`（重写为 Gate）/ `contracts/memory-context-contract.md` / `specs/INDEX.md` / 021 spec+plan+tasks+quickstart / 046 / 042 / 035；SC-15 旧字面量全局扫描收口
- [ ] T045 **未执行**：M4 对账清理（备份保留、旧字段残留移除、监控告警阈值、SC-15 签收表）——依赖 T042 切换完成。**手册已产出**：`cutover-drill-runbook.md` §T045 给出四项清理清单与双签口径。
- [ ] T046 [P] **部分**：本地全量回归（chat-api 记忆 275+ / admin-api 治理 35 / 双端 `vue-tsc` 0 错误 / 迁移 `--self-test` / 两服务 `compileall`）**已绿**；真实构建 + 双端真实浏览器 E2E（T031）+ 049 全量回归 + 切换演练（T042/T043/T045）**待维护窗口与凭据**。**清单已产出**：`cutover-drill-runbook.md` §T046 拆 A(本地可核验,已勾)/B(真实构建+E2E)/C(049回归+演练) 三组。

---

## Dependencies

```text
B0 ─→ B1 ─→ B2 ─┬─→ B3 ─→ B4 ─┐
                 └─→ B5 ────────┼─→ B6（维护窗口，M1 代码 + M2 数据原子切换）─→ B7
                                 │
        B2 的代码产物必须等到 B6 才能发布（J-6）
        T032/T033 的 C-7 仅需 B1，已提前落地
```

## MVP Scope

- **最小可交付 = B0 + B1 + B2 + B3 + B6**（安全闭环：身份、范围、链路、一次性切换）。
- B4（双端页面）、B5（治理 / 生命周期 / C-7）、B7（文档与回归）按优先级增量；但 **SC-15 / SC-10 / SC-12 必须在 B6 切换时同时满足，不能延后**。

## Notes

- **⚠️ 发布闸门**：B2/B3/B4 的代码已在工作区但**不得单独发布**。必须与 `scripts/migrate_017_scopes.py --apply` 在同一维护窗口原子切换（设计文档 R15 / 发布手册 §三条铁律）。跳过 B6 直接上线会造成新旧实例数据分叉且无法自动修复。
- **C-7 是跨特性改动**：钩子落在 049 端点、事件 `feature="049"`，已同步 049 spec/tasks；017 不新建成员端点。
- **SC-15 旧字面量的允许残留**：`scripts/migrate_017_scopes.py`（迁移脚本）、v3 设计/发布手册的改名对照与历史说明、`contracts` 中的 D4 声明、以及 `sediment.py` / `project_context.py` 里的 `workspace_id` **046 会话取值来源形参**（只用于读取 `chat_sessions` 的历史字段，绝不写入 017 记忆文档，不是 D4 禁止的旧字段回退）。`org_id` 作为 `end_user_org_relations` / auth 契约的真实字段名同样保留。
- **admin 短路已收紧**：结构性不完整的记录（空 `owner_id`、缺 `project_owner_id`、`default`、缺 `department_id`）对包括 `full_access_admin` 在内的所有 viewer 不可见；治理端读取归档记录走独立审计路径（`_governance_visible`）。
- 部门可见性含后代（D3）与 042 配额「直接成员」是不同口径；017 的 `visible_department_ids` 不得复用 042 `_scope_members`。
- 所有验收口径以 `spec.md` §8（SC-1~SC-15）为准，详细算法与字段以 v3 设计文档为准。
