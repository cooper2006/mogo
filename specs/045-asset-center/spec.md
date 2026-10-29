# Feature Specification: 资产中心枢纽（Asset Center Hub）

> 状态：已立项（2026-10-29，依据 `docs/asset-center-plan.md` 方案 A+B 落地）。
> 关联 spec：018 capability-asset-registration / 036 trust-rating / 037 unified-portal。
> 跨特性声明：本特性**只加枢纽 + 互链 + 一个能力资产只读列表接口**，不合并五页、不动 RBAC / 037 状态机、不把本体授权 join 进资产卡片。

## 定位（一句话）

把"技能 / 资产评级 / 门户上架 / 门户审批 / 资产使用"五个割裂的功能点，用**一个"资产中心"枢纽页 + 四类资产统一坐标 `(asset_type, asset_key)`** 串成一条生命周期；数据靠前端 join，后端只补一个能力资产只读列表接口 `GET /api/v1/capabilities/list`。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 管理员在资产中心页看到所有已发布技能与已注册能力资产的统一视图（Priority: P1）

作为管理员，我想在 `/assets` 页看到四类资产（技能 / MCP / 工具 / 连接器）的**同一张表**，每行带名称、类型、评级、上架状态、最近申领与最近使用统计，这样我不用在五个页面来回切就能掌握资产全景。

**AC1**：资产中心页调 `GET /api/v1/capabilities/list` + 既有 `GET /api/v1/skills` + 既有 `GET /api/v1/trust-ratings` + 既有 `GET /api/v1/portal/listings`，前端按 `(asset_type, asset_key)` join 成一张表。
**AC2**：技能行 `asset_key` 为 `skills._id`；能力资产行 `asset_key` 为 `capability_assets.asset_id`，`asset_type` 映射为 `skill` / `capability_asset`。
**AC3**：类型下拉筛选 4 项：`skill` / `mcp` / `tool` / `connector`（其中 mcp/tool/connector 对应 `capability_asset(kind=…)`）。
**AC4**：缺失评级（capability_asset 不在 036 `ASSET_TYPES` 内）显示"未评级"，**不阻塞**该行展示（容忍缺失）。
**AC5**：列表为空时显示空状态（区别于"出错"）。

### User Story 2 - 管理员从资产中心下钻到某资产的评级管理 / 上架下架 / 最近申领（Priority: P1）

作为管理员，我想在资产中心点某资产卡片的"评级"徽标跳到该资产的评级管理、点"上架/下架"跳到门户上架页并预填该资产、点"申领"跳到门户审批页并定位该资产的最近申领单。

**AC1**：资产卡片含：类型徽标、名称 + asset_key、§3 评级徽标、上架徽标、最近申领统计（`grantCount`）、最近使用统计（`recentUsedCount`）、"最近申领"明细（最近 1 条）。
**AC2**：评级徽标点击 → 跳 `/trust-ratings?asset=skill:<asset_key>`（技能）或"未评级"禁用（capability_asset 容忍）。
**AC3**：上架/下架徽标点击 → 跳 `/portal/listings?asset=<asset_type>:<asset_key>` 并预填。
**AC4**："最近申领"点击 → 跳 `/portal/approvals` 并定位该 asset_key 的最近一条申领单。
**AC5**：`grantCount` 与 `permission_grants` 同源（`code = "asset:use:<asset_key>"`）。

### User Story 3 - 五块互链：技能页评级徽标定位 / 评级页管理入口 / 门户上架下拉选择（Priority: P2）

作为管理员，我想在技能页点评级徽标直接定位到该技能的评级行（而不是整个列表页），在评级页点资产名带类型徽标并看到上架标志与最近申领，在门户上架页用下拉选资产而不是手填 asset_key。

**AC1**：技能页评级徽标点击 → 跳 `/trust-ratings?asset=skill:<skillId>`，评级页按 `?asset` 定位并打开该行变更弹层。
**AC2**：评级页资产列加类型徽标（skill/agent/workflow）、上架标志列、最近申领统计列；资产名旁加"管理"按钮（打开变更弹层）。
**AC3**：门户上架页类型下拉改 4 项（skill/mcp/tool/connector），资产选择改下拉：选 skill → 调 `GET /api/v1/skills`；选 mcp/tool/connector → 调 `GET /api/v1/capabilities/list?kind=…`；选中后填 `asset_key`。
**AC4**：门户上架页列表加评级列（复用 §4.2 同一口径）。

### User Story 4 - 门户审批流以"资产视角"卡片呈现并可下钻（Priority: P3）

作为管理员，我想在门户审批页看到以"资产为中心"的卡片（同一资产的申请聚合、按状态排序），而不是平铺列表，并能点卡片跳到资产中心对应资产。

**AC1**：`applied` 态按 `asset_key` 聚合，卡片头显示资产名 + 类型徽标 + 申请人列表 + 申请数 + 状态徽标。
**AC2**：卡片操作按钮（批准/拒绝/回收）按 037 既有状态机显示（`applied` 显示批准/拒绝；`granted` 显示回收）。
**AC3**：卡片点击（非按钮区）跳 `/assets?asset=<asset_type>:<asset_key>`。
**AC4**：`all` 态保留平铺列表（聚合仅作用于 `applied` 态）。

### Edge Cases

- **capability_asset 无评级**：评级列显示"未评级"，"管理"按钮禁用（036 `ASSET_TYPES` 不含 `capability_asset`，方案 §10.2 容忍）。
- **capability_asset 未上架**：上架徽标显示"未上架"，点击跳门户上架页预填该 asset_key。
- **某资产 0 申领**：`grantCount = 0`，"最近申领"入口禁用（无明细可看）。
- **技能未发布**：不出现在资产中心（口径：`authoring_mode=platform` 看 `publication_status=published`；`community` 看 `enabled`）。
- **能力资产 state ≠ active**：上架徽标显示"未上架"，但**仍出现在资产中心**（下钻去改）。
- **评审 skill 缺名称**：评级行显示 `asset_key`，不阻塞。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-1**：新增 admin 只读接口 `GET /api/v1/capabilities/list`，返回 `capability_assets` 集合文档（`asset_id` / `name` / `kind` / `state` / `contract` / `version` / `owner_role` / `endpoint` / `method` / `a2a_exposed` / `last_seen_at` / `updated_at`）。支持 `kind` / `state` 过滤。**区别**现有 service-token 端点（不依赖 `backend_service_token`，改用 `get_current_admin_user`）。
- **FR-2**：资产中心页 `/assets` 路由 + 菜单入口。
- **FR-3**：四类资产统一坐标：技能 `asset_key = skills._id`；能力资产 `asset_key = capability_assets.asset_id`，`asset_type` 映射 `skill` / `capability_asset`。
- **FR-4**：类型下拉 4 项（`skill` / `mcp` / `tool` / `connector`），`mcp/tool/connector` 对应 `capability_asset(kind=…)`。
- **FR-5**：资产卡片字段：类型徽标 / 名称 + asset_key / 评级徽标 / 上架徽标 / `grantCount` / `recentUsedCount` / 最近申领明细（最近 1 条）。
- **FR-6**：评级徽标 → `/trust-ratings?asset=skill:<asset_key>`（技能）；capability_asset "未评级"禁用。
- **FR-7**：上架/下架徽标 → `/portal/listings?asset=<asset_type>:<asset_key>` 预填。
- **FR-8**：最近申领 → `/portal/approvals` 定位该 asset_key 最近一条。
- **FR-9**：技能页评级徽标点击 → `/trust-ratings?asset=skill:<skillId>` 定位。
- **FR-10**：评级页资产列加类型徽标 / 上架标志 / 最近申领统计；资产名旁"管理"按钮。
- **FR-11**：门户上架页类型下拉 4 项 + 资产选择改下拉（skill→skills；mcp/tool/connector→capabilities/list?kind=…）。
- **FR-12**：门户审批页 `applied` 态改卡片化（按 asset_key 聚合），`all` 态保留平铺。
- **FR-13**：user-web 门户详情（`PortalDetail`）加"管理状态"锚点（评级徽标 + 上架状态 + 跳转 `/assets?asset=…`）。
- **FR-14**：缺失评级 / 0 申领 / 未上架 / 未发布技能均容忍（§10.2），不阻塞资产中心展示。
- **FR-15**：`grantCount` 与 `permission_grants` 同源（`code = "asset:use:<asset_key>"`）。

### Key Entities

- `capability_assets`：`{asset_id, name, kind, state, contract, version, owner_role, endpoint, method, a2a_exposed, last_seen_at, updated_at}`（018）。
- `skills`：`{_id, name, authoring_mode, publication_status, enabled, owner_user_id, version, updated_at, trigger_config}`（004）。
- `trust_ratings`：`{tenant_id, asset_type, asset_key, level, reason, owner_id, created_at, updated_at}`（036）；`asset_type ∈ {skill, agent, workflow}`。
- `portal_listings`：`{asset_type, asset_key, category, published_by, published_at, unpublished_at}`（037）。
- `portal_requests`：`{request_id, requester_id, asset_type, asset_key, reason, status, approver_id, applied_at, decided_at, decided_reason, granted_at, expires_at, revoked_at, revoke_reason}`（037）。
- `permission_grants`：`{tenant_id, level, org_id, user_id, code, granted_by, granted_at}`，`code = "asset:use:<asset_key>"`（001）。
- `capability_usage_records`：`{asset_id, agent_id, session_id, request_id, first_used_at, last_used_at, use_count}`（018 FR-14）。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- 资产中心页在 1000 资产规模下首屏加载 < 2s（4 个接口并发，后端 `capabilities/list` 索引命中）。
- 五块互链全部可达：技能页评级徽标 → 评级页定位；评级页 → 门户上架/审批；门户上架 → 资产中心；门户审批 → 资产中心；资产中心 → 四块。
- capability_asset 评级缺失时资产中心**不阻塞**（"未评级"占位）。
- 后端新增接口有单测覆盖（admin JWT 鉴权 / 列表返回 / kind·state 过滤）。
- 前端资产中心页 + 互链有 lint / 类型检查通过。

## Assumptions

- 五域仍各持一份资产数据，本期**不合并**；资产中心是 join 视图 + 互链，非单一数据源。
- `capability_assets` 无 `tenant_id` 过滤（共享集合，单租户部署）；方案 §2 已注明此限制，本期接受。
- 评级只覆盖 skill（capability_asset 容忍缺失）；如需 capability_asset 评级，后续扩展 036 `ASSET_TYPES`。
- 本体授权（`ontology_grants`）与能力资产授权是两套模型，本期不 join，仅资产中心保留"数据授权 → 本体授权"只读跳转出口。
- 会话 / 记忆 / 模型不纳入资产中心（运行时态，归外）。

## 跨特性关系（双向声明）

- **018**：提供 `capability_assets` 集合与 `PersistedCapabilityRegistry`；本特性新增 admin 只读列表接口（复用 registry，**不新增写路径**）。
- **036**：评级 join 按 `(asset_type, asset_key)` 坐标；本特性对 capability_asset 评级缺失容忍，**不改 036 `ASSET_TYPES`**。
- **037**：上架 / 审批 join 按同一坐标；本特性只读调用，**不改 037 状态机 / RBAC**。
- **001**：`grantCount` 复用 `permission_grants`（`code = "asset:use:<asset_key>"`），**不新建审批表**。

## Non-Go（明确不做）

- 不合并五页为一个大页面。
- 不动 RBAC / 037 后端状态机 / 036 评级模型。
- 本期不纳入模型 / 会话 / 记忆。
- 不把本体授权 join 进资产卡片。
- 不新增 capability_asset 评级写路径（仅只读列表）。

## 验收状态

（实施阶段回填）
