# Implementation Plan: 业务线维度删除

**Branch**: `048-business-line-removal` | **Date**: 2026-10-31 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/048-business-line-removal/spec.md`；证据与删除清单见 `specs/035-cost-attribution/review-2026-10-30-dimension-source-audit.md` §4.1–§4.3

**Note**: 纯删除，无新能力。文档侧已完成（035 spec/tasks/checklists 于 2026-10-30 改完），本计划只让代码跟上。

## Summary

删掉成本归集里的「业务线」维度：后端 `_resolve_business_line()` 与其归集块、响应键 `businessLineAttribution`；前端标签/类型/来源数组；测试里的相关断言。删除后成本段由 6 段变 5 段（租户/用户/部门/Agent/项目），其余口径不变。

## Technical Context

**Language/Version**: Python 3.11+（admin-api）；TypeScript 5（admin-web）

**Primary Dependencies**: `services/admin-api/app/api/routes/dashboard.py`（`_resolve_business_line` / `_resolve_org_attribution` / `_attribution_dimensions`）、`apps/admin-web/src/views/dashboard/DashboardPage.vue`、`services/admin-api/tests/test_cost_attribution_035.py`

**Storage**: 无变更（`token_usage_logs` 从未有 `is_business_line`，无需迁移）

**Testing**: pytest（admin-api 成本归集测试）+ 前端 `node scripts/check_sfc.mjs` + `vue-tsc --noEmit`

**Target Platform**: admin-web + admin-api

**Project Type**: web-app + web-service（删除型改动）

**Performance Goals**: 无（删除后每次成本查询少一次组织树反查，略有改善）

**Constraints**: 前端与后端同批发布（或前端先行）；不得改动其余五段的键名与结构

**Scale/Scope**: 3 个文件（后端 1 + 前端 1 + 测试 1）+ 1 处文档标记

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 035 文档先改（2026-10-30），本 spec 记录删除依据，代码随后。
- **II. Enterprise Production Readiness**: ✅ 删除的是**假数据源**，删除即修正；对账（`reconciles`）必须仍绿，这是"删了没伤到别人"的硬判据。
- **III. Security and Data Protection**: ✅ 无权限面变化。
- **IV. Cross-Platform and i18n**: ✅ 只删文案，不新增。
- **V. Observability and Simplicity**: ✅ 减少一个恒为单桶的维度，降低误读风险；不新增日志/指标。

## Project Structure

### Documentation (this feature)

```text
specs/048-business-line-removal/
├── spec.md
├── plan.md              # 本文件
├── tasks.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
services/admin-api/app/api/routes/dashboard.py   # 【改】删 _resolve_business_line + business_line 归集块 + 返回键
apps/admin-web/src/views/dashboard/DashboardPage.vue  # 【改】删标签 / 来源数组项 / 类型定义
services/admin-api/tests/test_cost_attribution_035.py # 【改】删业务线断言与用例，保留五段
specs/035-cost-attribution/review-...md          # 【改】§4.3 标注"代码已完成"
```

**Structure Decision**: 不新增文件，只在既有三处删除；与 046/047 共享 `dashboard.py` 与 `DashboardPage.vue`，但改的是不同位置（048 删维度段，046 改空间→项目，047 加告警卡片），可并行，注意同一文件合并冲突。

## 依赖与顺序

- **与 046 的 T028/T029 强耦合**：同一函数 `_attribution_dimensions()` 既要删业务线段又要改空间段，**建议同批提交**，避免两次动同一块。
- **与 047 无耦合**（047 加卡片、048 删维度），可并行。
- 发布顺序：前端先（忽略多余字段安全）或同批；后端先会让旧前端读到 `undefined`。

## Complexity Tracking

无违反宪法项，无需说明。
