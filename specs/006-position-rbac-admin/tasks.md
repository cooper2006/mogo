# Tasks: Organization, User & Position-Role RBAC Administration

> ⚠️ **落地审计说明**：本特性为回溯固化既有能力，任务条目标记当前落地状态。

**Input**: Design documents from `/specs/006-position-rbac-admin/`

**Prerequisites**: plan.md (required), spec.md (required)

**Organization**: 任务按用户故事分组，每组可独立实现与测试。

---

## Phase 1: Foundational — 角色模型与存储

**Goal**: 建立岗位角色数据模型与仓库层。

- [x] T001 实现 `position_roles` 集合 schema：角色文档结构（name/capabilities/tool_access/skill_access/status）
- [x] T002 实现 `end_user_position_roles` 集合 schema：用户绑定文档结构（user_id/role_ids/primary_role_id）
- [x] T003 实现 `PositionRoleRepository`：CRUD 仓库方法
- [x] T004 实现租户内唯一名校验：角色名在租户内唯一
- [x] T005 实现内置全能力管理员角色：`FULL_ACCESS_ROLE_KEY = full_access_admin`，始终可用（FR-7）

---

## Phase 2: User Story 1 (P1) — 岗位角色管理（CRUD + 启停）

**Goal**: 管理员可创建/更新/复制/启停/删除岗位角色。

**独立测试**: 创建→唯一名通过；更新→ID 有效；启停→状态切换；删除→审计。

- [x] T006 [P] 实现 `PositionRoleService.create`：创建角色，唯一名校验
- [x] T007 [P] 实现 `PositionRoleService.update`：更新角色，校验 tool/skill 资源 ID 有效
- [x] T008 [P] 实现 `PositionRoleService.copy`：复制角色，生成同名可改新角色
- [x] T009 [P] 实现 `PositionRoleService.set_enabled`：启停角色，状态切换
- [x] T010 [P] 实现 `PositionRoleService.delete`：删除角色
- [x] T011 单元测试：CRUD + 启停全链路
- [x] T012 单元测试：唯一名校验

---

## Phase 3: User Story 2 (P1) — 用户-角色绑定

**Goal**: 用户可绑定多角色并指定主角色，支持迁移补全。

**独立测试**: 绑定→主角色在集内；替换→新集生效；迁移→历史补全。

- [x] T013 [P] 实现 `PositionRoleService.bind_user_roles`：绑定角色，指定主角色
- [x] T014 [P] 实现 `PositionRoleService.replace_user_roles`：替换用户角色集，主角色必须在集内
- [x] T015 [P] 实现 `PositionRoleService.complete_migration`：历史用户角色数据迁移补全（FR-3）
- [x] T016 [P] 实现角色 ID 与主角色 ID 合法校验
- [x] T017 单元测试：绑定/替换/迁移全链路

---

## Phase 4: User Story 3 (P1) — 角色能力与资源访问控制

**Goal**: 角色配置能力开关与工具/Skill 访问模式，selected 模式 ID 必须存在。

**独立测试**: selected + 不存在 ID→拒绝；all→访问全部；全能力管理员→始终可用。

- [x] T018 [P] 实现 `normalized_capabilities`：能力开关归一化（FR-4）
- [x] T019 [P] 实现工具访问模式：`all` 或 `selected` + 显式 ID 列表（FR-5）
- [x] T020 [P] 实现 Skill 访问模式：`all` 或 `selected` + 显式 ID 列表（FR-5）
- [x] T021 [P] 实现资源 ID 校验：selected 模式下 toolIds/skillIds 必须全部存在（FR-6）
- [x] T022 [P] 实现资源引用校验：引用 external_tools 与 skills 集合真实存在性（FR-9）
- [x] T023 单元测试：能力开关与访问模式全链路
- [x] T024 单元测试：selected 模式 ID 校验（存在/不存在）

---

## Phase 5: User Story 4 (P2) — 角色操作全量审计

**Goal**: 角色全部操作写入审计（actor + action + target + details）。

**独立测试**: 每次操作→审计记录；可追溯生命周期全部变更。

- [x] T025 [P] 实现审计写入：CRUD/启停/绑定/迁移全部写入审计（FR-8）
- [x] T026 [P] 实现审计记录结构：actor + action + target + details
- [x] T027 单元测试：审计覆盖所有操作类型
- [x] T028 集成测试：审计可追溯某角色生命周期全部变更

---

## Phase 6: Testing & Verification

- [x] T029 角色 CRUD/启停/绑定/迁移 100% 写审计（Success Criteria 1）
- [x] T030 selected 模式资源 ID 100% 校验存在性（Success Criteria 2）
- [x] T031 全能力管理员角色在空租户 100% 可用（Success Criteria 3）
- [x] T032 主角色必须在用户角色集内 100%（Success Criteria 4）
- [x] T033 租户内角色名唯一 100%（Success Criteria 5）
