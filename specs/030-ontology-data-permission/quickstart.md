# Quickstart: 本体数据权限（ontology data-scope permission）

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Tasks**: [tasks.md](./tasks.md)

**用途**: 本文件是**可执行的验证清单**。覆盖管理端授权录入、运行时 fail-closed 解析、灰度开关与内部接口、双后端一致性四类场景。本特性已于 2026-10-16 按 T001–T026 全部落地（Phase 0–5；T023 HTTP 冒烟 12/12 + mongo parity 8/8、T024 网关已天然放行、T025 `vue-tsc`+`vite build` 双 exit 0、T026 前端代码级复核六点通过；本轮补 checklist 并抓到 enabled 归一化高危 bug；仅 T026 浏览器目视需用户执行）。

> 前置：租户管理员令牌；`MOGO_DATA_BACKEND` 默认 `mongo`（本特性所有新表双后端可用）。

## 0. 前置

```bash
cd services/admin-api      # 管理端 API
cd services/chat-api       # 运行时解析（权限生效点）
```

## 1. 验证清单

### 1.1 管理端配置本体数据权限（US1 / FR-019–FR-025）

1. 管理员登录 admin-web，打开「本体清单」页 → 看到「我的可见本体」与「全量清单」两个视图，顶部提示当前 `enforce` 状态。
2. 在「用户管理」对某员工点「本体数据权限」→ 批量勾选 2 个本体、选 `read` 模式、保存。
3. 断言 `mesc_ontology_grant` 写入 2 条（`subject_type='user'`），弹窗列表立即可见。
4. 调用 `GET /api/ontologies/users/{uid}/permissions` 断言返回 2 条。
5. 撤销其中 1 条 → 该授权与其**类明细**一并删除，落一条 `grant_delete` 审计。

### 1.2 运行时按用户解析可见本体（US2 / FR-009–FR-018）

1. 给定一组 `mesc_ontology_grant`（tenant 兜底 / org / role / user 四态），调用 `visible_ontology_ids(tenant_id, user_id)`。
2. 断言：同 `ontology_uri` 上 `priority` 大者胜；同优先级取更严格（fail-closed 偏置）。
3. 让数据访问层抛异常 → 断言返回**空集**且**不写缓存**，落一条 `deny` 审计。
4. 检索侧：`semantic_search(..., visible_ontology_ids=frozenset())` → 返回 `[]`；命中缺 `ontology_id` 的条目被隐藏。

### 1.3 灰度开关与内部接口（US3 / FR-016 / FR-020–FR-023）

1. `PUT /api/ontologies/config {enforce:false}` → `effectiveDefault == "allow"`，页面提示"预演模式"。
2. `PUT /api/ontologies/config {enforce:true}` → `effectiveDefault == "deny"`（未匹配即 deny）。
3. `GET /api/internal/ontology-permissions?tenantId=&userId=` 用**正确服务令牌** → 返回 `{tenantId, userId, count, ontologies[]}`；缺/错令牌 → 401。
4. 授权变更后 `sys_config['ontology-permission'].rev` 递增（可被其他进程观察）。

### 1.4 双后端行为一致（US4 / FR-026–FR-027）

1. 同一组 upsert grant → 读回 → 删除，在 `mongo` 与 `panweidb` 各跑一遍。
2. 断言返回字典形状一致（`column_list` 均为数组、`enabled` 均为 bool、时间戳均可序列化）。
3. PanWeiDB（`sql_compatibility=A`）查询使用 `doc #>> '{ontology_id}'` 而非 `->>`，不对 jsonb 文本做 `<> ''` 比较。

## 2. 自动化验证

```bash
# 后端：判权算法 + 双后端一致性 + 内部接口鉴权
cd services/admin-api
python -m pytest tests/test_ontology_permission.py -q        # 判权/审计/配置
# 预期: 全绿（含 mongo parity）

cd services/chat-api
python -m pytest tests/test_ontology_visible_ids.py -q       # 运行时解析 fail-closed
# 预期: 全绿（含异常→空集、不写缓存）
```

## 3. 回滚

本特性为权限层追加，无破坏性迁移。回滚只需：

- 将 `sys_config['ontology-permission'].enforce` 置 `false`（仅配置与预演，不影响既有行为）。
- 删除 `mesc_ontology_grant` / `mesc_ontology_class_detail` / `mesc_ontology_perm_audit` 三表（与 `sys_config` 本体权限键）即可彻底卸载，不影响 RBAC 功能权限与其他业务表。
- 前端 admin-web 的 `/ontologies` 页面与授权弹窗为只读/配置入口，不承载业务数据，可单独回滚。
