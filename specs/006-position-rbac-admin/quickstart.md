# Quickstart: Organization, User & Position-Role RBAC Administration (006)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md)

本文件说明如何**启用并验证**岗位角色 CRUD 与启停、用户-角色绑定、角色能力与资源访问控制、全量审计。

---

## 1. 前置

- `services/admin-api` 已部署（岗位角色管理面）
- MongoDB 可用（`position_roles` + `end_user_position_roles` 集合）
- 特性 001（gatekeeper）已落地（006 是 001 细粒度权限码的"预设组"基础）

---

## 2. 岗位角色管理（CRUD + 启停）

```python
from app.position_roles.service import PositionRoleService
from app.position_roles.constants import FULL_ACCESS_ROLE_KEY

svc = PositionRoleService(mongo_db)

# 创建角色
role = await svc.create(
    tenant_id="t1",
    name="销售经理",
    capabilities=["chat", "knowledge"],
    tool_access_mode="selected",
    tool_ids=["tool-1", "tool-2"],
    skill_access_mode="all",
)

# 更新角色
await svc.update(
    role_id=role.id,
    capabilities=["chat", "knowledge", "skill"],
    tool_access_mode="all",
)

# 复制角色
copied = await svc.copy(role_id=role.id, new_name="销售经理-副本")

# 启停
await svc.set_enabled(role_id=role.id, enabled=False)

# 删除
await svc.delete(role_id=role.id)

# 内置全能力管理员（始终可用）
admin_role = await svc.get_by_key(FULL_ACCESS_ROLE_KEY)
```

**验证**：创建→唯一名校验；更新→tool/skill ID 有效；启停→状态切换；删除→审计记录。

---

## 3. 用户-角色绑定（主角色 + 多角色）

```python
from app.position_roles.service import PositionRoleService

# 绑定角色（指定主角色）
await svc.bind_user_roles(
    user_id="u1",
    tenant_id="t1",
    role_ids=["role-1", "role-2"],
    primary_role_id="role-1",  # 主角色必须在角色集内
)

# 替换用户角色集
await svc.replace_user_roles(
    user_id="u1",
    tenant_id="t1",
    role_ids=["role-3"],
    primary_role_id="role-3",
)

# 迁移补全（历史数据）
await svc.complete_migration(tenant_id="t1")
```

**验证**：绑定→主角色在集内；替换→新角色集生效；迁移→历史数据补全。

---

## 4. 角色能力与资源访问控制

```python
# 角色携带能力开关（normalized_capabilities）
role.capabilities → ["chat", "knowledge", "skill"]

# 工具访问模式
role.tool_access_mode → "all" | "selected"
role.tool_ids → ["tool-1", "tool-2"]  # selected 模式下必须真实存在

# Skill 访问模式
role.skill_access_mode → "all" | "selected"
role.skill_ids → ["skill-1", "skill-2"]  # selected 模式下必须真实存在

# 校验：selected 模式下 ID 必须存在
try:
    await svc.create(
        tool_access_mode="selected",
        tool_ids=["non-existent-id"],  # 不存在 → 拒绝
    )
except ValidationError:
    pass
```

**验证**：selected + 不存在 ID→拒绝；all→访问全部；全能力管理员→始终可用。

---

## 5. 验证清单

| # | 验证项 | 期望 |
|---|---|---|
| 1 | 创建角色 | 唯一名校验通过，审计 create |
| 2 | 更新角色 | tool/skill 资源 ID 有效，审计 update |
| 3 | 复制角色 | 生成同名可改的新角色 |
| 4 | 启停角色 | 状态切换，审计 enable/disable |
| 5 | 删除角色 | 审计 delete（含角色名） |
| 6 | 绑定主角色 | 主角色在角色集内 |
| 7 | 替换角色集 | 主角色必须在新集内 |
| 8 | 迁移补全 | 历史用户角色数据补全 |
| 9 | selected + 不存在 ID | 创建/更新拒绝 |
| 10 | 全能力管理员 | 内置，始终可用 |

---

## 6. 单元测试

```bash
cd services/admin-api
PYTHONPATH=. python -m pytest \
  tests/test_position_roles.py \
  tests/test_position_role_auditing.py \
  -o asyncio_mode=auto -q
```

---

## 7. 说明

- 本特性为回溯固化既有能力，目标是把现有岗位角色 RBAC 写成可验收契约，防止回归
- 集合：`position_roles`（角色）+ `end_user_position_roles`（用户绑定）
- 内置全能力管理员：`FULL_ACCESS_ROLE_KEY = full_access_admin`
- 与特性 001（gatekeeper）的关系：001 的细粒度权限码以本特性的岗位角色为"预设组"基础
- 与特性 004（SkillHub）的关系：角色的 skillAccessMode/skillIds 决定 Skill 可见面
