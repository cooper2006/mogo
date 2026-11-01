# Quickstart: user-web SSO 接收方（门户免二次登录进入 MOGO 用户工作台）

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Tasks**: [tasks.md](./tasks.md)

**用途**: 本文件是**可执行的验证清单**。覆盖"门户签发票据 → user-web 换票 → 进入工作台"的端到端链路，以及多租户选租户、异常防护两类横切场景。本特性已于 2026-10-15 按 T001–T020 全部实现并验证。

> 前置：需要一个已在 `end_users` 存在且共享主键 `id` 匹配的门户测试用户；门户后端具备服务身份令牌（`X-MOGO-Service-Token`）与 `portal.issue_ticket` scope。

## 0. 前置

```bash
# 后端（chat-api）
cd services/chat-api
# 确保已配置服务身份密钥（PORTAL_SSO_SECRET 或回退 END_USER_AUTH_SECRET）
# 前端
cd apps/user-web
pnpm install        # 若依赖未装
```

## 1. 启动开发态

```bash
pnpm -C apps/user-web dev
```

浏览器打开 dev 地址。

## 2. 验证清单

### 2.1 单租户免密进入（US1 / FR-001–FR-009）

1. 门户后端用有效 `X-MOGO-Service-Token` 调 `POST /api/auth/portal-ticket`，声明已在 `end_users` 存在（共享 `id` 匹配）的外部身份。
2. 断言返回一次性 HMAC 票据（TTL 60s，含 `sub`/`exp`/`session_id`）。
3. 门户前端带票跳转到 user-web（`state=` 传票）。
4. user-web `onMounted` 立即 `replaceState({}, '')` 清除 state，再 `POST /api/auth/portal-exchange {portal_token}`。
5. 断言返回 `{token, profile, expiresAt}`，且 `end_user_sessions` 出现 `exchanged: true` 记录；user-web 写入 `localStorage`（`auth_token`/`auth_account`/`auth_user_profile`）进入工作台。
6. URL 中**不应**出现令牌（已 `replaceState` 清除）。

### 2.2 多租户选租户（US2 / FR-010）

1. 用属于多个租户的 `end_users` 走 2.1 的换票链路。
2. 断言返回 `requiresTenantSelection` 与候选租户列表（**不**建会话、不返回 token）。
3. 复用 `POST /api/auth/login/select-tenant` 选租户 → 建会话返回 token，进入**正确租户**的工作台。

### 2.3 异常与攻击防护（US3 / FR-005 / FR-012 / FR-016）

1. **过期票据**（exp 已过）→ `portal-exchange` 返回 401（fail-closed）。
2. **重放**（同一票据二次换票）→ 返回 401（`exchanged` 已置位，`upsert=True`）。
3. **映射失败**（`id` 不在 `end_users`）→ `portal-ticket` 拒绝（400/401），绝不 JIT 建号。
4. **跨租户**（票据 tenant 与用户可用租户不符）→ `portal-exchange` 返回 401。
5. **换票失败**（无效票据）→ user-web 立即回落登录弹窗，不白屏、不静默卡死。

### 2.4 零回归（与既有登录并存）

1. 不使用票据时，user-web 原有账号密码登录、选租户、会话恢复行为不变。
2. 换票成功后，原有工作台（会话列表、权限、菜单）正常可用。

## 3. 自动化验证

```bash
# 后端：门户票据签发 / 验签 / accept-once / 跨租户 / WebView 回落
cd services/chat-api
python -m pytest tests/api/test_auth_portal_sso.py -q
# 预期: 9 passed

# 前端：换票链路契约测试
cd apps/user-web
pnpm test portal-sso-receiver
# 预期: 契约测试通过
```

## 4. 回滚

本特性为"接收方"，无数据迁移。回滚只需还原以下文件：

- `services/chat-api/app/core/portal_sso.py`（新增：票据签发/验签/accept-once）
- `services/chat-api/app/api/endpoints/auth.py` 的 `portal-ticket` / `portal-exchange` 端点
- `services/chat-api/app/core/config.py` 的 `PORTAL_SSO_SECRET`
- `apps/user-web/src/App.vue` 的 `onMounted` 读票/清票/换票/回落逻辑
- 撤销 gatekeeper 中登记的 `portal.issue_ticket` scope

回滚后门户跳转将回落到登录弹窗（与"无 SSO 接收方"行为一致）。
