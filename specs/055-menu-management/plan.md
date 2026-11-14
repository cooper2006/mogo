# Implementation Plan: 菜单管理（055-menu-management）

**Branch**: `055-menu-management` | **Date**: 2026-11-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/055-menu-management/spec.md`（2026-11-10 用户确认的设计方案）

## Summary

- **后端（admin-api）**：新模块 `app/menu_settings/`（catalog 常量 / Pydantic 模型 / service），三个端点 `GET|PUT|DELETE /api/v1/settings/menus`，仿 `app/shortcut_settings/` 范式，集合 `organization_menu_schemes`。
- **前端（admin-web）**：新增 `composables/menuCatalog.ts`（静态树派生）、`api/menu-settings.ts`、`stores/menuConfig.ts`；改造 `useMenuOptions.ts` 基于合并后的树渲染；新增 `views/settings/MenuManagePage.vue` 挂到 `menuGroup: 'organizations'`。
- **不改**：`router/index.ts` 守卫、`routes.ts` 既有组件映射与 URL、BasicLayout 菜单渲染组件、后端鉴权模型。

## Technical Context

**Language/Version**: Python 3.13（admin-api）；Vue 3 + TypeScript + Naive UI（admin-web）

**Primary Dependencies**: `appRoutes`（唯一真源）、`useMenuOptions`、`useAuthStore`、`t()` i18n、`app.shortcut_settings` 范式；**不引入新第三方依赖**

**Storage**: 新增 `organization_menu_schemes` 集合（按 `tenant_id + scheme_key` 唯一）

**Testing**: `services/admin-api/tests/test_menu_settings.py`（模型校验 + service + 端点）；前端 `vue-tsc --noEmit` + `vite build` + 路由快照 + 构建产物浏览器渲染

**Target Platform**: Docker Compose（admin-api + admin-web）

## Architecture

```
routes.ts (静态，唯一真源)
   │
   ├─> menuCatalog.ts  buildCatalog()
   │      ├─ groups[]  /resources /assets /audit /organizations-group …
   │      ├─ nodes[]   可见菜单项（key = route.path, parentKey, title, icon, locked）
   │      └─ readonly[] hideInMenu + redirect（只在管理页展示）
   │
   ├─> menuConfig.ts (Pinia)  ── GET /api/v1/settings/menus ──> admin-api / Mongo
   │      overrides: Map<key, MenuNode>
   │      失败/为空 → 空 Map（默认菜单）
   │
   └─> useMenuOptions.ts  merged = catalog + overrides
          ├─ 过滤 visible=false（locked 忽略）
          ├─ label = override.label[locale] ?? t(title)
          ├─ icon  = ICON_REGISTRY[override.iconKey] ?? staticIcon
          └─ order = override.order ?? 静态顺序
```

**关键取舍**：菜单配置是「展示层覆盖」，不是路由定义。任何配置错误最坏只影响某个菜单项的显示，不会让路由 404，也不会扩大可访问面。

## 文件改动清单

| 层 | 文件 | 动作 |
| --- | --- | --- |
| 规格 | `specs/055-menu-management/{spec,plan,tasks}.md`, `checklists/requirements.md` | 新增 |
| 后端 | `app/menu_settings/{__init__,catalog,models,service}.py` | 新增 |
| 后端 | `app/api/routes/menu_settings.py` | 新增 |
| 后端 | `app/api/router.py` | 定点追加 import + include_router |
| 后端 | `tests/test_menu_settings.py` | 新增 |
| 前端 | `src/composables/menuCatalog.ts`, `src/api/menu-settings.ts`, `src/stores/menuConfig.ts` | 新增 |
| 前端 | `src/composables/useMenuOptions.ts` | 改造为合并树渲染 |
| 前端 | `src/views/settings/MenuManagePage.vue` | 新增 |
| 前端 | `src/router/routes.ts` | 定点追加 `/settings/menus` |
| 前端 | `src/locales/messages.ts` | 补词条 |

## Constitution Check

| 门禁 | 结论 |
| --- | --- |
| 凭证零明文 | 配置只含菜单元数据，无凭证字段 |
| 租户隔离 | `tenant_id` 从认证主体取，GET/PUT/DELETE 全部按 `tenant_id + scheme_key` 过滤 |
| GET 无副作用 | GET 只 `find_one`，无记录返回内存默认值，不写库 |
| 平台租户反向闸门 | 复用 `get_current_admin_user` |
| 不引入新依赖 | 仅用已有 pydantic / motor 门面 / Pinia / Naive UI |
| 安全默认值 | 配置失败回退默认菜单；locked 强制可见；未知 key 丢弃 |
| 权限不被绕过 | 显隐不影响路由与后端鉴权，UI 常驻提示 |

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 覆盖层与静态路由漂移（新增/删除路由） | 合并层以静态树为准，未知 key 丢弃并告警；不存完整树 |
| 配置加载慢导致侧边栏闪烁 | 首次渲染即返回默认菜单，配置到达后原地合并；不阻塞布局 |
| 误把隐藏当权限 | spec / UI 双重明示；`locked` 防止把管理页自己藏掉 |
| 切租户后沿用上个租户配置 | store 记录 `tenantKey`，变化时清空并重载 |
| 多会话并发保存覆盖 | 单方案 + 显式保存（无自动保存），diff 预览降低误操作；P1 再做乐观锁 |
