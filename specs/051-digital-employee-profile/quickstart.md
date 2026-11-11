# Quickstart: 051 数字员工档案

**状态**：B1 + B2 已落地；T028「真实登录态 + 下拉选中员工发起会话」为人工保留项（2026-11-10 reviewer 复核后保持未勾），本文件不虚勾。

## 做了什么

新增「数字员工」实体：岗位档案（能力边界）+ 知识库挂载 + 记忆 scope + 模型配置 + Harness profile + SOP/编排绑定 + 定时任务归属；门户从「申领应用」升级为「认领员工」。

- admin-api：`app/employees/`（model / repository / profile / injection / api_keys）+ `app/api/routes/employees.py`，集合 `employees` / `employee_api_keys`。
- chat-api：`app/api/endpoints/employees.py`（用户可用员工列表，认领开通过滤）、`app/api/endpoints/sessions.py` 创建接受 `employee_id` 并注入档案；IM 渠道多员工绑定与规则路由见 `app/im_gateway/routing.py`（集合 `channel_employee_bindings`），路由写审计事件 `im.employee.route`。
- 会话未声明 `employee_id` 时**零行为改动**；能力边界与 001 门禁取交集，R4 红线不被档案覆盖。

## 前置条件

1. kiri 生产栈在线（10 Pod Running），`localhost:3000/admin/setup` = 200。
2. admin 会话（Bearer / Cookie）具备员工管理写权限；至少一个已开通的知识库与已启用的模型实例（32-hex ID）。
3. 门户认领需 001 审批流可用。

## 如何启用

```bash
# 管理端创建（需 admin 凭证）
curl -s -X POST -H "Authorization: Bearer <admin token>" -H 'Content-Type: application/json' \
  -d '{"name":"财务分析员工","position":"财务分析","capability_allowlist":["tool:search"],"status":"active"}' \
  http://localhost:3000/admin-api/api/v1/employees

# 用户侧可用员工列表
curl -s -H "Authorization: Bearer <user token>" \
  http://localhost:3000/api/v1/employees

# 会话携带员工档案
curl -s -X POST -H "Authorization: Bearer <user token>" -H 'Content-Type: application/json' \
  -d '{"employee_id":"<32-hex>"}' http://localhost:3000/api/v1/sessions
```

## 如何验证

```bash
cd /Users/cooper/mogo
services/admin-api/.venv/bin/python -m pytest services/admin-api/tests/test_employees.py \
  services/admin-api/tests/test_employee_credentials.py \
  services/admin-api/tests/test_employee_tenant_identity.py -q -o addopts=
services/chat-api/.venv/bin/python -m pytest services/chat-api/tests/services/test_t999_audit_t998_docs.py -q -o addopts=
cd apps/admin-web && npx vue-tsc --noEmit
cd ../user-web && npx vue-tsc --noEmit
```

## 注意事项

- **T028 人工保留项**：管理页与门户目视已证实，但「下拉选中具体员工并发起会话」从未验证，且历史 200 依赖自签合成登录态（会话已删、当前不可复现）。需真实登录态复现后再勾 `tasks.md` T028。
- 3000 网关的 `/admin-api` 反代已在位（kiri 实测 401 而非 404）；若本地另起 vite 代理，注意 3001 与 3000 的区别。
- 成本经 035 `agent_id` 归因，不新建计量体系；员工模板分发走 053，本特性不另建通道。
- `employees` / `employee_api_keys` / `channel_employee_bindings` 已纳入 `tenant_purge`（2026-11-11 审计修复）。

## 通过判据

- [ ] 三组 admin-api 员工测试 + IM 审计枚举测试全绿，双端 `vue-tsc` exit 0
- [ ] 未声明 `employee_id` 的会话行为零改动
- [ ] 白名单外工具调用被拒并审计；跨租户查询 fail-closed
- [ ] T028 真实登录态下拉选中员工发起会话（**待人工**，未勾不算通过）
