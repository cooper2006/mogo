# Quickstart: 055 菜单管理

**状态**：已实现（25/25 tasks 全勾，代码同轮落地）。

## 做了什么

admin-web 的路由保持静态，菜单**配置化**：按租户存一份「默认方案覆盖层」，控制分组与菜单项的可见性 / 标签 / 图标；入口挂在「权限中心」下。

- admin-api：`app/menu_settings/`（catalog / models / service），`GET | PUT | DELETE /api/v1/settings/menus`；`tenant_id` 只从 `current_user` 取，不接受请求体传入；GET 无记录时返回空 `nodes` 的默认方案且不写库（025 口径）。
- admin-web：`src/stores/menuConfig.ts`、`src/api/menuConfig.ts`、`src/views/settings/MenuManagePage.vue`、`src/composables/useMenuOptions.ts`。
- 集合 `organization_menu_schemes`（租户级覆盖层，已在 `tenant_purge` 清单内）。

## 前置条件

1. kiri 生产栈在线；admin 会话具备租户管理员身份（平台租户标识被 `get_current_admin_user` 拒绝）。
2. 前端已构建：`apps/admin-web` 的 `vue-tsc --noEmit` 与 `vite build` 通过。

## 如何启用

```bash
# 读取当前租户方案（无记录返回默认，不写库）
curl -s -H "Authorization: Bearer <admin token>" \
  http://localhost:3000/admin-api/api/v1/settings/menus

# 保存覆盖层
curl -s -X PUT -H "Authorization: Bearer <admin token>" -H 'Content-Type: application/json' \
  -d '{"nodes":[{"key":"/settings/menus","label":{"zh-CN":"菜单管理","en-US":"Menu"},"iconKey":"setting","parentKey":"permission","visible":true,"locked":true}]}' \
  http://localhost:3000/admin-api/api/v1/settings/menus

# 恢复默认（幂等）
curl -s -X DELETE -H "Authorization: Bearer <admin token>" \
  http://localhost:3000/admin-api/api/v1/settings/menus
```

浏览器：admin-web → 权限中心 → 菜单管理 → 调整可见性 / 标签 → 保存 → 刷新侧边栏生效。

## 如何验证

```bash
cd /Users/cooper/mogo
services/admin-api/.venv/bin/python -m pytest services/admin-api/tests/test_menu_settings.py -q -o addopts=
cd apps/admin-web && npx vue-tsc --noEmit && npx vite build
```

## 注意事项

- 校验：key 唯一、`/` 开头、允许 `[A-Za-z0-9_/:.-]`、禁 `//` / `..` / 控制字符、长度 ≤ 160；`nodes` 上限 200；`parentKey` 分组节点为 `null`、非分组必须落在已知分组白名单；`iconKey` 属预设枚举；`label` 仅 `zh-CN` / `en-US` 两键且单值 ≤ 80。
- `locked` 节点忽略 `visible=false`（服务端 + 前端合并层双重生效），防止把入口藏死后无法恢复。
- 只存覆盖层，不改动路由表；GET 无副作用、DELETE 幂等。
- 2026-11-11 全量审计按磁盘重扫：055 使 specs 总数达 54（054 资源中心由其它会话在途，未计入）。

## 通过判据

- [ ] `test_menu_settings.py` 全绿，`vue-tsc` + `vite build` 通过
- [ ] GET 空租户返回默认方案且库中无新增文档
- [ ] 跨分组挂接 / 自环 / 非法 key / 非法 iconKey 被拒
- [ ] `locked` 节点始终可见；DELETE 后恢复默认且可重复调用
