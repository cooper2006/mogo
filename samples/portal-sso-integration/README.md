# 门户 SSO 集成示例（portal-sso-integration）

> 对应 spec 029「user-web 门户 SSO 接收方」的**门户侧接入**（集成方案
> `docs/MOGO-Web应用集成方案.md` §1.3.2「路径 1：MOGO 签发 + 门户转发票据」）。
>
> 目标：外部门户已登录的用户，**不二次登录**进入 MOGO 用户工作台。

## 架构与时序

```
① 用户已在外部门户登录
② 门户后端 ──X-MOGO-Service-Token──▶ POST {MOGO}/api/auth/portal-ticket
                                       （服务身份 + scope portal.issue_ticket + user_id）
③ MOGO 签发一次性票据（HMAC-SHA256，TTL 60s，含 session_id）
④ 门户前端 ──跳转──▶ user-web  （票据经 history.state.portalToken 传入，不落 URL）
⑤ user-web 启动 → 读 window.history.state.portalToken → 立即 replaceState 清除
⑥ user-web ──POST {MOGO}/api/auth/portal-exchange {portal_token}──▶ MOGO
⑦ MOGO 验签 + accept-once（复药 401）+ 按 end_users._id 匹配 → 复用 _create_session 建会话
⑧ user-web 写 localStorage（auth_token / auth_account / auth_user_profile）→ 进入工作台
```

> ⚠️ 实际服务身份请求头为 **`X-MOGO-Service-Token`**（沿用 022 `app/api/principal.py`
> 与 `app/security/service_token.py` 的常量 `SERVICE_TOKEN_HEADER`），而非集成方案正文里的
> `X-MOGO-Service-Token`。二者仅差一个字母，以代码为准。

## 前置条件

| 项 | 说明 |
| --- | --- |
| 账号预置 | 门户用户必须已在 MOGO `end_users` 有记录，且**共享主键 `_id`** 与门户用户 id 一致。**无 JIT**——匹配不到即回退登录弹窗。 |
| 服务令牌 | 门户后端持有 022 服务凭据 `MOGO_PORTAL_TOKEN`（与 chat-api 侧同值的共享密钥）。chat-api 侧由 `build_issuer_from_env("portal")` 读取同名变量。 |
| 票据密钥 | chat-api 侧 `PORTAL_SSO_SECRET`（留空则回退 `END_USER_AUTH_SECRET`）。**门户不持有该密钥**——票据由 chat-api 签发。 |
| scope | 服务令牌须携带 `portal.issue_ticket`（022 gatekeeper 已注册）。 |

## 文件

- `portal_backend.py` —— 门户后端：签 022 服务令牌 → 调 `portal-ticket` 拿一次性票据 → 返回给前端。
- `entry.js` —— 门户前端：拿到票据后，经 `history.state` 跳转 user-web（不落 URL）。

## 配置（门户后端环境变量）

```bash
MOGO_BASE_URL=https://mogo.example.com          # chat-api 根地址
MOGO_PORTAL_TOKEN=<与 chat-api 侧一致的共享密钥>  # 022 服务凭据
```

## chat-api 侧配置

```bash
# 可选：独立票据签名密钥；留空则回退 END_USER_AUTH_SECRET
PORTAL_SSO_SECRET=<独立密钥>
# 022 服务凭据（portal-ticket 端点校验用；留空则 portal-ticket 返回 401）
MOGO_PORTAL_TOKEN=<与门户后端一致的共享密钥>
```

## 失败语义（全部 fail-closed，前端回退登录弹窗）

- 票据签名错 / 被篡改 / 格式错 / 过期 → `portal-exchange` 401。
- 票据二次使用（accept-once）→ 401。
- `end_users` 匹配不到 / 非 active → 401（不建号）。
- 跨租户（票据 tenant_id 与用户当前租户不符）→ 401。
- 多租户用户 → `portal-exchange` 返回 `{requiresTenantSelection, challengeToken, candidates}`，
  前端打开登录弹窗进入「只选组织」流程（复用 `POST /api/auth/login/select-tenant`），免二次输密码。

## 安全要点

- 票据 **一次性**（`end_user_sessions.exchanged`）、**TTL 60s**、**绝不下落 URL**。
- 验签用 `hmac.compare_digest` 常数时间比较。
- 门户**不持有**票据签名密钥；只持有 022 服务身份凭据（`MOGO_PORTAL_TOKEN`）。
- 门户不得把票据写进 URL query / localStorage / 任何可被日志/Referer 捕获的位置。
