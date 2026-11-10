# Tasks: 菜单管理（055-menu-management）

**Input**: Design documents from `/specs/055-menu-management/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: 设计方案于 2026-11-10 经用户确认后同轮实现；T001 起连续编号。

**Tests**: `pytest services/admin-api/tests/test_menu_settings.py`；前端 `vue-tsc --noEmit` + `vite build` + 路由快照 + 构建产物渲染。

**Organization**: Phase 0 调研 → Phase 1 规格 → Phase 2 后端 → Phase 3 前端 → Phase 4 验证收尾。

---

## Phase 0: 研究与澄清

- [x] T001 核实 `useMenuOptions.ts` 菜单推导、`router/index.ts` 守卫、`menuGroup: 'organizations'` 扩展点
- [x] T002 核实 `app/shortcut_settings/` 范式（models / service / router 注册）与 `get_current_admin_user` 租户闸门
- [x] T003 统计 `routes.ts` 规模（66 条 path / 36 条 hideInMenu 或 redirect），确认只读区范围
- [x] T004 确认 Naive UI 已全局注册所需组件、i18n `t()` 回退行为、Pinia store 挂载点

## Phase 1: 规格

- [x] T005 建立 spec / plan / tasks / checklist 四件套（本目录）
- [x] T006 固化 12 条已定决策，记录「白名单执行点前移到合并层」的实现细化与理由
- [x] T007 定义 API 契约、字段语义、locked 清单、安全边界与验收标准

## Phase 2: 后端 admin-api

- [x] T008 [P] `app/menu_settings/catalog.py`：分组 key 白名单、图标枚举、locked 集合
- [x] T009 [P] `app/menu_settings/models.py`：key 格式/唯一性、parentKey、label、iconKey、locked 强制可见
- [x] T010 `app/menu_settings/service.py`：`get_plan` / `save_plan` / `delete_plan`，按 `tenant_id + scheme_key` upsert，GET 不写库
- [x] T011 `app/api/routes/menu_settings.py`：GET / PUT / DELETE，tenant_id 仅取自 `current_user`
- [x] T012 `app/api/router.py` 定点追加 import 与 `include_router(prefix="/settings/menus")`（不覆盖其它会话改动）
- [x] T013 [P] `tests/test_menu_settings.py`：模型校验、默认方案、服务读写、端点契约、locked 强制、租户隔离

## Phase 3: 前端 admin-web

- [x] T014 `src/composables/menuCatalog.ts`：从 `appRoutes` 派生 groups / nodes / readonly，导出 `ICON_REGISTRY` 与 `resolveIcon`
- [x] T015 [P] `src/api/menu-settings.ts`：类型 + fetch / save / reset
- [x] T016 [P] `src/stores/menuConfig.ts`：幂等加载、租户变化失效、合并覆盖、丢弃未知 key、失败静默回退、save / reset
- [x] T017 改造 `src/composables/useMenuOptions.ts`：基于合并树渲染，保留 `joinPath` / `expandedGroupsForPath` / `selectedKey` / platformOnly 过滤
- [x] T018 `src/views/settings/MenuManagePage.vue`：分组树、显隐、上移下移、中英改名、图标、搜索、仅看已修改、只读区、diff、保存/恢复默认/离开拦截
- [x] T019 `src/router/routes.ts` 定点追加 `/settings/menus`（`menuGroup: 'organizations'`）
- [x] T020 [P] `src/locales/messages.ts` 补「菜单管理」等词条与页面文案

## Phase 4: 验证与收尾

- [x] T021 后端单测 + 模块导入 / 路由注册检查
- [x] T022 前端 `vue-tsc --noEmit` + `vite build`
- [x] T023 路由快照断言（既有 URL / redirect / 分组归属不变）
- [x] T024 构建产物浏览器渲染：默认菜单一致、配置失败静默回退、菜单管理页在「权限中心」下
- [x] T025 清理临时脚本、更新工作区日志、回填 tasks 勾选
