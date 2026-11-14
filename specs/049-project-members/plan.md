# Implementation Plan: 项目成员与项目层配额收口

**Branch**: `049-project-members` | **Date**: 2026-11-05 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/049-project-members/spec.md`；读路径残留证据来自 2026-11-05 核查（`quota_projects` 0 行 vs `projects` 2 行）。

**Note**: 本特性 = 一处读路径 bug 修复（US3）+ 一个能力扩展（US1/US2：项目成员、成员可见性、成员配额口径）。引擎结构（042 四层取小）不动。

## Summary

三条主线：
1. **US3 读路径修复**：`admin-api` 的 `quota_projects.py` / `traffic_allocations.py` / `quota_policy.py` 全部切到 `projects` 表；`quota_projects` 退役（0 行，无迁移）。
2. **US1 成员与可见性**：`projects.member_user_ids` 新字段；chat-api `PATCH /projects/{id}` 收成员（仅创建者）；`GET /projects` 过滤改"我的 ∪ 我参与的"；chat-api 新增 `GET /projects/member-candidates`（部门过滤 + 用户列表）；user-web「…」菜单加「成员」项 + 弹窗。
3. **US2 配额口径**：双服务 `quota_policy.py` 的项目层成员来源改为 `projects.member_user_ids ∪ user_id`（创建者兜底）；admin 侧 `_layer_state` 的 deleted 判断改 `projects.status == "archived"`；`_require_project` 改查 `projects`。

## Technical Context

**Language/Version**: Python 3.11+（admin-api / chat-api）；TypeScript 5 + Vue 3（user-web / admin-web）

**Primary Dependencies**:
- `services/chat-api/app/api/endpoints/projects.py`（成员字段 + PATCH/GET 改）
- `services/chat-api/app/core/quota_policy.py`（项目层成员来源）
- `services/admin-api/app/services/quota_projects.py`（读切 `projects`）
- `services/admin-api/app/api/routes/traffic_allocations.py`（`_require_project` / 端点退役）
- `services/admin-api/app/core/quota_policy.py`（镜像 chat-api 的成员口径 + archived 判断）
- `apps/user-web/src/App.vue`（「…」菜单 + 成员弹窗）
- `apps/user-web/src/api/sessions.ts`（`PATCH member_user_ids` + 候选端点 client）
- `apps/admin-web/src/api/traffic-allocations.ts` + `views/organizations/TrafficAllocationsPage.vue`（删 5 个 quota_projects 写函数及其调用点）
- `apps/admin-web/src/views/projects/ProjectsPage.vue`（字段映射微调：archived 分组直接消费 status）

**Storage**:
- `projects` 加 `member_user_ids: [str]` 动态字段（PanWeiDB 读路径列优先 + doc 兜底，无需 DDL；`column_map.py` 不需要动——该列不在 `COLUMN_MAP`，走 doc JSONB）。
- `quota_projects` 退役不删表（0 行；AGENTS.md 禁删文件同理，保留表壳，文档标记）。

**Testing**: 双服务 pytest（`chat-api/tests/test_projects_rename.py` 扩展 + 新增 `test_project_members.py`；`admin-api` 既有 `test_quota_three_level.py` 回归 + `test_quota_consistency.py` 加成员用例）；前端 `node scripts/check_sfc.mjs` 单文件编译。

**Target Platform**: chat-api + admin-api + user-web + admin-web

**Project Type**: web-service + web-app（能力扩展 + 读路径修复）

**Performance Goals**: `GET /projects` 多一次 `member_user_ids` 的 `$in`/`$elemMatch` 匹配——PanWeiDB 走 doc 路径，租户内项目数 < 1k，无新增索引需求（046 FR-002 的 `{tenant_id, user_id, status}` 索引继续服务主查询）。

**Constraints**:
- 两份 `quota_policy.py` 成员口径必须逐字段一致（047 T022 一致性测试锁死）。
- 前端与后端同批发布；`member-candidates` 端点必须在 user-web 弹窗上线前就绪。
- `quota_projects` 的 5 个 admin 写端点退役时，`TrafficAllocationsPage.vue:227-238` 的 import 同批清理，不留死引用。

**Scale/Scope**: 后端 4 文件 + 测试 2–3 文件；前端 4 文件（user-web 2 + admin-web 2）+ 弹窗组件 1；文档 1。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本 spec 先于代码。
- **II. Enterprise Production Readiness**: ✅ 读路径修复有 3 条验收（SC-001/002/003）；退役端点无第三方消费（核查 `grep createQuotaProject apps/` 仅 `TrafficAllocationsPage.vue` 一处）。
- **III. Security and Data Protection**: ✅ 成员写操作鉴权 = 创建者本人（403 兜底）；候选端点只返回 active 用户的展示字段（不含 password/salt 等敏感列——`list_users` 既有白名单口径）。
- **IV. Cross-Platform and i18n**: ✅ user-web 文案走内联三元（`locale === 'en' ? 'Members' : '成员'`），与既有「重命名/删除项目」风格一致，不引 i18n key。
- **V. Observability and Simplicity**: ✅ 不新增日志/指标；退役端点直接删路由（不留 410 壳），grep `quota_projects` 收口为 0 命中（SC-005）。

## Project Structure

### Documentation (this feature)

```text
specs/049-project-members/
├── spec.md
├── plan.md              # 本文件
├── tasks.md
├── checklists/requirements.md
└── quickstart.md
```

### Backend

```text
services/chat-api/app/api/endpoints/projects.py   # member_user_ids + 过滤 + 候选端点
services/chat-api/app/core/quota_policy.py         # 项目层成员口径
services/admin-api/app/services/quota_projects.py  # 读切 projects + project_view 映射
services/admin-api/app/api/routes/traffic_allocations.py  # _require_project + 端点退役
services/admin-api/app/core/quota_policy.py        # 镜像口径 + archived 判断
services/chat-api/tests/test_project_members.py    # 新增
services/chat-api/tests/test_quota_consistency.py  # 成员口径用例（047 T022 扩展）
services/admin-api/tests/test_quota_three_level.py # 回归
```

### Frontend

```text
apps/user-web/src/App.vue                          # 「…」菜单加「成员」+ 弹窗
apps/user-web/src/api/sessions.ts                  # PATCH member_user_ids + 候选列表 client
apps/user-web/src/components/project/MemberPicker.vue   # 新弹窗组件（部门树 + 多选）
apps/admin-web/src/api/traffic-allocations.ts      # 删 5 个 quota_projects 写函数
apps/admin-web/src/views/organizations/TrafficAllocationsPage.vue  # 删调用点
apps/admin-web/src/views/projects/ProjectsPage.vue # status=archived 消费（可能零改动）
```

### Documentation

```text
specs/INDEX.md                                      # 049 行
specs/042-three-level-quota/spec.md（落地索引节）   # quota_projects 退役标记（一行）
Decisions/ADR-9-项目成员-可见性与配额口径.md        # 决策记录（新建）
```

## Phase Breakdown

```
Phase 0  基线与决策记录（ADR-9 + INDEX + 042 退役标记）
Phase 1  US3 读路径修复（admin 侧 4 处切 projects；端点退役；前端清理）   ← 可独立发布，最小闭环
Phase 2  US1 成员与可见性（chat-api 字段/端点 + user-web 菜单/弹窗）     ← 依赖 Phase 1 的字段契约稳定
Phase 3  US2 配额口径（双 quota_policy + 一致性测试）                    ← 依赖 Phase 2 的字段落库
Phase 4  验证收尾（grep 收口、全量回归、quickstart）
```

- **Phase 1 是最小可交付**：admin 页面立刻有数据（US3），与本特性其余部分解耦。
- Phase 2 依赖 Phase 1：`project_view` 的字段映射（`name`←`title` 等）在 Phase 1 定型。
- Phase 3 依赖 Phase 2：成员字段必须先有值，口径切换才有意义。

## Open Questions

- **OQ-1 候选端点放在哪个服务**：取 chat-api（`/api/v1/projects/member-candidates`），理由：user-web 只连 chat-api（`/askai-api` 前缀），admin-api 的 `/directory/users` 要求 `get_current_admin_user`（管理员 token），普通员工没有 admin 会话。部门树数据 `org_units.path_ids` 在 chat-api 可直接读（共享库）。
- **OQ-2 弹窗组件归属**：user-web 已有 `ProjectManager.vue`（`apps/user-web/src/components/project/`），成员弹窗同目录新增 `MemberPicker.vue`，App.vue 通过 `<MemberPicker v-if=...>` 挂载——不在 App.vue（3000+ 行）里再堆模板。
- **OQ-3 `GET /projects` 的 ∪ 过滤在 PanWeiDB 的表达**：`member_user_ids` 不在 `COLUMN_MAP` → doc JSONB 路径，`$elemMatch` 在 R1 未实现（pg_compat 明确抛 `PgCompatUnsupported`）——**改用两个查询取并集**：`find({user_id: me}) ∪ find({"member_user_ids": me})`（后者是普通 eq 匹配 JSONB 数组元素，R1 支持 `$eq` 对 JSONB 数组的语义——需要 Phase 2 实测确认；若不支持，回退为拉全租户 active 项目在内存过滤，规模 <1k 可接受）。
- **OQ-4 配额"创建者兜底"落库还是计算**：取**计算**（不往 `member_user_ids` 里写创建者 id，保持 FR-001"创建者不落此字段"）；两份 `quota_policy.py` 的 `_project_members()` 统一为 `list(set(doc.member_user_ids or []) | {doc.user_id})`。
