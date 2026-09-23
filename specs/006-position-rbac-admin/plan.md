# Implementation Plan: Organization, User & Position-Role RBAC Administration

**Branch**: `006-position-rbac-admin` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 回溯规约，固化既有行为。把岗位角色 RBAC 实现事实技术化为契约。

## Summary

不新增模块，把 `admin-api/position_roles/`（repository + service + constants）与相关路由写成契约。交付物：data-model.md（position_roles + end_user_position_roles 集合字段）、contracts/rbac-contract.md、quickstart.md。

## Technical Context

**Language/Version**: Python 3.13（admin-api 既有栈）

**Primary Dependencies**: MongoDB（position_roles + end_user_position_roles + external_tools + skills）

**Storage**: MongoDB

**Testing**: pytest（position_roles 既有测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 既有服务契约化（brownfield）

## 现有实现事实（contract 依据）

- 常量：`constants.py` → `FULL_ACCESS_ROLE_KEY = full_access_admin`、`POSITION_ROLE_COLLECTION = position_roles`、`USER_ROLE_COLLECTION = end_user_position_roles`
- 仓库：`repository.py`（PositionRoleRepository）：
  - `ensure_full_access_role(main_id)` → 内置全能力管理员
  - `assign_role` / `replace_user_roles`（主角色 + 多角色）
  - `complete_migration` → 历史补全
  - `audit(main_id, actor, action, target_type, target_id, details)` → 审计落点
- 服务：`service.py`（PositionRoleService）：
  - `normalized_capabilities` → 能力开关归一化
  - `validate_resource_ids` → tool/skill 资源 ID 存在性校验（external_tools / skills 集合）
  - 访问模式：`toolAccessMode`/`skillAccessMode` ∈ {all, selected} + 显式 ID 列表

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：内置全能力管理员 |
| III. Security | 通过：资源 ID 校验、fail 拒绝 |
| IV. i18n | 通过 |
| V. Observability | 通过：角色操作全量审计 |

## Project Structure

```text
specs/006-position-rbac-admin/
├── plan.md
├── data-model.md      # position_roles / end_user_position_roles 字段
├── contracts/
│   └── rbac-contract.md   # 角色 CRUD / 绑定 / 能力 / 审计 API 契约
└── quickstart.md
```

源码不改动（brownfield 契约化）；如需修回归，以 tasks.md 登记。

## Open Questions
- OQ-1: 岗位角色如何与 001 gatekeeper 细粒度权限码联动（001 未实现前，权限码模型如何映射到岗位角色预设组）需 clarify
- OQ-2: 能力开关（capabilities）当前支持哪些维度（模型/知识/Skill/工具/审计各自开关）

## 下一步
`/speckit-clarify` 消解 OQ → 补 data-model/contracts/quickstart → checklist → tasks → analyze。
