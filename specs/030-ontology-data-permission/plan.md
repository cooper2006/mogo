# Implementation Plan: 本体数据权限（ontology data-scope permission）

**Branch**: `030-ontology-data-permission` | **Date**: 2026-10-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/030-ontology-data-permission/spec.md`（设计闭环于 `docs/ontology-permission-merge-plan.md` + `docs/MOGO-Web应用集成方案.md` §5.4–§5.9）

## Summary

给本体（ontology）域新增一层**数据范围权限**，与既有 RBAC 功能权限**正交**。落点三处：① 建表（`mesc_ontology_grant` / `mesc_ontology_class_detail` / `mesc_ontology_perm_audit` + 通用 `sys_config`），双后端同构；② 运行时按 `(tenant_id, user_id)` 解析**可见本体清单**（fail-closed，进程内 60s 缓存），在 `business_semantic_index.semantic_search` 按 `ontology_id` 过滤命中；③ 管理端（admin-api 6+2 端点 + 1 内部接口 / admin-web 清单页 + 用户授权弹窗）完成授权录入与灰度开关。判权以 `ontology_id` 为准，`entity_type` 仅作类型标签。数据访问走**原生 repository**（PG SQL / mongo motor），**不经** `pg_compat` 通用壳门面。

## Technical Context

**Language/Version**: Python 3.13（chat-api / admin-api）/ TypeScript + Vue 3（admin-web）

**Primary Dependencies**: FastAPI（两服务既有）；psycopg3 + `psycopg_pool`（PanWeiDB 异步池，既有 `app/core/pg.py`）；motor（mongo 后端）；naive-ui（admin-web 既有）

**Storage**: PanWeiDB（`deploy/pg/ontology_permission.sql`）+ MongoDB（`deploy/mongo/ontology_permission.js`），两份字段一一对应；主体侧表（`end_user_org_relations` / `end_user_position_roles` / `org_units`）与清单来源（`business_entity_index`）沿用**既有通用壳表**，走 `get_db()` 门面

**Testing**: `pytest`（admin-api `tests/test_ontology_permission_service.py` 20 条；chat-api `tests/services/test_ontology_permission.py` 11 条 + `test_semantic_search_ontology_filter.py` 6 条）；`vue-tsc --noEmit`（admin-web 类型检查）

**Target Platform**: Linux 服务（chat-api / admin-api）/ 浏览器（admin-web）

**Project Type**: web-service（双后端 API）+ frontend（admin-web 管理页）

**Performance Goals**: 缓存命中零 DB 往返；未命中时对授权表**单次**批量查询（不做 N+1）；解析 p95 < 50ms

**Constraints**: 严格 fail-closed（异常→空集且不写缓存）；PanWeiDB `sql_compatibility=A` 坑规避（`''`=NULL、`NOT(@>)` 用 `IS NOT TRUE`、jsonb 走 `#>`/`#>>`、占位符顺序）；不改既有 `semantic_search` 默认行为（`visible_ontology_ids=None` 即不过滤）

**Scale/Scope**: 每租户本体数量级 10²，授权行数量级 10³–10⁴；单次解析主体集合规模 = 1(tenant) + org(含下级) + role + 1(user)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Specification-First（NON-NEGOTIABLE）**：⚠️ **本特性为回溯补规格** —— 建表 + 运行时解析 + 管理端 API/前端代码**先于本 spec 落地**（与 027 数据后端迁移的处理方式一致：代码先于规格）。本 spec/plan/tasks 已补齐并把实现口径固化，剩余任务见 `tasks.md`。后续同类特性必须先出 spec 再动代码。
- **Agent Operating Rules（AGENTS.md）**：仅改本轮必要文件、不顺手重构；只 `git add` 具体路径（禁 `git add -A`）；不越出工作区；每轮实际修改后写入 obsidian vault 当日 session-log（`docs/WORK_LOG.md` 自 2026-10-17 停更，见 constitution v1.2.0）。✅ 规划已约束改动面。
- **双后端对等**：新表必须双后端可用（027 迁移期硬约束）。✅ 已产出 PG DDL + mongo JS 两份。
- 无 Constitution 违规需 Complexity Tracking 声明（见文末）。

## Project Structure

### Documentation (this feature)

```text
specs/030-ontology-data-permission/
├── plan.md              # 本文件
├── spec.md              # 特性规约（4 个用户故事 / 27 条 FR）
└── tasks.md             # 任务拆分（6 阶段 + 测试）
```

> 权威设计见 `docs/ontology-permission-merge-plan.md`（合并方案，5 项决策已拍板）与 `docs/MOGO-Web应用集成方案.md` §5.4–§5.9。本特性为回溯补规格，不另出 research / data-model / contracts 独立产出（接口契约已在 spec FR-019–FR-024 固化）。

### Source Code (repository root)

```text
# 建表（双后端）
deploy/pg/ontology_permission.sql                  # 3 张 mesc_* + sys_config（结构化列，复合主键）
deploy/mongo/ontology_permission.js                # 同构集合 + $jsonSchema 校验器 + 索引

# 运行时（chat-api）
services/chat-api/app/services/ontology_permission.py     # visible_ontology_ids / ontology_scope_snapshot / 缓存 / 审计
services/chat-api/app/services/business_semantic_index.py # 生效点：SemanticHit/EntityRecord 加 ontology_id；semantic_search 按可见集过滤

# 管理端（admin-api）
services/admin-api/app/ontology_permission/constants.py   # 表名 / 枚举 / 复合键
services/admin-api/app/ontology_permission/repository.py  # 原生双后端数据访问（结构化列）
services/admin-api/app/ontology_permission/service.py     # 配置 / 清单 / 可见集 / 授权写入侧（审计 + rev）
services/admin-api/app/ontology_permission/subjects.py    # 四态主体展开（tenant + org 含下级 + role + user）
services/admin-api/app/api/routes/ontologies.py           # 13 条管理端路由
services/admin-api/app/api/routes/ontology_permission_internal.py  # 内部接口（服务凭证）
services/admin-api/app/api/router.py                      # 路由注册

# 管理端（admin-web）
apps/admin-web/src/api/ontologies.ts                      # API 层
apps/admin-web/src/icons/OntologyIcon.ts                  # 菜单图标
apps/admin-web/src/views/ontologies/OntologyCatalogPage.vue          # 清单页（只读 + 开关 + 同步）
apps/admin-web/src/views/ontologies/UserOntologyPermissionDialog.vue # 用户级授权弹窗
apps/admin-web/src/router/routes.ts                       # /ontologies 路由
apps/admin-web/src/views/organizations/OrganizationUsersPage.vue     # 用户行「本体数据权限」入口
```

**Structure Decision**: 沿用既有 monorepo 布局（后端在 `services/`，前端在 `apps/`），不引入新服务。
admin-api 新增独立包 `app/ontology_permission/`（对齐既有 `app/position_roles/` 的包级组织），
避免把结构化表访问混进走通用壳门面的 `app/repositories/`。

## 关键设计取舍

| 取舍点 | 选择 | 理由 |
| --- | --- | --- |
| 结构化列 vs 通用 `doc` JSONB 壳 | **结构化列** | `mesc_*` 需要复合主键 + CHECK + jsonb 子列；通用壳表达不了，且判权热路径需要真实列索引 |
| 走 `pg_compat` 门面 vs 原生 repository | **原生 repository**（决策 A） | 门面假定 `(id, tenant_id, doc, ...)` 单主键 + `ON CONFLICT (id)`；两者不可混用 |
| upsert 实现 | PG：先 UPDATE、`rowcount=0` 再 INSERT；mongo：`replace_one(upsert=True)` | 规避 openGauss `ON CONFLICT ... DO UPDATE` 兼容性风险；同时避免 A 模式空串比较坑 |
| 权限判定键 | `ontology_id`（本体标识） | `entity_type` 是粗粒度类型标签，多本体可共享同一 type，按 type 判权会越权 |
| 缓存失效 | 进程内 60s TTL + 变更递增 `sys_config.rev` | 无 Redis 客户端（两服务均未引入 `redis`），跨进程推送不可用；`rev` 保证变更可被观察与审计 |
| 本体清单来源 | 聚合既有 `business_entity_index`，**不新增表** | 设计 §5.4 的独立副本集合属阶段 4（业务系统对接）；现在新增一张没有数据来源的空表只会增加维护面 |
| 内部接口鉴权 | 复用 `settings.backend_service_token` + `X-MOVO-Service-Token` | 与 `personal_knowledge_internal.py` 同一机制，不引入第二套 |

## 落地阶段映射

| 阶段 | 内容 | 对应 tasks | 状态 |
| --- | --- | --- | --- |
| 0 | 建表入库（PG DDL + mongo JS 执行） | T1–T3 | ✅ 已执行 |
| 1 | chat-api 运行时解析 + 检索生效点 + 测试 | T4–T7 | ✅ 已落地 |
| 2 | admin-api 原生 repository + 服务层 + 路由 | T8–T12 | ✅ 已落地 |
| 3 | admin-api 内部接口 + 配置/审计路由 | T13–T15 | ✅ 已落地 |
| 4 | admin-web 清单页 + 授权弹窗 + 入口 | T16–T20 | ✅ 已落地（待构建验证） |
| 5 | 容器重建 + 端到端冒烟 + 网关放行 `/internal/*` | T21–T25 | ⏳ 待做 |
| 6 | 文档与日志（spec 补录、merge-plan 同步、WORK_LOG） | T26–T28 | ⏳ 待做 |

## Complexity Tracking

> 无 Constitution 违规需声明。本特性**复用**既有 `get_db()` 门面（主体侧壳表）、既有 `gate_events` 审计流、既有服务凭证机制、既有 `position_roles` 包级组织范式；新增面集中在「结构化表 + 原生 repository」这一条 027 迁移期必需的路径上，且该路径已在 `docs/ontology-permission-merge-plan.md` §3.8 记录为决策 A。

**已知未闭环项（须在 tasks 阶段 5/6 收口）**：
1. `/internal/*` 不在网关路由表 → 需显式 `location` + 来源网段限制（设计 §6 约束 6）。
2. 跨进程缓存传播窗口 = 60s TTL 上限（无 Redis），须在文档显式声明。
3. `sourceEntity` / `keyField` 暂为空串（业务系统未接入）。
4. 类明细（`mesc_ontology_class_detail`）已建表与提供仓储，但**列/行过滤尚未接进检索生效点**（列投影 + 行条件叠加属下一阶段）。
