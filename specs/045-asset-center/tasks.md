# Tasks: 资产中心枢纽（045-asset-center）

> 依据 `specs/045-asset-center/spec.md` 与 `plan.md`。批次划分对应方案 §5。
> 格式：`[ID] [P0/P1/P2] [US] 描述`。完成一项勾一项 `[x]`。

## Phase 0: 研究与澄清

- [x] [T0] 调研后端 018/036/037 现状与前端四页行为（已完成）。
- [x] [T0] 确认路由前缀叠加坑与 trust `ASSET_TYPES` 不含 capability_asset（已完成）。
- [x] [T0] 立项：spec.md / plan.md 已建（2026-10-29）。

## Phase 1: 后端能力资产只读列表接口（批次 1 · P0）

- [x] [T1] [P0][US1] `capability_assets.py` 新增 `admin_router = APIRouter(prefix="/capabilities", tags=["capability-assets-admin"])`，`GET /list` 用 `get_current_admin_user`，返回 `capability_assets` 文档列表，支持 `kind` / `state` 查询参数。复用 `PersistedCapabilityRegistry.list_all`。
  - 验收：`router.py` include `admin_router` 不加 prefix；最终路径 `/api/v1/capabilities/list`。
- [x] [T2] [P0][US1] 新建 `services/admin-api/tests/test_capability_assets_admin.py`：覆盖 admin JWT 鉴权（无 token 401 / 非法 401）、列表返回结构、`kind` / `state` 过滤。
  - 验收：pytest 全绿（2026-10-29 复跑 5 passed）。

## Phase 2: 前端资产中心枢纽页（批次 1 · P0）

- [x] [T3] [P0][US1] 新建 `apps/admin-web/src/api/capabilities.ts`：`fetchCapabilities(params?: { kind?: string; state?: string })`，调用 `GET /api/v1/capabilities/list`，返回 `CapabilityAsset[]`（含 `asset_id/name/kind/state/contract/version/owner_role/endpoint/method/a2a_exposed`）。
  - 验收：类型定义与后端文档字段对齐。
- [x] [T4] [P0][US1] 新建 `apps/admin-web/src/views/assets/AssetsPage.vue`：并发调 4 个 API（capabilities/skills/trust-ratings/portal-listings/approvals），按 `(asset_type, asset_key)` join，渲染资产卡片（类型徽标 / 名称+asset_key / 评级徽标 / 上架徽标 / grantCount / recentUsedCount / 最近申领明细）。类型下拉 4 项筛选。空状态区别于错误。
  - 验收：缺失评级显示"未评级"；空状态展示；类型筛选生效。
  - 备注：实际落地路径为 `apps/admin-web/src/views/AssetsPage.vue`（表格视图），join 口径一致。
- [x] [T5] [P0][US1] `routes.ts` 新增 `/assets` 路由（`AssetsPage`）+ 菜单入口（导航中加"资产中心"）。
  - 验收：菜单点击进入 `/assets`。

## Phase 3: 五块互链（批次 2 · P1）

- [x] [T6] [P1][US3] `SkillsPage.vue` 评级徽标点击：`goTrustRating` 改为 `router.push('/trust-ratings?asset=skill:' + skillId)`（原为跳整个列表页）。
  - 验收：点评级徽标跳评级页并带 asset 定位。
  - 备注（2026-10-29）：已落地 `?asset=skill:<id>`；评级页解析该参数后定位并自动打开变更弹层。
- [x] [T7] [P1][US3] `TrustRatingPage.vue`：资产列加类型徽标（skill/agent/workflow）+ 上架标志列 + 最近申领统计列；资产名旁加"管理"按钮（打开变更弹层）；支持 `?asset=skill:<key>` 定位并打开该行变更弹层。
  - 验收：类型徽标 / 上架标志 / 申领统计显示；?asset 定位生效。
  - 备注（2026-10-29）：类型徽标 NTag、上架列、最近申领统计列（申请数 + 最近时间）、管理按钮（跳技能配置 / 资产中心）、`?asset=` 定位 + 自动打开变更弹层均落地。
- [x] [T8] [P1][US3] `PortalListingPage.vue`：类型下拉改 4 项（skill/mcp/tool/connector）；资产选择改下拉：skill→`fetchSkills`，mcp/tool/connector→`fetchCapabilities({kind})`；选中填 `assetKey`；列表加评级列；支持 `?asset=<type>:<key>` 预填。
  - 验收：下拉选择资产；?asset 预填生效；评级列显示。
  - 备注（2026-10-29）：改为统一读 `useAssetCatalog` 共享数据源（skills + capabilities 一次 join）；支持 `asset_type`/`asset_key` 预填；不可用禁上架。
- [x] [T9] [P1][US4] `PortalApprovalPage.vue`：`applied` 态按 `asset_key` 聚合为卡片（资产名 + 类型徽标 + 申请人列表 + 申请数 + 状态徽标 + 批准/拒绝按钮）；卡片点击跳 `/assets?asset=<type>:<key>`；`all` 态保留平铺。支持 `?asset=<type>:<key>` 定位。
  - 验收：applied 卡片化；点击跳资产中心；all 平铺。
  - 备注（2026-10-29）：applied 卡片化（`appliedGroups` 聚合）+ 卡片点击跳资产中心 + 申请人明细内批准/拒绝 + 详情弹层评级/owner/上架状态；all 态保留表格。`?asset=` 定位沿用既有 query 过滤。
- [x] [T10] [P1][US2] `apps/user-web` 门户详情（`PortalDetail`）加"管理状态"锚点：评级徽标 + 上架状态 + 跳 `/assets?asset=<type>:<key>`。
  - 验收：门户详情显示管理状态并可跳转。
  - 备注（2026-10-29）：只读锚点已落地（评级徽标 + 上架状态 + owner + 跳 admin `/assets?asset=<type>:<key>`）。

## Phase 4: 接线与验收（批次 3 · P2）

- [x] [T11] [P2][US2] 资产中心 ↔ 四块双向可达：资产中心卡片评级/上架/申领入口跳对应页；四页回跳资产中心。`grantCount` 与 `permission_grants` 同源。
  - 验收：双向互链可达；grantCount 口径一致。
  - 备注（2026-10-29）：资产中心 → 四页互链已通；门户上架 / 门户审批页头新增「资产中心」回跳按钮；评级页「管理」按钮跳资产中心；技能页经菜单可达。
- [x] [T12] [P2] 验收：后端 pytest 全绿；前端 `pnpm lint` / 类型检查通过；空状态 / 缺失评级 / 0 申领 / 未上架 / 未发布技能容忍。
  - 验收：测试与 lint 通过。
  - 备注（2026-10-29）：`test_capability_assets_admin.py` 5 passed；admin-web / user-web `vue-tsc` 通过、eslint 0 error；边界容忍已按"未评级 / — / 未上架 / 空态"分支处理。

## Dependencies & Execution Order

### Phase Dependencies

- Phase 1（后端接口）→ Phase 2（前端页）→ Phase 3（互链）→ Phase 4（验收）。
- T1 → T2（接口先于测试）；T3 → T4（API 先于页）；T4 → T5（页先于路由）。

### Within Each Phase

- T1/T2 可并行（接口与测试同时写）；T3/T4/T5 顺序；T6–T10 可并行（不同页）。

## Implementation Strategy

### MVP First（批次 1）

T1–T5：后端列表接口 + 资产中心页 + 路由。完成后资产中心页可展示四类资产统一视图（US1）。

### Incremental（批次 2）

T6–T10：五块互链。完成后全链路可达（US2/US3/US4）。

## 验收状态

（2026-10-29 回填，T1–T12 全部完成）

- 后端：`services/admin-api/tests/test_capability_assets_admin.py` → 5 passed。
- 前端：`apps/admin-web` 与 `apps/user-web` `vue-tsc --noEmit` 通过；改动文件 eslint 0 error。
- §5 方案 B 五块互链：门户上架资产下拉（不可用禁上架）、评级页类型徽标 / 上架列 / 最近申领统计列 / 管理按钮 / `?asset=` 定位并自动开变更弹层、技能卡片上架小标与评级点击 `?asset=skill:<id>`、审批页 applied 聚合卡片 + 详情评级 / owner、user 门户详情管理状态锚点。
- 双向互链：资产中心 ↔ 评级 / 上架 / 审批 / 技能页；上架与审批页头可回跳资产中心。
