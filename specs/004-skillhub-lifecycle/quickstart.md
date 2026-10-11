# Quickstart: SkillHub Marketplace & Skill Lifecycle (004)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md)

本文件说明如何**启用并验证**组织级 Skill 生命周期（草稿→发布→回看→反馈）、ZIP 安装校验、启停授权与更新分享。

---

## 1. 前置

- `services/admin-api` 已部署（Skill 生命周期管理面）
- `services/chat-api` 已部署（Skill 运行时加载与调用）
- MongoDB 可用（`skills` + `organization_skill_releases` 集合）
- 特性 001（gatekeeper）已落地（Skill 调用授权与审计复用 001 权限码）

---

## 2. Skill 草稿与发布

```python
from app.services.skill_lifecycle import SkillLifecycleService

svc = SkillLifecycleService(mongo_db)

# 初始化草稿
draft = await svc.initialize(org_id="org-1", skill_name="my-skill")

# 保存草稿（revision 递增）
updated = await svc.save_draft(
    skill_id=draft.id,
    config={"description": "...", "parameters": [...]},
)
# updated.has_unpublished_changes → True

# 发布（生成不可变版本快照）
release = await svc.publish(skill_id=draft.id, release_notes="v1.0.0")
# release.version → 递增版本号
# release.digest → 不可变快照摘要
```

**验证**：初始化→保存→发布全链路；同版本号重复发布→拒绝。

---

## 3. Skill 版本回看

```python
releases = await svc.list_releases(skill_id="skill-123", limit=20)
# releases[0].version, .published_at, .release_notes, .digest

# 回看某版本（不改变当前已发布态）
snapshot = await svc.get_release(skill_id="skill-123", version="1.0.0")
```

**验证**：列出 releases → 按时间倒序，最多 20 条；回看版本→不改变当前已发布态。

---

## 4. SkillHub ZIP 安装与校验

```python
from app.enterprise_capabilities.skills.skill_packages.validator import validate_package

result = await validate_package(
    zip_bytes=b"...",
    org_id="org-1",
)
# result.valid → True/False
# result.errors → 校验失败原因（定位到具体项）

from app.api.endpoints.skill_package_install import install_skill_package
await install_skill_package(
    org_id="org-1",
    zip_bytes=b"...",
)
```

**验证**：合法 ZIP→校验通过并安装；缺失必需字段→校验拒绝并定位错误；版本冲突→拒绝安装。

---

## 5. Skill 启停与授权

```python
# 停用 Skill（运行时不再提供）
await svc.set_enabled(skill_id="skill-123", enabled=False)

# 授权岗位角色（006 联动）
await svc.authorize_role(
    skill_id="skill-123",
    role_id="role-sales",
)

# 未授权角色调用 → 拒绝并审计（001 联动）
```

**验证**：停用→运行时不提供；授权→角色可调用；未授权→拒绝并审计；启停/授权变更→写入审计通道。

---

## 6. 验证清单

| # | 验证项 | 期望 |
|---|---|---|
| 1 | 初始化草稿 | revision=1，has_unpublished_changes=True |
| 2 | 修改后保存 | revision 递增，digest 比对标记未发布 |
| 3 | 发布 | 生成新版本号，release 落库，skill 切 published 态 |
| 4 | 同版本号重复发布 | 拒绝（版本号已存在） |
| 5 | 历史版本回看 | 最多 20 条，不改变当前已发布态 |
| 6 | ZIP 校验失败 | 不半装，错误定位到具体项 |
| 7 | 停用 Skill | 运行时不再提供 |
| 8 | 未授权角色调用 | 拒绝并审计 |
| 9 | 启停/授权变更 | 写入审计通道 |
| 10 | 已发布快照不可变 | 发布后 digest 不变 |

---

## 7. 单元测试

```bash
cd services/admin-api
PYTHONPATH=. python -m pytest \
  tests/test_skill_lifecycle.py \
  tests/test_skill_package_validator.py \
  -o asyncio_mode=auto -q

cd services/chat-api
PYTHONPATH=. python -m pytest \
  tests/test_skill_runtime_load.py \
  tests/test_skill_authorization.py \
  -o asyncio_mode=auto -q
```

---

## 8. 说明

- 本特性为回溯固化既有能力，目标是把现有行为写成可验收契约，防止回归
- 版本快照不可变：发布后 release 文档不被修改
- 组织级存储：MongoDB skills + organization_skill_releases（digest 去重）
- 与特性 001（gatekeeper）联动：Skill 调用授权与审计复用 001 权限码
- 与特性 006（position-rbac）联动：角色 skillAccessMode/skillIds 决定 Skill 可见面
