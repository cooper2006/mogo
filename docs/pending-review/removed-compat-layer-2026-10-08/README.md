# 待确认：移除 main_id→tenant_id 兼容层

**日期**：2026-10-08
**原因**：`main_id` → `tenant_id` 迁移已完成（Phase 1 双写 → Phase 2 回填 → Phase 3 切读/删字段），
本兼容层已**零引用**，按"彻底切断旧名"要求从源码移除。

**原路径**：`services/chat-api/app/core/tenant_field.py`
**备份**：同目录 `tenant_field.py.bak`

## 原用途（Phase 1 双写窗口期）
- `compose_tenant_fields()` / `set_tenant_fields()`：写入时同时写 `main_id` 与 `tenant_id`
- `tenant_value()`：读取优先 `tenant_id`，回退 `main_id`
- `tenant_scope_filter()` / `add_tenant_scope()`：查询匹配任一键
- `dual_write_props()` / `tenant_prop_value()`：Weaviate `mainId`/`tenantId` 双写

## 为何可以安全移除
- 数据库 `main_id` 字段已 `$unset`（556 文档 / 30 集合，残留 0）
- Weaviate `mainId` schema 属性已删除
- 代码中 `main_id`/`mainId` 代码级残留为 0
- 全库对该模块的 import 为 0（`employee_tenant_fields` 等为同名子串误匹配，非本模块）

**如需恢复**：把 `.bak` 复制回 `services/chat-api/app/core/tenant_field.py` 即可。
