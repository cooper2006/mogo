# Implementation Plan: 统一门户 + 自助申领（037-unified-portal）

**Branch**: `037-unified-portal` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/037-unified-portal/spec.md`

**Note**: 本计划为**全新特性的事前设计**——代码尚未开工，先过 Constitution Check，再按 tasks.md 的 Phase 0→3 推进。

## Summary

在既有 monorepo 内落地员工侧「应用门户」：chat-api 新增终端用户侧端点（目录/申领/我的申领，end_user 会话鉴权），admin-api 新增管理侧端点（上架/下架/审批队列），两侧经共享 MongoDB 集合 `portal_listings` / `portal_requests` 协作；申领审批复用 001 审批语义（防自审、fail-closed、审计），开通经 `permission_grants` 用户级授权实现「开通即用、回收即失效」；user-web 新增门户页（目录/详情/我的申领，承载于既有 SPA），admin-web 新增上架管理与审批队列视图。形态严格遵循 ADR-7：Web only，移动触达由 013 IM 入口覆盖，029 SSO 提供免登分发。

## Technical Context

**Language/Version**: Python 3.11+（chat-api 与 admin-api，FastAPI + pydantic v2）；TypeScript 5（user-web 与 admin-web，Vue 3 + naive-ui）

**Primary Dependencies**: FastAPI、pydantic v2、MongoDB（`app.core.db.get_db()`，不引入 Redis/新存储）；前端 Vue 3 SFC + naive-ui + axios（`createApiClient`）+ `@vue/compiler-sfc`（仅校验）

**Storage**: 新增 `portal_listings` 集合（上架标记，chat-api 读 / admin-api 写）与 `portal_requests` 集合（申领单状态机，chat-api 写 / admin-api 审批读写）；复用 `permission_grants`（开通授权）、`skills` / `capability_assets`（目录数据源）、022 审计落点

**Testing**: pytest（chat-api `tests/test_portal_requests.py` 状态机/幂等/防自审；admin-api 契约测试 `permission_grants` 字段兼容 + 上架/审批）；前端 `@vue/compiler-sfc` 单文件编译校验；E2E 脚本覆盖「浏览→申领→审批→开通→调用→回收」

**Target Platform**: Docker Compose（chat-api / admin-api / user-web / admin-web）；自托管 Linux/Docker

**Project Type**: web-service ×2（chat-api、admin-api）+ web-app ×2（user-web、admin-web），pnpm 工作区

**Performance Goals**: 目录列表一次聚合查询（`portal_listings` + 资产集合 join 在应用层完成，首期不做物化视图）；申领单状态迁移为单文档条件更新（并发安全）；授权写入/移除即时生效（`permission_grants` 无缓存语义，天然满足回收实时性）

**Constraints**: 不改 029 端点与票据语义；不改 001 门禁矩阵与既有审批表；不建 H5/App/桌面端（ADR-7）；目录仅返已上架 active；防自审（requester ≠ approver）；跨服务集合字段契约须有契约测试防漂移；审计失败不阻断主流程

**Scale/Scope**: 2 个新集合；2 个新路由文件（chat-api `portal.py` + admin-api `portal_admin.py`）；1 个新服务模块（chat-api `app/services/portal/`）；前端 2 处新增（user-web 门户组件 + api、admin-web 门户视图）；0 个新依赖、0 个新服务

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本三件套先行，spec 已固化 7 项已定决策与 FR-001..017；tasks.md 全部未勾选，实现未开工。
- **II. Enterprise Production Readiness**: ✅ 失败路径 fail-closed（无授权调用被门禁拒、审批并发幂等、防自审、资产 offline 时申领单自动 rejected）；上架/下架/审批/开通/回收全审计；无新部署形态（复用既有 Compose 服务）。
- **III. Security and Data Protection**: ✅ 开通授权走 001 既有 `permission_grants` 机制（不平行造授权表）；目录按租户隔离（end_user 会话）；跨租户由 029 既有校验拒绝；审批防自审沿用 001「审批与消费分离」教训；审计不落 PII（asset_key + user_id）。
- **IV. Cross-Platform and i18n**: ✅ Web 形态交付（ADR-7），移动触达经 013 IM；user-web/admin-web 新文案走 `t()` 中文 key 回退，保持双语可用。
- **V. Observability and Simplicity**: ✅ 复用既有基座（user-web axios client、admin-web 视图模式、001 审批语义、016/018 数据、029/013 链路）；新增集合仅 2 个且职责单一；无新框架/依赖，符合 YAGNI。

## Project Structure

### Documentation (this feature)

```text
specs/037-unified-portal/
├── spec.md              # 特性规约（本文件引用的 spec）
├── plan.md              # 本文件
└── tasks.md             # 任务清单（全新特性，全部未勾选）
```

### Source Code (repository root)

```text
services/chat-api/
├── app/api/endpoints/portal.py            # 新增：目录/详情/申领/我的申领（end_user 会话鉴权，挂 /askai-api 基座）
├── app/services/portal/
│   ├── __init__.py
│   ├── listings.py                        # 新增：portal_listings 读写与目录聚合（读 skills/capability_assets）
│   └── requests.py                        # 新增：申领单状态机（条件更新幂等 + 防自审 + 审计）
└── tests/test_portal_requests.py          # 新增：状态机/幂等/防自审/并发审批单测

services/admin-api/
├── app/api/routes/portal_admin.py         # 新增：上架/下架 + 审批队列 + 批准/拒绝（管理员鉴权）
├── app/api/routes/gatekeeper_internal.py  # 复用参考：服务间内部端点模式（如需 chat-api→admin-api 内部调用）
├── app/governance/permission_grants.py    # 复用：开通授权/回收的字段契约与审计口径（不修改，仅按契约写集合）
└── tests/test_portal_admin.py             # 新增：上架即时生效 + 审批决策 + grants 字段契约测试

apps/user-web/src/
├── api/portal.ts                          # 新增：门户 API 客户端（createApiClient 基座）
└── components/portal/                     # 新增：PortalCatalog.vue / PortalDetail.vue / MyRequests.vue（App.vue defineAsyncComponent 挂接）

apps/admin-web/src/
├── api/portal.ts                          # 新增：上架/审批管理 API 客户端
└── views/portal/                          # 新增：PortalListingPage.vue（上架管理）+ PortalApprovalPage.vue（审批队列）
```

**Structure Decision**: 复用既有双服务 + 双前端布局，不新增服务与部署单元。关键切分：**终端用户侧 API 落 chat-api**（user-web 的 `/askai-api` 基座与 029 换票同域，end_user 会话鉴权零新增），**管理侧 API 落 admin-api**（admin-web 既有基座 + `get_current_admin_user` 鉴权），两侧经共享 MongoDB 集合协作——此为仓库既有模式（016 `quality_metrics` 即由 chat-api 写、admin-api 读同一集合）。开通授权直接按 `permission_grants.py` 的字段契约写集合而非新造授权表，保证 001 门禁 RBAC 层天然认可；字段契约由 admin-api 侧契约测试锁定防跨服务漂移。

## Complexity Tracking

> 无 constitution 违规，无需复杂度论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |
