# 资产中心串联方案（A+B）

> 状态：实施中（基础链路 + 资产中心互链已落，§5 方案 B 剩余项待后续批次）。
> 关联 spec：018 capability-asset-registration / 036 trust-rating / 037 unified-portal。

## 0. 一句话

把"技能 / 资产评级 / 门户上架 / 门户审批 / 资产使用"五个割裂的功能点，用**一个"资产中心"枢纽页 + 四类资产统一坐标**串成一条生命周期；数据靠前端 join，后端只补一个能力资产只读列表接口。

## 1. 为什么"没联系"（根因诊断）

五个域**各持一份资产数据**，只在 `(asset_type, asset_key)` 这个"暗坐标"上偶然对齐，互不引用：

| 功能域 | 位置 | 数据源 | 现状痛点 |
|---|---|---|---|
| 技能 | admin `SkillsPage` | `skills` 集合 | 卡片已显示评级徽标，但点击只跳"整个评级列表页"，没有"看该技能本身评级/上架"入口 |
| 资产评级 | admin `TrustRatingPage` | `trust_ratings` | 资产是 `asset_key` 文本，看不出它是什么、能否上架、有没有人在用 |
| 门户上架 | admin `PortalListingPage` | `portal_listings` | **手填 asset_key 上架**，不从技能/能力列表选，不显示评级 |
| 门户审批 | admin `PortalApprovalPage` | `portal_requests` | 只见 `requester_id`，不知资产是谁的、什么等级 |
| 资产使用 | user `PortalCatalog/Detail` | 同上（chat-api 侧） | 是整条链终端，与 admin 侧三块完全割裂 |

**暗坐标 bug**：`capability_assets` 集合被两套 key 写——admin 侧 `registry.py` 用 `asset_id`，chat-api 侧（012 AgentCard）用 `key` 别名读；门户上架读 `asset_id`、技能读 `skills._id`。两条不同的"暗坐标"，**没有任何 UI 帮你对齐**。门户上架页手填 key 填错就 404/409，没有下拉可选。

## 2. 哪些算"资产"（边界，已与用户确认）

**原则：资产 = 可被 Agent 发现、可版本化、可授权、可评级的"能力单元"；运行时态（会话/记忆）不是资产。**

| 类型 | 算资产吗 | 现状 | 资产中心纳入 |
|---|---|---|---|
| 技能 | ✅ | 核心链路 | `skills`（一等公民） |
| MCP | ✅ | 018 扫描目标 | `capability_asset(kind=mcp)` |
| 工具 | ✅ | 018 FR-4 与 Skill 多对多 | `capability_asset(kind=tool)` |
| 连接器 | ✅ | `connector_market` 安装即登记 | `capability_asset(kind=connector)` |
| 模型 | ⚠️ 可选 | `models` 独立集合，未走 018 | **暂不纳入**（二期，作为 `capability_asset(kind=model)`） |
| 本体 | ❌ 不纳入 | `ontology_grants`（`read/write/none`+优先级，`OntologyPermissionService`） | **数据授权域**，非能力资产 |
| 会话 | ❌ | `sessions` 运行时态 | 域外 |
| 记忆 | ❌ | 存储/运行时态 | 域外 |

**本体特别说明**：`ontologies.py` 注释明确"本体清单只做展示，不提供本体 CRUD（本体定义与数据都在业务系统）"。本体的授权走 `ontology_grants`（`read/write/none` + 优先级合并），与资产的 `permission_grants.asset:use:<key>` 是**两套不同的授权模型**——前者是"数据可见性控制"，后者是"能力可用性授权"。故本体划到**数据授权域**，不进资产中心 join；资产中心只给一个"数据授权 → 本体授权"只读跳转出口，避免它成孤岛但保持两条授权线解耦。

> **本期资产中心只收核心 4 类（技能 / MCP / 工具 / 连接器）**。本体归数据授权域、会话/记忆是运行时态，三者均划到域外，写进方案避免资产中心变杂烩。

## 3. 数据流（生命周期 + 暗坐标修复点）

一个资产从"存在"到"被用"，分**三条线**并行（业务流 / 数据流 / 审批流），在同一个 `(asset_type, asset_key)` 坐标上对齐：

```
① 资产存在              ② 资产评级            ③ 门户上架            ④ 门户审批            ⑤ 资产使用
─────────────         ─────────────        ───────────────       ───────────────       ─────────────
skills 集合           trust_ratings       portal_listings        portal_requests          user-web 门户
capability_assets     (L1–L4 质量)        (暴露登记)              (申领/授权)              PortalCatalog
(4 类能力)    ────►    关联①的坐标   ───►  关联①②坐标     ───►    批准→写授权      ───►   PortalDetail
                                                            permission_grants
                                                            asset:use:<key>
```

- **业务流**（人做的动作）：登记/安装资产 → 评质量 → 上架暴露 → 员工申领 → 管理员审批 → 员工使用。
- **数据流**（集合怎么写读）：`skills` / `capability_assets` → `trust_ratings` → `portal_listings` → `portal_requests` → `permission_grants`，五份数据各持一份资产、各页各渲染，**互不引用**——这是割裂的根因。
- **审批流**（权限收敛闭环，见 §3.1）：`portal_requests` 状态机 `applied→approved→granted→revoked/expired`，批准即写用户级 `asset:use:<key>`，回收即删、fail-closed。

**修复点**：新增"资产中心"页做统一 join，把三条线在**同一个坐标**上对齐；能力资产从"手填 key"改为"从已登记的 4 类资产下拉直选"，消除暗坐标。

### 3.1 审批流（037 状态机，方案需对齐的权限语义）

审批是"开通→使用"闭环的权限收敛层，不是孤立功能。资产中心要把它**纳入统一视图**，但不改它自身实现：

| 审批流要素 | 现状（037，已落地） | 资产中心怎么呈现 |
|---|---|---|
| 申领单状态机 | `applied→approved→granted→revoked/expired`（`portal_requests`，持久状态机） | 资产卡片显示 `grantCount`（granted 数）+ 最近申领单状态；点跳 `PortalApprovalPage` 对应单 |
| 审批人解析 | `resolve_approver`：owner 优先 → 回落持 `portal:approve` 的管理员；**防自审**（requester≠approver）；解析不到 fail-closed 拒单 | 卡片展示"可审批人"（owner + 回落管理员数） |
| 开通授权 | `grant_asset_use`：写 `permission_grants`（`level=user`，`code=asset:use:<key>`，幂等 upsert） | 卡片"授权概况"= granted 计数，与 `permission_grants` 同源 |
| 回收 | `revoke_grant`：删授权 + 申领单转 revoked，下次调用 fail-closed | 审批页可回收；资产中心显示"最近回收时间" |
| 惰性过期 | `expire_stale_grants`：读路径惰性把到期 granted 转 expired 并删授权（无后台调度） | 卡片显示授权 `expires_at`（若 TTL>0） |

**资产中心不新建审批机制**，只把上述状态汇总进卡片 + 提供跳转；审批动作仍走 `PortalApprovalPage`（管理）/ `PortalDetail`（员工自助）。

## 4. 方案 A：资产中心枢纽页

**新增** admin-web `/assets` 页（`views/assets/AssetCenterPage.vue` + `composables/useAssetCenter.ts`）。
按 `asset_type` 聚合，每个资产一张卡片，**同屏显示全生命周期状态**：

| 卡片列 | 数据来源（前端 join，已有接口 + 1 个新接口） |
|---|---|
| 资产名 / 类型 / key | `fetchSkills()`（技能）+ **新** `GET /api/v1/capabilities/list`（MCP/工具/连接器） |
| 启用 / 可上架 | 技能 `lifecycle/publication_status` + 能力 `state` |
| 评级 L1–L4 | `fetchTrustRatings()`，徽标点开跳 `TrustRatingPage` 对应行 |
| 上架状态 | `fetchPortalListings({publishedOnly:false})`，一键上架 / 跳 `PortalListingPage` |
| 授权概况 | `fetchPortalApprovals({status:'all'})`，granted 计数，跳 `PortalApprovalPage` |

- 类型下拉 4 项：`skill / mcp / tool / connector`。
- 卡片"全生命周期"视图：未上架可发起上架、无评级可发起评级、可跳技能配置 / 资产中心详情。
- 页面顶部放"生命周期图"（本方案 §3 那张图），让用户看懂"这是同一条链"。

**后端仅补 1 个接口**（不建统一资产目录服务，控制改动面）：
`GET /api/v1/capabilities/list`（admin JWT，只读，区别现有 service-token 端点），按租户读 `capability_assets` 4 类。

## 5. 方案 B：五块互链（消除孤岛）

| 页面 | 改动 |
|---|---|
| `PortalListingPage` | 手填 `asset_key` → 改成**从 4 类已登记资产下拉选**（调 §4 同一 join 数据源）；选中即带出评级 + 启用状态，**不可用则禁上架**（对齐后端 409） |
| `TrustRatingPage` | 加"上架"列（该资产是否已发布到门户）+ "管理"按钮：跳技能配置页（`/skills/:id/config`）或资产中心 |
| `SkillsPage` | 卡片加"上架状态"小标；评级徽标保留（已点跳 `TrustRatings`，可细化为跳对应资产行） |
| `PortalApprovalPage` | 审批详情显示该资产的**评级 + owner**（数据 §4 已 join，直接传） |
| user `PortalDetail` | 已能拿到 `rating.level / effect / owner`；补一个"在资产门户查看管理状态"只读锚点 |

**原则**：只加链接与下拉，**不动 RBAC、不动 037/038 后端状态机**（门户/出站是刻意设计过的）。

## 6. 数据一致性 & 暗坐标修复

- `capability_assets` 双 key（`asset_id` / `key`）已在 `registry.py:_asset_to_row` 双写对齐（`asset_id` + `key` 别名）。资产中心与上架下拉**统一读 `asset_id`**，与 `portal_admin._asset_row` 一致，不再引入第三条 key。
- 上架"是否可上架"判定复用 `portal_admin._is_active_asset` 口径（技能看 `authoring_mode/publication_status`，能力看 `state`），前端下拉禁用态与后端 409 对齐。

## 7. 落地拆解（建议批次）

- **批次 1（最小闭环，纯前端 + 1 接口）**：资产中心页 `/assets`（4 类 join）+ `GET /api/v1/capabilities/list`。→ 单页先验证"同坐标对齐"可行。
- **批次 2（互链 + 审批流呈现）**：§5 五块互链（上架下拉、评级管理列、技能小标、审批详情、user 锚点）+ 资产中心卡片汇总审批流状态（§3.1：grantCount/最近单/可审批人/到期时间），审批动作仍跳 `PortalApprovalPage`。
- **批次 3（可选数据底座）**：模型作为 `capability_asset(kind=model)` 纳入 + 会话/记忆明确域外注释。

## 8. 验收点

1. 资产中心页能列出技能 + MCP/工具/连接器四类资产，每个卡片同屏显示评级 / 上架 / 授权三态。
2. 门户上架页可下拉选资产（非手填 key），选中后显示评级 + 启用状态，停用资产禁用上架。
3. 评级页"管理"按钮能跳到对应技能的配置页或资产中心对应卡片。
4. 审批详情显示资产评级 + owner。
5. 全链路无 404/409（key 对齐）；前端 join 不重复拉同一份数据超过一次。
6. **审批流呈现**：资产卡片 grantCount 与 `permission_grants` 同源；最近申领单可跳 `PortalApprovalPage`；防自审/惰性过期语义不变（037 既有）。

## 9. 明确不做（边界）

- 不合并五个页面为一个大页面（保留各自职责，只加枢纽 + 互链）。
- 不动 RBAC / 037 / 038 后端状态机。
- 本期不纳入模型 / 会话 / 记忆（会话记忆是运行时态，归外）。
- **不纳入本体**：本体属数据授权域（`ontology_grants`，`read/write/none`+优先级），与能力资产的 `permission_grants.asset:use:<key>` 是两套授权模型。资产中心只加"数据授权 → 本体授权"只读跳转出口，不 join 进资产卡片，保持两条授权线解耦。

## 10. 实施进度

### 已完成（2026-10-29）
- [x] 登录页跳转：`AuthLoginPage` 登录后回跳来源页（replace 去历史残留）
- [x] `/api/portal` 走 admin-web base URL：去尾斜杠防重定向丢 JWT
- [x] SDK 统一响应格式：`portal.ts` 直接返回后端 JSON，类型对齐
- [x] 资产中心互链：`AssetsPage` → `/trust-ratings`、`/portal/listings`、`/portal/approvals` 带 `asset_type`/`asset_key` query；`PortalListingPage`、`PortalApprovalPage` 读 query 客户端过滤聚焦；`TrustRatingPage` 已有互链逻辑（useRoute + filteredRows + watch）

### 待落地（§5 方案 B 剩余项）
- [ ] `PortalListingPage`：手填 `asset_key` → 4 类已登记资产下拉选，不可用禁上架
- [ ] `TrustRatingPage`：加"上架"列 + "管理"按钮（跳技能配置 / 资产中心）
- [ ] `SkillsPage`：卡片加"上架状态"小标
- [ ] `PortalApprovalPage`：审批详情显示该资产评级 + owner
- [ ] user `PortalDetail`：补"在资产门户查看管理状态"只读锚点
- [ ] `PortalUsagePage` / `PortalPortalPage`：当前代码库不存在，需确认是否在后续批次创建

### 验收（§8）
- [x] 资产中心页能列出技能 + MCP/工具/连接器四类资产
- [ ] 门户上架页可下拉选资产（当前仍手填 asset_key）
- [ ] 评级页"管理"按钮能跳（当前无此列）
- [ ] 审批详情显示资产评级 + owner（待验证）
- [ ] 全链路无 404/409（待端到端验证）
- [ ] 审批流呈现：grantCount / 最近单 / 到期时间（待验证）
