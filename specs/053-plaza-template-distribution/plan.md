# Implementation Plan: 广场模板分发（053-plaza-template-distribution）

**Branch**: `053-plaza-template-distribution` | **Date**: 2026-11-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/053-plaza-template-distribution/spec.md`

**Note**: **全新特性**（StaffDeck 整合方案 §4.4 立项，代码尚未开工）——SOP 模板可先行（不依赖 051），员工模板克隆依赖 051 B1；tasks 全部未勾选。

## Summary

在 045 资产中心与 016 市场之上扩展模板分发：

- **模板类型（admin-api）**：`capability_assets` 扩 `employee_template` / `sop_template`；新模块 `app/services/templates/`（模板 CRUD + 版本 + 上架门禁接线 + 克隆服务）。
- **上架门禁**：SOP 模板过 032 评估卡点（复用 `skill_eval` 既有门禁范式）；员工模板校验档案引用；上架走 001 审批。
- **克隆**：深拷贝定义到克隆者名下（SOP → `dag_definitions` 新定义；员工 → 051 `employees`），记录 `template_ref`；凭证不复制（034）。
- **版本生命周期**：新版本提示 + 手动升级（整份替换 + 旧快照，002）；下架不伤副本。
- **广场前端**：user-web 门户侧广场页（目录/详情/克隆/版本提示）；admin-web 模板管理页。

## Technical Context

**Language/Version**: Python 3.13（admin-api / chat-api）；Vue 3 + TypeScript（双前端）

**Primary Dependencies**: 045 capability_assets、016 市场监控、001 审批、032 skill_eval 门禁、002 版本化、034 凭证口径、037 门户申领、010 dag_definitions；051 employees（员工模板，软依赖）；**不引入新第三方依赖**

**Storage**: 新增 `asset_templates` / `template_clones` 集合（027 门面双后端）；模板版本内容快照内嵌模板文档；副本落既有实体集合（dag_definitions / employees）

**Testing**: pytest 双服务（admin-api `tests/test_templates_admin.py`、chat-api 克隆消费侧）：门禁三类拒绝/克隆原件不变性（哈希）/版本不强制覆盖/下架不伤副本/凭证零明文；前端 SFC + vue-tsc

**Target Platform**: Docker Compose（admin-api + chat-api + 双前端）

**Project Type**: web-service 全栈特性（市场扩展）

**Performance Goals**: 广场目录查询走既有资产列表索引口径；克隆为一次性深拷贝（定义尺寸受编排 YAML 既有约束）

**Constraints**: 原件只读语义（非上架者不可改）；凭证零明文（FR-004）；跨租户 fail-closed；不强制覆盖副本；OQ-1~OQ-4 clarify 前不进入实现

**Scale/Scope**: admin-api 1 新模块 + 资产类型扩展 + 门禁接线；chat-api 克隆消费侧（dag_definitions/employees）；双前端各 1 页；0 新依赖

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 三件套先于代码；七决策拍板，四 OQ 登记。
- **II. Enterprise Production Readiness**: ✅ 门禁 fail-closed（评估/引用/测试集三类拒绝）；克隆/升级/下架全审计；无不可观测路径。
- **III. Security and Data Protection**: ✅ 凭证零明文（模板与克隆产物扫描断言）；租户隔离；原件只读防越权修改；上架审批留痕。
- **IV. Cross-Platform and i18n**: ✅ 双前端中英双语（FR-010）。
- **V. Observability and Simplicity**: ✅ 分发体系全部复用（045 坐标/016 质量/001 审批/032 门禁/002 版本）；不新建评分与计量；升级用整份替换而非三方合并（YAGNI）。

## Project Structure

### Documentation (this feature)

```text
specs/053-plaza-template-distribution/
├── spec.md
├── plan.md              # 本文件
├── tasks.md             # 全部未勾选
└── checklists/requirements.md
```

### Source Code (repository root)

```text
services/admin-api/app/services/templates/
├── __init__.py            # 【新增】
├── model.py               # 【新增】AssetTemplate / TemplateVersion / TemplateClone
├── repository.py          # 【新增】asset_templates / template_clones（027 门面）
├── publish.py             # 【新增】上架门禁（032 接线 + 引用校验）+ 审批
├── clone.py               # 【新增】深拷贝 + template_ref + 凭证剥离
└── upgrade.py             # 【新增】版本提示 + 手动升级（整份替换 + 快照）

services/admin-api/app/api/routes/
└── templates.py           # 【新增】模板管理 + 广场查询 + 克隆/升级端点

services/admin-api/app/services/capability_assets/
└── registry.py            # 【修改】asset_type 扩两类模板

services/chat-api/app/orchestration/
└── store.py               # 【修改】克隆 SOP 落 dag_definitions（克隆者名下）+
                           #  含审批节点定义的审批人租户重解析（050 联动）

apps/user-web/src/views/plaza/      # 【新增】广场页（目录/详情/克隆/版本提示，i18n）
apps/admin-web/src/views/templates/ # 【新增】模板管理页（i18n）

services/admin-api/tests/test_templates_admin.py  # 【新增】
```

**Structure Decision**: 模板本体与分发逻辑放 admin-api（管理面与市场同侧，045/016 先例）；副本落实体集合（SOP → chat-api dag_definitions，员工 → employees）保持"副本即普通实体"——副本后续走一切实体既有路径（编排执行/员工会话/申领），不给副本加特殊运行时语义。含转人工节点的 SOP 克隆时审批人引用按克隆者租户重解析（050 联动点）。

## Complexity Tracking

> 无 constitution 违规。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |

**已评估并拒绝的复杂度**：① 三方合并升级——冲突解决语义复杂且无首期场景，整份替换 + 旧快照（002）足够。② 副本特殊运行时——副本即普通实体，避免"模板副本"旁路语义。③ 跨租户模板市场——数据出域与授权面扩大，community 版租户内即可。④ 新建模板评分——016 质量信号承接（048 教训：不建无写方体系）。