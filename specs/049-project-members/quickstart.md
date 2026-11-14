# Quickstart: 049 全链路手工验证（T022）

**状态**：⏸ 待用户提供凭据（2026-11-05 22:10 更新）。

- **早前的环境阻塞已消失**：20:47 时 `mogo-chat-api-1` / `mogo-admin-api-1` / `mogo-document-api-1` 反复重启，日志 `psycopg_pool.PoolTimeout: pool initialization incomplete after 5 sec`（外部 PanWeiDB `PANWEIDB_HOST=172.17.5.145` 连不上）；21:28 复核三者均已 `healthy`，`GET /ready` 返回 200 且有正常业务日志，`mogo-gateway-1` 的 3000 端口返回 200。该故障**与 049 代码无关**。
- **当前剩余阻塞**：用户已选择「我提供凭据」，等待 admin 会话 / 登录方式 + 创建者 A / 成员 B / 非成员 C 三个真实账号，以及配额度 / 加成员的写操作授权。网关直连 `/api/v1/...` 返回 404（API 前缀或认证头待确认）；栈内 `mogo-panweidb-1`（127.0.0.1:5432）凭据与服务实际连接的外部库不一致，不能用 psql 旁路核对数据面。
- 自动测试不受影响（纯逻辑 + fake DB：chat-api 27 passed / admin-api 51 passed）；本清单只覆盖需要真实 HTTP 端点的部分。
- **不依赖账号的严格收口已完成**（22:10）：3 个 410 写路由已删除并同步改测试、`tenant_purge` 旧表清理项已移除、T019 已补运行时双服务对拍（14 passed，变异自检确认非假阳性）；D-2 默认项目租户共享兜底登记为已批准豁免。

## 前置条件

1. `docker compose ps` 中 `mogo-chat-api-1` / `mogo-admin-api-1` / `mogo-panweidb-1` 均为 `healthy`。
2. 能连上 PanWeiDB：`docker exec mogo-panweidb-1 pg_isready -U boncuser -d mogo`（若用外部库，改测 `172.17.5.145:17700` 的连通性并确认 `.env` 指向可达地址）。
3. 准备三个同租户账号：创建者 A、成员 B、非成员 C；管理员账号 admin。
4. 已知数据基线（2026-11-05 核查）：`projects` 2 行（默认项目 + test），`quota_projects` 0 行，`user_quota_policies.scope_type=project` 0 行。

## 验证步骤

### 1. admin「项目管理」显示真实项目（US3 / SC-001）

- 以 admin 登录 admin-web → 「项目管理」页，应显示 2 行（默认 + test）。
- 直接核对接口：

```bash
curl -s -H "Cookie: <admin session>" \
  https://<host>/api/v1/traffic-allocations/projects-with-usage | jq '.data | length'
# 期望 2；每行含 name / memberCount / status / 周期用量与成本
```

- 给 test 项目配额度（FR-008，不再 404）：

```bash
curl -i -X PUT -H "Cookie: <admin session>" -H 'Content-Type: application/json' \
  -d '{"period":"monthly","tokenLimit":100000}' \
  https://<host>/api/v1/traffic-allocations/projects/<test 项目 id>/policy
# 期望 200；user_quota_policies 落一条 scope_type=project, scope_id=<项目 id>
```

- 归档项目折叠进「已归档」分组（`ProjectsPage.vue` 的 `archivedRows`）。

### 2. 成员与可见性（US1 / SC-002）

- A 登录 user-web → 侧边栏非默认项目「…」→「成员」→ 选部门 → 勾选 B → 保存。
- 核对落库：`projects.<id>.member_user_ids` 含 B 且**不含 A**（创建者不落库，FR-001）。
- B 刷新 → 侧边栏出现该项目分组；`GET /askai-api/api/projects` 返回含该项目。
- C 登录 → 列表不含该项目。
- 权限矩阵：B 直接 `PATCH /projects/<id>` 带 `member_user_ids` → 403；对 `default` 项目 PATCH 成员 → 400；默认项目侧边栏不渲染「…」菜单。
- 候选端点（FR-004）：

```bash
curl -s -H "Authorization: Bearer <A token>" \
  'https://<host>/askai-api/api/projects/member-candidates?department_id=<部门 id>' | jq '.data.items'
# 期望仅该部门及下级、仅 active 用户、字段白名单（无 password/salt）
```

### 3. 项目层配额按成员用量计（US2 / SC-003）

- 设 test 项目额度 = A 一次 LLM 调用的 token 量（便于复现）。
- A 发起调用 → 成功；B（成员）再调用 → 被拒，错误文案含「项目层」；C（非成员）在别处调用 → 不受该项目层约束。
- 删除 test 项目的额度策略 → 零行为变化（042 SC-003 等价）。
- 把 test 项目 `status` 改为 `archived` → 项目层不参与四层取小（046 US2 场景 2）。
- 对无成员项目，项目层用量口径 = 创建者本人（FR-010 迁移期读兼容）。

### 4. 收口复核（SC-004 / SC-005）

```bash
# 双服务一致性用例（10 静态 + 4 运行时对拍）
cd services/admin-api && .venv/bin/python -m pytest tests/test_quota_consistency.py -q -o addopts=

# 运行时对拍有效性自检（身份核对 + 变异验证，预期变异后 1 failed）
cd services/admin-api && .venv/bin/python /tmp/qa/verify_049_d4.py

# 读路径 0 命中（只应对出注释 / 退役文案 / 模块名）
grep -rn "QUOTA_PROJECT_COLLECTION" services/*/app
grep -rn "quota_projects" services/*/app
```

## 通过判据

- [ ] admin 页 2 行、配额度 200
- [ ] 成员 B 可见 / 非成员 C 不可见 / 权限矩阵 403 & 400
- [ ] 成员用量合计命中限额被拒，文案含「项目层」；无策略 & archived 不约束
- [ ] 双服务一致性用例全绿、读路径 0 命中

执行完成后回填 `tasks.md` 的 T022 并在此文件记录实测证据（日期、响应码、用量数字）。
