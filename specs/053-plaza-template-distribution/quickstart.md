# Quickstart: 053 广场模板分发

**状态**：已实现（29/29 tasks 全勾）；US3 P2 代码/端点契约已于 2026-11-10 复核。

## 做了什么

045 资产中心扩展 `employee_template` / `sop_template` 两类资产坐标：上架 → 广场展示 → 用户「复制到自己名下」（clone 深拷贝，副本可改、原件不动）→ 副本走既有申领审批。SOP 模板发布前过 032 评估门禁（无测试集不得上架）；模板版本升级不强制覆盖副本。

- admin-api：`app/services/templates/`（model / repository，集合 `asset_templates` / `template_clones` / `template_upgrades`）+ `app/api/routes/templates.py`。
- chat-api：`app/api/endpoints/plaza_templates.py`；user-web `src/plaza/PlazaPage.vue`、`src/api/plazaTemplates.ts`。
- 克隆记录 `template_ref`（坐标 + 版本），原件下架/删除不影响副本；克隆时模板已下架则拒绝。

## 前置条件

1. kiri 生产栈在线；045 资产中心 `GET /api/v1/capabilities/list` 可用。
2. 上架需 001 审批 + 032 评估门禁可用（SOP 模板必须有测试集）。
3. 034 凭证加密口径：模板不得含凭证明文，克隆不复制凭证。

## 如何启用

```bash
# 广场目录（分类 / 搜索 / 详情 / 版本查看）
curl -s -H "Authorization: Bearer <user token>" \
  'http://localhost:3000/api/v1/plaza/templates?asset_type=employee_template'

# 复制到自己名下（clone 语义）
curl -s -X POST -H "Authorization: Bearer <user token>" -H 'Content-Type: application/json' \
  -d '{"asset_type":"employee_template","asset_key":"<key>","version":1}' \
  http://localhost:3000/api/v1/plaza/templates/clone
```

## 如何验证

```bash
cd /Users/cooper/mogo
services/admin-api/.venv/bin/python -m pytest services/admin-api/tests/test_plaza_templates.py -q -o addopts=
services/chat-api/.venv/bin/python -m pytest \
  services/chat-api/tests/api/test_plaza_templates_endpoint.py \
  services/chat-api/tests/orchestration/test_plaza_clone_consumer.py -q -o addopts=
cd apps/user-web && npx vue-tsc --noEmit
```

## 注意事项

- 副本使用仍需走 037 / 001 申领审批，未开通 fail-closed。
- 模板新版本只给副本侧「可升级」提示 + 手动升级（整份替换 + 旧副本快照，002 版本化），全审计。
- `asset_templates` / `template_clones` / `template_upgrades` 已纳入 `tenant_purge`（2026-11-11 审计修复）。
- 员工模板与 051 数字员工实体联动；本特性不另建分发通道。

## 通过判据

- [ ] 三份 Plaza 相关测试全绿，`vue-tsc` exit 0
- [ ] clone 后副本可编辑、原件只读且变更不影响副本
- [ ] SOP 模板无测试集上架被 032 门禁拒绝
- [ ] 已下架模板克隆被拒；模板含凭证明文被拒
