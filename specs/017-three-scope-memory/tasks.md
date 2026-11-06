# Tasks: Three-Scope Memory (personal / project / department) · v3 修订稿

**Input**: [`spec.md`](./spec.md)（v3 修订稿）、[`plan.md`](./plan.md)、[`design-2026-11-05-project-department-scopes.md`](./design-2026-11-05-project-department-scopes.md)（v3 权威设计）

**Prerequisites**: spec.md (required), plan.md (required), `specs/049-project-members/` 已落地、`Decisions/ADR-9`

**Status（2026-11-06）**: 决策全部闭环；**B0 / B1 已完成并实测通过**；B2–B7 待执行。本文件的 `[x]` 现在对应**有测试证据的落地**，不再是「条目勾选」。

**Checklist Gate**: `checklists/requirements.md` 需按 v3 口径重写（T039）；旧版 100% 勾选不能作为本轮 Gate。

**Organization**: 后端落点 `chat-api/app/memory/`、`chat-api/app/api/endpoints/`、`chat-api/app/enterprise_capabilities/runtime/`；前端 `apps/admin-web/`、`apps/user-web/`。

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

> 对应 `spec.md` §7 A-2 / A-3 / A-6、§9。**本批次不引入任何范围改名**，满足 D4「改名须一次性原子切换」的约束。

- [x] T004 [P] 新增 `chat-api/app/memory/viewer.py`：`MemoryViewerContext`（frozen）+ `build_viewer_context()`（只认真实 `{session, user, tenant_id, org_id}` 契约，不回退 `user_id`）+ `resolve_viewer_context()`（HTTP）+ `resolve_viewer_from_identity()`（RAG，用 trusted ids）+ `load_role_keys()` / `load_visible_workspace_ids()` / `load_primary_org_id()`（全部 fail-closed）
- [x] T005 修 `api/endpoints/memory.py` 四个端点（create / list / delete / promote）改走统一上下文；补全 `viewer_org_id` 透传
- [x] T006 修 `api/endpoints/context_space.py` 两个端点（resolve / trace）改走统一上下文
- [x] T007 修 `enterprise_capabilities/runtime/adapters.py::knowledge_search`：`context.get(...)` 对冻结 pydantic `CapabilityExecutionContext` 必然抛 `AttributeError` 且被 `except` 吞掉 → 改为 `resolve_viewer_from_identity()`；补齐 `viewer_org_id`；让 `memory_candidates` 真正进入返回载荷
- [x] T008 `memory/scope.py::visible_to` 增加空 `viewer_id` / 空 `owner_id` 的 fail-closed 防御（P0 纵深防御）
- [x] T009 [P] 回归测试：`tests/memory/test_memory_endpoints.py` 换真实 auth 契约 + 7 个越权/角色/成员用例；新增 `test_memory_viewer.py`（15 例）、`test_rag_viewer_wiring.py`（2 例）；`tests/context_space/test_context_endpoints.py` 同步换契约 + 透传断言
- [x] T010 实测：017/021 + `knowledge_search` 相关 **171 passed**；交叉回归 **81 passed**；`compileall` 通过

**B1 阶段验收**：SC-1 的 personal 越权项、SC-12（无契约外字段 mock）、RAG 路径非空 —— 均已通过。**遗留**：A-1 目标态字段（`visible_department_ids` / `visible_project_keys` / `active_project_id` / `session_participants`）由 B2 补齐；`visible_workspace_ids` 是 B1 过渡来源，B2 换成二元组。

## Phase B2 — 范围模型 + D4 代码侧全量替换（**不发布**）

> 本阶段产出**只进分支、不上线**；与 B6 的数据迁移必须在同一维护窗口原子切换（J-6）。

- [ ] T011 [P] **D4 全量替换（J-5）**：`MemoryScope` / `Visibility` / `SCOPE_VISIBILITY` / `Memory` dataclass（`scope.py:22-57`）、`sediment.py`、`retrieval.py`、`store.py`、`address.py`、`endpoints/memory.py`、`adapters.py`、`context_space/`、`contracts/memory-context-contract.md:12-24`、017 与 021 的 spec/plan/tasks/quickstart
- [ ] T012 删除 `normalize_scope`、双写、三级回退、别名分支、`legacy_alias` 回显；`visible_to` 对未知 scope 直接 fail-closed（B-6）
- [ ] T013 实现 §4 可见性算法：`visible_to(Memory | dict, MemoryViewerContext)` 为唯一判据；021 只委托不重写
- [ ] T014 实现 `visible_project_keys = {(project_id, project_owner_id)}`（C-1），排除 `"default"` 与 `archived`；写入时固化 `project_owner_id`（B-8 / N1），`default` 显式 400 / 沉淀回落 `personal`（B-9 / N2）
- [ ] T015 实现 `visible_department_ids`（A-4 / **D3**：`end_user_org_relations` 不带 `status` 过滤 + `org_units.path_ids` 后代展开，不含祖先，跨租户 fail-closed）
- [ ] T016 [P] 补齐 `MemoryViewerContext` 目标态字段（A-1）并替换 B1 的 `visible_workspace_ids` / `viewer_org_id` 过渡字段
- [ ] T017 [P] 单测：可见性矩阵、跨租户 / 非成员 / 跨部门 / 同名 `project_id` / `default` 五类越权（SC-1 / SC-2 / SC-3 / SC-4 / SC-13）

**阶段验收**：SC-4、SC-13 通过；全仓 `workspace`/`org` 字面量仅剩迁移脚本与历史说明（SC-15 前半）。

## Phase B3 — 写入 / 沉淀 / 检索三条链路

- [ ] T018 `memories` schema 增 `project_id` / `project_owner_id` / `department_id`；索引与 `_row_to_memory` 同步
- [ ] T019 写入端点：`project_owner_id` / `department_id` 服务端解析、客户端传值忽略；`resolved_from` 回显（J-1，无 `legacy_alias`）；`scope_invalid` 400 / 404（B-6）
- [ ] T020 **D-6**：promote 改增量 `$set`，保留 L0/L1/L2、provenance、`archived`、`project_owner_id`（修现有 `replace_one` 全量清空）
- [ ] T021 会话沉淀 E-1~E-5：`session_doc.project_id` 三级回退（046，勿与 D4 字段回退混淆）、反查 `projects.user_id`、`default` 回落 `personal`、`ended_at` 幂等
- [ ] T022 **D-5**：生产注入写时 summarizer（修 `sediment.py` 两处调用恒不传 `summarizer` 导致 L0/L1 恒空）+ 读时 `tier_content` 惰性补全接线
- [ ] T023 检索 F-1~F-4：所有调用点传完整 viewer（含部门集合）、`skipped` 非空且原因可归类、trace 落观测通道并可按 `trace_id` 回看
- [ ] T024 地址 F-5：`mogo://memory/project|department/...` 新段；旧段运行时 404；`uri()` 往返一致
- [ ] T025 [P] 集成测试：写入 → 沉淀 → RAG → 地址 → 提升全链路（SC-5 / SC-6 / SC-7）

## Phase B4 — 双端功能（参考插件 / Skill 管理范式）

- [ ] T026 admin `/memories`：`routes.ts` 新增路由、`MemoriesPage.vue` + `MemoryDetailDrawer.vue` + `MemoryApprovalDialog.vue`（I-1）
- [ ] T027 admin 可见范围配置 / 策略 / 配额（I-2）
- [ ] T028 `SystemAuditPage.vue` 增加「记忆管理」module 过滤，纳入 `memory.*` 与 `project.member.*`（I-3）
- [ ] T029 user 侧栏「我的记忆」：`MyMemoriesPage.vue` + `MemoryViewTabs.vue` + `MemoryDetailDialog.vue`，双 Tab / 搜索 / 增删改 / 提升申请（I-4，**不含成员编辑**）
- [ ] T030 两端共用响应契约、分页、审计桥；不可见即 404；`get_current_admin_user` / `require_end_user_principal` 鉴权（I-5 / I-6）
- [ ] T031 [P] 双端 E2E + `vue-tsc` 0 错误（SC-11）；**记忆不挂 `/assets`**（045 排除项）

## Phase B5 — 治理 / 生命周期 / 组织变更 + C-7

- [ ] T032 **C-7（必做）**：在 049 `chat-api/app/api/endpoints/projects.py:168-217 patch_project` 按 `member_user_ids` diff 挂 `project.member.granted` / `project.member.revoked`；`emit_feature_event("049", ...)`，`update_one` 成功后发；失败只留观测日志不阻断 PATCH；**不改 049 鉴权 / 去重 / 500 上限 / `default` 400 / 响应结构**（设计文档 §9.4 事件契约）
- [ ] T033 `feature_audit.py` 白名单：新增 `"049": ("project.member.granted", "project.member.revoked")` 分组 + 扩充 `"017"` 分组；`record_feature_event` 会校验 feature code 与 event，须与 T032 同批上线
- [ ] T034 同步 `specs/049-project-members/{spec,tasks}.md` 增加成员变更审计 FR 与回归用例（R16：防后续 049 迭代覆盖钩子）
- [ ] T035 提升审批 G-1~G-3：`full_access_admin` + 目标部门在可见集合内、001 审计、普通用户走 `portal_requests` 状态机
- [ ] T036 生命周期 H-1 / H-2：`MEMORY_DECAY_DAYS` 注入 `main.py` 衰减循环（现硬编码 30 天）+ 读取命中 `lifecycle.touch()` 生产接线
- [ ] T037 离职 / 调岗 / 成员移除 H-3~H-6：personal 与 project 失效、department 保留且脱离创建者依赖；动态重算不固化名单
- [ ] T038 [P] 用例：SC-8 / SC-14（含审计桥异常不阻断）/ 049 既有语义回归全绿

## Phase B6 — D4 迁移与原子切换（**维护窗口**）

> 无运行时兼容层：切换窗口内不得新旧实例并存；回滚必须「代码回退 + `--reverse`」成对执行。

- [ ] T039 `scripts/migrate_017_scopes.py`：默认 dry-run、`--apply` 才落盘、可重入（第二次 0 条）、`--reverse` 可回退；步骤 S1 scope 值 / S2 字段 `$rename` + `$unset` / S3 `project_owner_id` 回填（N1，多行或零行归档） / S4 `default` 归档（N2） / S5 部门节点校验（D3） / S6 旧地址改写三清单 / S7 孤儿归档
- [ ] T040 迁移不触碰 `projects` / `org_units` / `end_user_org_relations` / `chat_sessions`；`--reverse` 不撤销 S4/S7 的 `archived` 标记
- [ ] T041 发布手册：M0 前置（备份 `memories`、盘点持久化旧地址、J-5 清单核对）→ M1 代码替换（不发布）→ M2 冻结写入 + 迁移 → M3 原子切换 + 解冻 → M4 对账；**成对回滚 SOP**
- [ ] T042 切换演练 + 对账：旧 scope / 旧字段 0 条、`scope_invalid` 与旧地址 404 监控、`--reverse` 演练（SC-10 / SC-15）

## Phase B7 — 回归 / 文档同步 / 对账清理

- [ ] T043 049 回归 SC-9：管理端 `/projects` 四列有值、join 不丢行、`/projects/{id}/policy` 可用；按 049 `quickstart.md` 补齐 T022 剩余手工步骤（配额 / 成员用量 / 归档）
- [ ] T044 [P] 文档同步（J-4）：`plan.md`（删 `promote.py` 等陈旧项、OQ-1/3/10）、`quickstart.md`、`checklists/requirements.md`（第 48 行「超限拒绝写入」与改写后 FR 不符）、`contracts/memory-context-contract.md`、`specs/INDEX.md`（017 行补「依赖 049」）、021 / 046 / 042 / 035、`sediment.py:14-18` 文件头「接线留待后续」
- [ ] T045 M4 对账清理：备份保留 N 天、移除旧字段残留、监控告警阈值；SC-15 检查单逐项签收
- [ ] T046 全量回归：017 + 021 + 049 + RAG 适配器 + 双端构建；SC-12 全绿且无契约外字段 mock

---

## Dependencies

```text
B0 ─→ B1 ─→ B2 ─┬─→ B3 ─→ B4 ─┐
                 └─→ B5 ────────┼─→ B6（维护窗口，M1 代码 + M2 数据原子切换）─→ B7
                                 │
        B2 的代码产物必须等到 B6 才能发布（J-6）
        T032/T033 的 C-7 仅需 B1，可从 B3 依赖中解耦提前
```

## MVP Scope

- **最小可交付 = B0 + B1 + B2 + B3 + B6**（安全闭环：身份、范围、链路、一次性切换）。
- B4（双端页面）、B5（治理 / 生命周期 / C-7）、B7（文档与回归）按优先级增量；但 **SC-15 / SC-10 / SC-12 必须在 B6 切换时同时满足**，不能延后。

## Notes

- **B1 已完成**（2026-11-06）：改动文件 `app/memory/viewer.py`（新增）、`app/memory/scope.py`、`app/api/endpoints/memory.py`、`app/api/endpoints/context_space.py`、`app/enterprise_capabilities/runtime/adapters.py`；测试 `tests/memory/test_memory_endpoints.py`（重写）、`tests/memory/test_memory_viewer.py`（新增）、`tests/memory/test_rag_viewer_wiring.py`（新增）、`tests/context_space/test_context_endpoints.py`。
- **D4 不是「不做迁移」**：取消的是运行时兼容层；历史 `memories` 仍须由 T039 脚本一次性转换。跳过 B6 直接发布 B2 代码会造成新旧实例数据分叉且无法自动修复（设计文档 R15）。
- **C-7 是跨特性改动**：钩子落在 049 端点、事件 `feature="049"`，须同步 049 的 spec/tasks，017 不新建成员端点。
- 部门可见性含后代（D3）与 042 配额「直接成员」是不同口径；017 的 `visible_department_ids` 不得复用 042 `_scope_members`。
- 所有验收口径以 `spec.md` §8（SC-1~SC-15）为准，详细算法与字段以 v3 设计文档为准。
