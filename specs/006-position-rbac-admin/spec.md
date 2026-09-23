# Feature Specification: Organization, User & Position-Role RBAC Administration

**Feature Branch**: `006-position-rbac-admin`

**Created**: 2026-07-08

**Status**: Draft

**Input**: 回溯固化 MOVO 既有优势能力（规划文档 §1.1"管理后台：组织/用户/角色/模型/知识/Skill/工具/审计/运行状态、RBAC"）：岗位角色 CRUD 与启停、用户-角色绑定（主角色 + 多角色）、角色能力开关与工具/Skill 访问模式（all/selected + 显式 ID 列表）、全能力管理员内置角色、角色操作全量审计。

## User Scenarios & Testing *(mandatory)*

用户故事按优先级排列，每个独立可交付、可测试。

### User Story 1 (P1) — 岗位角色管理（CRUD + 启停）

管理员可创建/更新/复制/启停/删除组织岗位角色；角色名在租户内唯一；角色携带能力开关与工具/Skill 访问配置。

**Acceptance Scenarios:**
- 创建角色 → 写入 position_roles 集合，唯一名校验通过，审计 create
- 更新角色 → 校验 tool/skill 资源 ID 有效，审计 update
- 复制角色 → 生成同名可改的新角色
- 启停角色 → 状态切换，审计 enable/disable
- 删除角色 → 审计 delete（含角色名）

### User Story 2 (P1) — 用户-角色绑定（主角色 + 多角色）

用户可绑定多个岗位角色，其中指定一个为主角色；绑定关系落 end_user_position_roles；迁移补全能力。

**Acceptance Scenarios:**
- 绑定角色（primary=True）→ 该用户主角色为该角色
- 替换用户角色集 → 新角色集生效，主角色必须在新集内
- 迁移补全（complete_migration）→ 历史用户角色数据补全
- 校验角色 ID 与主角色 ID 合法

### User Story 3 (P1) — 角色能力与资源访问控制

角色配置能力开关（normalized_capabilities）与工具/Skill 访问模式：
- `all` → 访问该租户全部工具/Skill
- `selected` + 显式 ID 列表 → 仅访问指定工具/Skill，ID 必须真实存在

**Acceptance Scenarios:**
- 角色 toolAccessMode=selected 且 toolIds 含不存在 ID → 创建/更新拒绝
- 角色 skillAccessMode=all → 该角色用户可见全部 Skill
- 能力开关 → 影响用户可用功能面
- 全能力管理员角色（full_access_admin）→ 内置，始终可用

### User Story 4 (P2) — 角色操作全量审计

角色的创建/更新/复制/启停/删除/绑定/迁移全部写入审计（actor + action + target + details）。

**Acceptance Scenarios:**
- 每次角色操作 → 审计记录操作者与目标
- 审计可追溯某角色生命周期全部变更

### Notes / Assumptions
- 本特性为**回溯固化**既有能力，目标是把现有岗位角色 RBAC 写成可验收契约，防止回归
- 角色仓库：services/admin-api/app/position_roles（repository + service + constants）
- 集合：`position_roles`（角色）+ `end_user_position_roles`（用户绑定）
- 内置全能力管理员：`FULL_ACCESS_ROLE_KEY = full_access_admin`
- 与特性 001（gatekeeper）的关系：001 的细粒度权限码模型以本特性的岗位角色为"预设组"基础，向下兼容
- 与特性 004（SkillHub）的关系：角色的 skillAccessMode/skillIds 决定 Skill 可见面

## Functional Requirements

- FR-1: 岗位角色支持创建/更新/复制/启停/删除，租户内唯一名
- FR-2: 用户可绑定多角色并指定主角色，绑定落 end_user_position_roles
- FR-3: 历史用户角色数据支持迁移补全（complete_migration）
- FR-4: 角色携带能力开关（normalized_capabilities），影响用户功能面
- FR-5: 角色工具/Skill 访问模式为 all 或 selected + 显式 ID 列表
- FR-6: selected 模式下 toolIds/skillIds 必须全部存在，否则拒绝
- FR-7: 内置全能力管理员角色（full_access_admin）始终可用
- FR-8: 角色全部操作（CRUD/启停/绑定/迁移）写入审计
- FR-9: 资源 ID 校验引用 external_tools 与 skills 集合真实存在性

## Non-Goals
- 不实现细粒度权限码 `<resource>:<action>[:<target>]` 模型（属特性 001 gatekeeper，本特性是 001 的预设组基础）
- 不实现跨租户角色共享
- 不实现 RBAC 与 PII 脱敏的联动（属 001）
- 不改变现有岗位角色数据模型，仅固化行为契约

## Success Criteria
- 角色 CRUD/启停/绑定/迁移 100% 写审计
- selected 模式资源 ID 100% 校验存在性（不引用空 ID）
- 全能力管理员角色在空租户 100% 可用
- 主角色必须在用户角色集内 100%（无孤儿主角色）
- 租户内角色名唯一 100%

## Further Details
- 技术实现（仓库方法、能力归一化、审计落点）由 plan.md 承载
- 与特性 001（gatekeeper）的关系：本特性是 001 细粒度权限码的"岗位角色预设组"基础
- 与特性 004（SkillHub）的关系：角色 Skill 访问面决定 004 的可见性
