# Implementation Plan: 资产中心枢纽（045-asset-center）

> 依据 `specs/045-asset-center/spec.md` 与 `docs/asset-center-plan.md` 方案 A+B 落地。
> 状态：已立项（2026-10-29）。

## Summary

落地"资产中心"枢纽页 + 四类资产统一坐标 + 五块互链。后端只补一个 admin 只读列表接口 `GET /api/v1/capabilities/list`（复用 018 `PersistedCapabilityRegistry`，不新增写路径）；前端新增 `/assets` 枢纽页，并改造技能页 / 评级页 / 门户上架页 / 门户审批页实现互链。数据靠前端 join，不合并五域数据。

## Technical Context

- **后端**：`services/admin-api`（FastAPI），路由挂 `/api/v1`（`app/main.py` 321 行）。
- **鉴权**：admin JWT → `get_current_admin_user`（`app/api/deps.py`）；既有 service-token 端点（`capability_assets.py` 现有 `router`）不依赖 admin JWT。
- **018 registry**：`services/admin-api/app/services/capability_assets/registry.py` 的 `PersistedCapabilityRegistry` 已实现双 key 写入（`_asset_to_row` 写 `asset_id` + `key`）、`list_all(state=...)` 过滤。`CapabilityAsset` dataclass 字段：`asset_id/name/contract/version/owner_role/state/endpoint/method/a2a_exposed`。
- **036 trust**：`services/admin-api/app/services/trust_rating/ratings.py` 的 `ASSET_TYPES = ("skill", "agent", "workflow")`，**不含 `capability_asset`**；`list_ratings(db, tenant_id, asset_type, visible_to)` 返回原始文档。
- **037 portal**：`services/admin-api/app/api/routes/portal_admin.py`：
  - `_asset_row`：capability_asset 读 `capability_assets` by `asset_id`；skill 读 `db.skills` by `_id`。
  - `_is_active_asset`：capability_asset → `state==active`；skill → `authoring_mode==platform` 时 `publication_status==published` 否则 `True`。
  - `CATALOG_ASSET_TYPES = ("skill", "capability_asset")`：上架 `asset_type` 仅支持这两项（mcp/tool/connector 统一走 `capability_asset`）。
  - `list_listings(published_only)` 已做 `_asset_row` join 并输出 `name` / `is_active_asset`。
  - `list_approvals(status)` 已做 `_asset_row` join，输出 `asset_name` / `can_decide`。
- **前端 admin-web**：Vue 3 + Vite + naive-ui；`apiClient` baseURL `/admin-api`，请求路径写 `/api/v1/...`（反代剥前缀）；路由在 `src/router/routes.ts`；API 层在 `src/api/`。
- **现有四页**：
  - `SkillsPage.vue`：评级徽标 `@click.stop="goTrustRating"` → `router.push({ name: 'TrustRatings' })`（跳到整个列表页，**不带 skill_id**）。
  - `TrustRatingPage.vue`：`skillNames` 只解析 `skill` 类型；行显示 `asset_type/asset_key/level`；无"管理"按钮、无上架标志、无申领统计。
  - `PortalListingPage.vue`：上架表单 `assetType`（skill/capability_asset 两项）+ `assetKey` 手填 + `category`；列表显示 name/asset_key/asset_type/category/published。
  - `PortalApprovalPage.vue`：审批列表平铺，显示 asset_name/asset_key/requester_id/status；有批准/拒绝/回收。
- **路由前缀坑**：`capability_assets.router` 自身 prefix `/api/capabilities`，`router.py` include 时又加 `prefix="/capabilities"`，叠加后实际路径异常（历史遗留，无外部调用者）。**新接口走独立 `admin_router`，prefix 设 `/capabilities`，include 时不加 prefix**，最终路径 `/api/v1/capabilities/list`。

## Constitution Check

- **Specification-First**：spec.md 已立项，先 plan/tasks 后实现 ✅
- **Enterprise Readiness**：新接口为只读，不引入不可观测失败路径；鉴权复用 admin JWT ✅
- **Security**：不新增凭据；admin JWT 已有审计 ✅
- **Cross-Platform / i18n**：前端文案走 `t()` 中英双语；不涉及后端平台差异 ✅
- **Observability**：新接口无副作用，无需额外日志；复用既有审计 ✅

## Project Structure

### Documentation (this feature)

```
specs/045-asset-center/
├── spec.md                       # 本特性规格（已立项）
├── plan.md                       # 本文件
├── tasks.md                      # 实施任务（/speckit-tasks 生成）
└── checklists/requirements.md    # 质量门禁（/speckit-checklist 生成）
```

### Source Code (repository root)

**后端（admin-api）**：
```
services/admin-api/app/api/routes/capability_assets.py
    └── 新增 admin_router（prefix="/capabilities"）+ GET /list（admin JWT 只读）
services/admin-api/app/api/router.py
    └── include_router(capability_assets.admin_router)（不加 prefix）
services/admin-api/app/services/capability_assets/registry.py
    └── 复用 PersistedCapabilityRegistry.list_all（不改写路径）
services/admin-api/tests/test_capability_assets_admin.py（新建）
    └── admin JWT 鉴权 / 列表返回 / kind·state 过滤 单测
```

**前端（admin-web）**：
```
apps/admin-web/src/api/capabilities.ts（新建）
    └── fetchCapabilities(kind?) → CapabilityAsset[]
apps/admin-web/src/router/routes.ts
    └── /assets 路由 + 菜单入口
apps/admin-web/src/views/assets/AssetsPage.vue（新建）
    └── 资产中心枢纽页（4 API join + 卡片 + 互链）
apps/admin-web/src/views/skills/SkillsPage.vue（改造）
    └── 评级徽标点击 → /trust-ratings?asset=skill:<id>
apps/admin-web/src/views/trust-ratings/TrustRatingPage.vue（改造）
    └── 资产列加类型徽标 / 上架标志 / 申领统计 / 管理按钮 + ?asset 定位
apps/admin-web/src/views/portal/PortalListingPage.vue（改造）
    └── 类型下拉 4 项 + 资产选择改下拉 + 列表加评级列 + ?asset 预填
apps/admin-web/src/views/portal/PortalApprovalPage.vue（改造）
    └── applied 态卡片化 + ?asset 定位 + 跳资产中心
```

**前端（user-web）**：
```
apps/user-web/src/views/.../PortalDetail.vue（改造）
    └── 加"管理状态"锚点（评级徽标 + 上架状态 + 跳 /assets）
```

## Complexity Tracking

| 维度 | 评估 |
|---|---|
| 后端改动 | 低（1 新只读路由 + 复用 registry + 单测） |
| 前端新增 | 中（1 枢纽页 + 1 API 层 + 路由） |
| 前端改造 | 中（4 页互链 + 1 user-web 锚点） |
| 跨服务 | 无（admin-api 单服务；user-web 只加锚点） |
| 数据迁移 | 无（只读视图，不写库） |
| 测试 | 后端单测 + 前端 lint/类型 |

## 批次划分（对应方案 §5）

### 批次 1（P0，核心）：后端列表接口 + 资产中心枢纽页

1. **T1 后端**：`capability_assets.py` 新增 `admin_router` + `GET /list`（admin JWT，返回 `capability_assets` 文档，支持 `kind`/`state` 过滤）；`router.py` include。
2. **T2 后端测试**：`test_capability_assets_admin.py` 覆盖鉴权 / 列表 / 过滤。
3. **T3 前端 API**：`capabilities.ts` `fetchCapabilities`。
4. **T4 前端页**：`AssetsPage.vue`（4 API join + 卡片 + 类型筛选 + 空状态）。
5. **T5 前端路由**：`/assets` + 菜单。

### 批次 2（P1，互链）：五块互链 + 审批流卡片

6. **T6 技能页**：评级徽标点击 → `/trust-ratings?asset=skill:<id>`。
7. **T7 评级页**：资产列加类型徽标 / 上架标志 / 申领统计 / 管理按钮 + `?asset` 定位。
8. **T8 门户上架页**：类型下拉 4 项 + 资产选择改下拉 + 评级列 + `?asset` 预填。
9. **T9 门户审批页**：`applied` 态卡片化 + `?asset` 定位 + 跳资产中心。
10. **T10 user-web PortalDetail**：加"管理状态"锚点。

### 批次 3（P2，接线与验收）

11. **T11 接线**：资产中心 ↔ 四块双向可达；`grantCount` 与 `permission_grants` 同源。
12. **T12 验收**：后端单测全绿；前端 lint/类型通过；空状态 / 缺失评级容忍。

## 数据流

```
AssetsPage (/assets)
  ├── GET /api/v1/capabilities/list?kind=&state=  → capability_assets[]
  ├── GET /api/v1/skills                            → skills[]
  ├── GET /api/v1/trust-ratings                     → trust_ratings[]
  ├── GET /api/v1/portal/listings?published_only=true → portal_listings[]
  ├── GET /api/v1/portal/approvals?status=applied   → portal_requests[]
  └── join by (asset_type, asset_key)
```

## 验收标准（对应方案 §6）

- P0 全 AC 可达（资产中心页 + 后端接口）。
- P1 五块互链双向可达（技能页 ↔ 评级页 ↔ 门户上架 ↔ 门户审批 ↔ 资产中心）。
- P2 审批流卡片化（applied 态聚合）。
- 缺失评级 / 0 申领 / 未上架 / 未发布技能均容忍。

## 风险与回退

- **路由前缀叠加**：新接口走独立 `admin_router` 规避；不改现有 service-token 端点（无调用者）。
- **capability_asset 无评级**：资产中心容忍"未评级"；如需评级，后续扩展 036 `ASSET_TYPES`（非本期）。
- **portal 上架 asset_type 仅 skill/capability_asset**：前端类型下拉 4 项，mcp/tool/connector 映射为 `capability_asset` + `kind` 过滤。
- **回退**：资产中心为纯前端 join + 一个只读接口，回退只需移除 `/assets` 路由与 `admin_router`，不影响五域既有功能。

## 验收状态

（实施阶段回填）
