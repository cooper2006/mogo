# Implementation Plan: SkillHub Marketplace & Skill Lifecycle

**Branch**: `004-skillhub-lifecycle` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 回溯规约，固化既有行为。plan 把"现有实现事实"技术化为可验收契约，不引入新架构。

## Summary

本特性不新增模块，把 `admin-api/skill_lifecycle`（组织 Skill 草稿/发布/版本/反馈）与 `chat-api/skills + skill_packages`（ZIP 安装/校验/分享/更新）两条既有路径写成技术契约。交付物：data-model.md（skills 集合 + releases 文档 + 校验产物字段）、contracts/lifecycle-contract.md、contracts/package-contract.md、quickstart.md。

## Technical Context

**Language/Version**: Python 3.13（沿用 admin-api/chat-api 既有栈）

**Primary Dependencies**: MongoDB（skills 集合 + organization_skill_releases）+ 既有 ZIP 校验器（`skill_packages/validator.py`）

**Storage**: MongoDB `skills`（组织 Skill 行，含 draft/published 态与 digest）+ `organization_skill_releases`（不可变版本快照）

**Testing**: pytest（admin-api 既有 + chat-api skill_packages 测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 既有服务契约化（brownfield）

## 现有实现事实（contract 依据）

### 组织 Skill 生命周期（admin-api/services/skill_lifecycle.py）
- 集合：`skills`（组织行）+ `organization_skill_releases`（版本）
- 字段快照 `FIELDS = (name, description, scenario, type, config)`；`digest()` = sha256(排序 JSON)
- 状态机：
  - `initialize` → `authoring_mode=platform, publication_status=draft, draft_revision=1, has_unpublished_changes=True`
  - `save` → revision 递增；`has_unpublished_changes = digest(draft) != published_digest`
  - `publish` → 生成不可变 release（digest + snapshot + release_notes + created_at），版本号去重（已存在则 `FileExistsError`），skill 切 `published` 态
  - `releases` → 最近 20 条，时间倒序，回看不改当前已发布态
  - `_next` 自动递增版本；`_version` 归一化
- 路由（`api/routes/skill_lifecycle.py`）：`POST /{skill_id}/publish`、`GET /{skill_id}/releases`、`GET /{skill_id}/feedback`
- 反馈：`services/organization_skill_feedback.py`

### ZIP 安装与包校验（chat-api）
- 校验器：`services/chat-api/app/services/skill_packages/validator.py`
  - `validate_skill_zip(content) -> ValidatedSkillPackage`
  - `SkillPackageError(code, message, file, field)` + `detail()` 结构化错误
  - `_safe_zip_path`（防 zip slip）、`_frontmatter`（SKILL.md 元数据解析）、`_bool_field/_bool_value`
  - `ValidatedSkillPackage.package_summary()`
- 安装入口：
  - `api/endpoints/skill_package_install.py`：`install_personal_skill_zip`、`install_organization_skill_zip`
  - `enterprise_capabilities/skills/skillhub_install.py`：`skillhub_install`（SkillHub 来源安装）
- 分享/更新：`api/endpoints/skill_shares.py`、`skill_share_direct.py`、`skill_updates.py`、`skill_lifecycle.py`

### 运行时授权与审计
- 运行时目录：`enterprise_capabilities/runtime/catalog.py` + `adapters.py`（Skill 注册/加载）
- 审计：`admin-api/app/system_audit`（skills 资源已在 constants："skills": "Skill 管理"）
- 与特性 001 的关系：Skill 调用授权/审计复用 001 的权限码模型与审计落点（001 尚未实现，本契约以"审计通道已存在"为前置）

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过：spec 已固化既有行为 |
| II. Enterprise Production Readiness | 通过：不可变版本 + digest 去重 + zip-slip 防护 |
| III. Security | 通过：`_safe_zip_path` 防 zip-slip；授权与审计可查 |
| IV. i18n | 通过：Skill 管理面文案既有 |
| V. Observability | 通过：release 版本可回看 |

## Project Structure

```text
specs/004-skillhub-lifecycle/
├── plan.md              # 本文件
├── data-model.md        # skills / organization_skill_releases 字段契约
├── contracts/
│   ├── lifecycle-contract.md  # 草稿/发布/版本/反馈状态机
│   └── package-contract.md    # ZIP 校验 schema / 安装 / 分享 / 更新
└── quickstart.md        # 安装/发布/回看 + 各场景验证
```

源码不改动（brownfield 契约化）；如需修回归，以 tasks.md 登记修复项。

## Open Questions
- OQ-1: ZIP 包是否有签名/完整性校验（spec FR-5 写"结构/签名/版本约束"，需确认现有是否含签名）
- OQ-2: Skill 启停/按角色授权当前落在哪张表/哪个服务（catalog 还是 admin skills 路由）？
- OQ-3: 安装/更新/分享操作当前是否已写审计？落点是 system_audit 还是 events？

## 下一步
`/speckit-clarify` 消解 OQ → 补齐 data-model.md / contracts / quickstart → `/speckit-checklist` → `/speckit-tasks` → `/speckit-analyze`。
