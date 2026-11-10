# Feature Specification: 菜单管理（admin-web 路由/菜单配置化）

**Feature Branch**: `055-menu-management`

**Created**: 2026-11-10

**Status**: Implemented

**Input**: 用户需求「在 admin-web 下设计一个菜单管理功能，放置在组织与用户菜单下，将 admin-web 下的所有路由管理功能放在菜单管理功能中」+ 2026-11-10 已确认的设计方案（路由静态、菜单配置化、只存覆盖层）。

> **性质说明**：本规约与实现同轮落地（2026-11-10）。设计方案先经用户确认，本文件是该方案的规约化记录，不是新设计。
>
> **背景事实（代码级核实，2026-11-10）**：`apps/admin-web/src/composables/useMenuOptions.ts` 从 `appRoutes` 自动推导侧边栏（有 children → 一级分组，`menuGroup: 'organizations'` → 硬编码分组，`selectedKey = route.path`）；`router/index.ts` 的守卫只做登录态 / `platformOnly` 判定；后端没有任何菜单配置端点，但 `app/shortcut_settings/` 提供了「按 `tenant_id` 存单份默认方案 + Pydantic 白名单 + locked 强制可见」的现成范式。`routes.ts` 共 66 条 `path:`，其中 36 条带 `hideInMenu` / 为 redirect。

## 定位（一句话）

把 admin-web 侧边栏所有菜单项的**展示元数据**（名称 / 显隐 / 顺序 / 图标）集中到「组织与用户 → 菜单管理」页配置；**路由表仍是唯一真源**，后端只保存相对默认菜单的**差异覆盖层**，新增路由自动出现在菜单里，无需同步配置。

## 已定决策（2026-11-10 设计方案，用户确认后落地）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | 配置化边界 | **只配置展示元数据**；不改 `component`、不新增/删除路由、不改访问守卫 | `menuCatalog.ts` / `useMenuOptions.ts` |
| 2 | 存储形态 | 后端只存**覆盖层**（`nodes[]`），不存完整菜单树；无记录 = 空覆盖 = 默认菜单 | `organization_menu_schemes` |
| 3 | 节点坐标 | `key` 一律用 `route.path`（含 `/hooks/rules`、`/token-stats` 这类绝对路径子项），与 `selectedKey` 对齐 | 全链路 |
| 4 | 范围 | 菜单树内可见节点可编辑；36 条 `hideInMenu` / redirect 路由**只读展示**，不能编入菜单树 | 菜单管理页 |
| 5 | 方案粒度 | 租户级**单一默认方案**（`scheme_key = 'default'`），不做多方案 / 按角色授权 | service |
| 6 | 改名 | 存多语言 `label: {zh-CN, en-US}`，**不改** `messages.ts` 静态词条；缺失回退 `t(title)` | 合并层 |
| 7 | 图标 | 只允许预设 `iconKey` 枚举，禁止注入任意 SVG / 组件 | `catalog.py` / `ICON_REGISTRY` |
| 8 | 白名单执行点 | **前端合并层用静态 catalog 做精确白名单**（丢弃未知 key 并告警）；后端内置稳定的**分组 key 白名单** + key 格式校验，不复制全量路由清单以免漂移 | 见「实现细化」 |
| 9 | 权限 | `get_current_admin_user`（平台租户被拒）；菜单配置**不是权限**，隐藏项直接输 URL 仍可访问 | 路由 / 说明 |
| 10 | 防锁死 | `/dashboard`、`/settings/menus`、`/platform/tenants` 及全部只读路由为 `locked`，忽略 `visible=false` | catalog / models |
| 11 | 失败降级 | 配置为空 / 接口失败 → 全量回退默认菜单，页面不报错 | `menuConfig.ts` |
| 12 | 入口 | `/settings/menus`，`meta.menuGroup: 'organizations'` → 自动落入「组织与用户」分组 | `routes.ts` |

### 实现细化（相对设计方案的一处技术调整）

设计方案写「服务端强制：`key` 必须在前端清单白名单内」。实现时把**精确白名单放在前端合并层**：菜单树由静态 `appRoutes` 派生，配置中的未知 key 根本不会被渲染，因此这是更强且不会漂移的边界；后端若再复制一份全量 key 清单，会在每次新增路由时产生同步负担。后端保留的是**分组白名单**（数量少且稳定）+ key 格式/结构校验，仍能拒绝注入任意 path、跨分组挂接与环。安全目标不变，漂移风险更低。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 查看并调整菜单 (Priority: P1) 🎯 MVP

管理员进入「组织与用户 → 菜单管理」，看到按现有分组排列的全部可管理节点及其路径、类型、来源；可隐藏某项、调整同组内顺序、改中英文名称、换图标，保存后侧边栏即时生效。

**Why this priority**: 这是「所有路由管理功能集中到一处」的最小闭环。

**Independent Test**: 隐藏「Token 统计」→ 保存 → 侧边栏「系统审计」下不再出现它，但地址栏输入 `/token-stats` 仍能打开页面；恢复默认 → 全部还原。

**Acceptance Scenarios**:

1. **Given** 无任何配置记录，**When** 打开菜单管理，**Then** 展示与当前侧边栏一致的默认菜单树，全部节点标记为「默认」。
2. **Given** 管理员隐藏某非 locked 节点并保存，**When** 刷新页面 / 切换语言 / 重新登录，**Then** 该节点持续隐藏，其余节点不变。
3. **Given** 管理员把某节点上移两位，**When** 保存，**Then** 侧边栏与菜单管理页的组内顺序一致。
4. **Given** 管理员改中英文名称，**When** 切换界面语言，**Then** 显示对应语言；清空自定义名称后回退静态词条。

### User Story 2 - 只读路由与变更预览 (Priority: P1)

隐藏路由 / 旧路径 redirect 以只读区展示，可查看跳转目标但无法编入菜单树；保存前可查看本次变更 diff。

**Why this priority**: 「所有路由管理」要求覆盖清单，但允许编辑隐藏路由会诱导出指向不存在组件的菜单项。

**Acceptance Scenarios**:

1. **Given** 只读区，**When** 查看，**Then** 显示 36 条隐藏/重定向路由的 `path`、标题、类型与目标，且无显隐/排序/改名控件。
2. **Given** 有未保存改动，**When** 点「变更预览」，**Then** 逐条列出 `key` / 字段 / 原值 / 新值；未改动项不出现。
3. **Given** 有未保存改动，**When** 离开页面，**Then** 弹出确认，取消则留在原页。

### User Story 3 - 降级与防锁死 (Priority: P1)

配置接口失败、返回未知 key、或配置试图隐藏 locked 节点时，系统保持可用。

**Acceptance Scenarios**:

1. **Given** GET 返回 500 / 超时，**When** 加载侧边栏，**Then** 静默回退默认菜单，无错误弹窗、无空白侧边栏。
2. **Given** 配置含静态树中不存在的 `key` 或非法 `parentKey`，**When** 合并 / PUT，**Then** 前端丢弃并 `console.warn`、后端 422 拒绝。
3. **Given** 配置把 `/settings/menus` 设为 `visible=false`，**When** 保存并读取，**Then** 该节点仍可见（locked 强制）。

## Functional Requirements

- **FR-1**：MUST 提供 `GET /api/v1/settings/menus`，无记录时返回空 `nodes` 的默认方案，不创建任何文档（GET 无副作用，025）。
- **FR-2**：MUST 提供 `PUT /api/v1/settings/menus` 校验并 upsert 覆盖层；`tenant_id` 只从 `current_user` 取，不接受请求体传入。
- **FR-3**：MUST 提供 `DELETE /api/v1/settings/menus` 恢复默认（删除本租户默认方案），幂等。
- **FR-4**：MUST 使用 `get_current_admin_user` 依赖，平台租户标识被拒。
- **FR-5**：MUST 校验 `key` 唯一、格式（`/` 开头、允许 `[A-Za-z0-9_/:.-]`、禁 `//` / `..` / 控制字符）、长度 ≤ 160；`nodes` 上限 200。
- **FR-6**：MUST 校验 `parentKey`：分组节点为 `null`；非分组节点必须落在已知分组 key 白名单内。禁止跨分组挂接与自环。
- **FR-7**：MUST 校验 `iconKey` 属于预设枚举；`label` 仅允许 `zh-CN` / `en-US` 两个键，单值 ≤ 80 字符。
- **FR-8**：MUST 对 `locked` 节点忽略 `visible=false`（服务端与前端合并层双重生效）。
- **FR-9**：MUST 在前端由静态 `appRoutes` 派生 catalog（分组 / 可见项 / 只读项），作为菜单渲染与菜单管理页的唯一真源。
- **FR-10**：MUST 合并时丢弃未知 key 与非法结构并告警；配置为空 / 请求失败 MUST 回退默认菜单。
- **FR-11**：MUST 保留既有 URL、书签、工作台快捷入口、`hideInMenu` 旧路径 redirect 与 `platformOnly` 过滤行为。
- **FR-12**：MUST 将 `/settings/menus` 挂在 `menuGroup: 'organizations'`，使「菜单管理」出现在「组织与用户」下；平台管理员侧不显示该入口。
- **FR-13**：MUST 在菜单管理页提供搜索、「仅看已修改」、组内上移/下移、显隐、中英改名、图标选择、变更 diff、保存、恢复默认、离开拦截。
- **FR-14**：MUST NOT 把菜单显隐当作权限控制；MUST NOT 允许配置注入任意 path / component / SVG。

## 数据模型与 API 契约

### `organization_menu_schemes`（Mongo 集合，027 门面双后端兼容）

```json
{
  "tenant_id": "t-001",
  "scheme_key": "default",
  "nodes": [
    {
      "key": "/token-stats",
      "parentKey": "/audit",
      "label": { "zh-CN": "用量统计", "en-US": "Usage" },
      "iconKey": "token",
      "visible": false,
      "order": 9,
      "locked": false
    }
  ],
  "updated_at": "2026-11-10T03:20:00+00:00",
  "updated_by": "<admin_id>"
}
```

### 响应（`GET` / `PUT` 同形）

```json
{
  "id": "default",
  "schemeKey": "default",
  "version": 1,
  "nodes": [],
  "updatedAt": "",
  "updatedBy": ""
}
```

`DELETE` 返回 `{ "ok": true, "schemeKey": "default" }`。

### 字段语义

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `key` | string | `route.path`，唯一，合并主键 |
| `parentKey` | string \| null | 所属分组；一级项为 `null` |
| `label` | object \| null | 多语言覆盖；`null` / 缺语言 → 回退 `t(title)` |
| `iconKey` | string \| null | 预设图标枚举；`null` → 回退静态图标 |
| `visible` | bool \| null | `false` 隐藏；`null` 视为默认可见 |
| `order` | int \| null | 同组内升序；`null` 保持静态顺序 |
| `locked` | bool | 只读标记，服务端据 catalog 强制 |

## 安全边界（MUST 在 UI 明示）

**菜单配置只控制展示，不是权限。** 隐藏某项后，直接输入 URL 仍可访问；访问控制由后端 API 与 `meta.platformOnly` / 角色负责。菜单管理页必须常驻一条提示，避免「菜单藏了但接口还开着」的错觉。

## 分期

- **P0（本轮）**：只读清单 + 显隐 / 排序 / 中英改名 / 图标 + 保存 / 恢复默认 / diff / 离开拦截 / 回退默认；单租户默认方案。
- **P1**：拖拽跨分组、变更审计、保存前侧边栏实时预览、方案导入导出。
- **P2**：按岗位/角色授权菜单（**须同步后端鉴权**）、多方案、与「快捷入口」体系打通。

## 验收标准

1. `vue-tsc --noEmit` 与 `vite build` 通过；后端 `pytest tests/test_menu_settings.py` 通过。
2. 配置为空 / GET 500 时，菜单与改动前**逐项一致**；不出现空白侧边栏或错误弹窗。
3. 隐藏「Token 统计」后菜单消失，`/token-stats` 仍可直接打开。
4. 现有路由快照（含 `/resources` redirect、`/hooks/rules`、`/token-stats`、详情页）全部解析不变；工作台快捷入口与旧路径 redirect 有效。
5. locked 节点不可隐藏；未知 key / 非法 `parentKey` / 非法 `iconKey` 被拒（前端丢弃 + 后端 422）。
6. 「菜单管理」出现在「组织与用户」分组下；平台管理员不可见。
7. 刷新 / 切租户 / 切换中英文界面后配置持续生效。
