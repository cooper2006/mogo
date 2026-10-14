# MOGO 与 Web 应用集成方案

> **版本基线**：**v0.2.1**（tag `v0.2.1`，HEAD `370e396`）+ **022 安全加固已全部落地**（58/58 任务，Phase 0–7 已提交，且已包含在 v0.2.1 内）。
>
> **本文档由以下 5 份文档合并而成**（原件保留，见附录 B）：
> `docs/web应用集成规划.md`、`docs/业务系统集成方案.md`、`docs/业务系统集成-实施方案.md`、`docs/022-W1-对齐备忘.md`、`docs/本体清单与数据权限-设计方案.md`
>
> **性质**：方案与设计文档，**未改动任何服务代码**。
> **事实基线**：所有接口、头部、状态码、集合与字段均对照当前仓库源码核实，核对点见附录 A。

---

## v2 修订说明（2026-10-13）

本次按 **022 安全加固完成态** + **v0.2.1** 刷新。**以下是相对 v1 的实质性更正**——若你此前读过 v1，请以本版为准：

| # | v1 的说法 | v2 更正 | 影响 |
| :-: | --- | --- | --- |
| 1 | 「机制 B（签名服务凭证）**当前零接线**」 | **已接线**。022 T019/T020/T028 已落地：`app/security/service_token.py` + `app/security/gatekeeper.py`（双服务），并由 `chat-api/app/api/principal.py`、`gatekeeper_client`、admin-api 多个路由消费 | **W1 的净增量大幅缩小**（见第 3、4 部分） |
| 2 | 网关默认 `X-Frame-Options: SAMEORIGIN`，「同源 iframe 零改造」 | 默认配置已改为 TLS 侧 `deploy/nginx/nginx.conf`，其值为 **`X-Frame-Options: DENY`** | **iframe 嵌入必须显式改造**，同源也不再放行 |
| 3 | 网关默认 HTTP（`deploy/docker/nginx.conf`） | **TLS 已默认启用**：`MOGO_NGINX_CONF:-./deploy/nginx/nginx.conf`，443 + HTTP 301（`/healthz` 例外） | 反代与地址书写方式改变 |
| 4 | 未提 CORS | 022 T033/T034 新增 CORS 白名单中间件，**拒绝通配符**，来源由 `CORS_ORIGINS` 配置 | 前端直连跨域**必须显式配来源** |
| 5 | 用户 token 长期有效 | access token TTL **7 天 → 3600s（1h）**；会话**空闲 30min / 绝对 24h** 超时 | **路径 A（业务系统持用户 token）必须处理刷新** |
| 6 | 未提 GET 副作用 | 022 T032 把 4 个 GET 端点的写操作拆成 POST | 调用方需改用新端点 |
| 7 | 未提 SSO 细节 | SSO 改 **POST 换票**（`POST /api/auth/sso/exchange`），票据 TTL **60s**、accept-once | SSO 集成方式改变 |
| 8 | 未提容器加固 | 7 个服务 `read_only` + `cap_drop ALL` + `no-new-privileges` + tmpfs | **自定义挂载/写文件配置需注意** |

> 另：v1 中「`chat-api/app/middleware/` 不存在」这条**已过时**——022 Phase 4 已新建该目录（含 `cors.py`）。`app/deps.py`（两个服务）与 `chat-api/app/api/routes/` **仍不存在**，该提醒继续有效。

### v2.1 补丁（2026-10-13）：服务令牌头改名

**`X-MOVO-Service-Token` → `X-MOGO-Service-Token`**，共 **39 处 / 21 个文件**（`admin-api` 14 个 + `chat-api` 7 个），本文档已同步。

| 位置 | 说明 |
| --- | --- |
| 常量定义 | `app/security/service_token.py` 的 `SERVICE_TOKEN_HEADER` |
| 接收端 | `Header(alias=...)`：`chat-api/app/api/principal.py` + admin-api 多个路由（`gatekeeper_internal` / `capability_assets` / `skill_canary` / `skill_monitoring` / `personal_knowledge_internal`） |
| 发送端 | 出站 `headers={...}`：`gatekeeper_client.py`、`personal_knowledge/lifecycle_client.py`、`skill_package_proxy.py`、`model_connectivity.py`、`model_image_connectivity.py`、`tools.py`、`skills.py` |
| CORS | `app/middleware/cors.py`（双服务）的 `allow_headers` 白名单 |
| 测试 | `tests/test_security_service_token.py`、`tests/test_security_cors.py`（双服务） |

- **不涉及**：前端（`apps/`）、`deploy/`、`document-parser`（后者用 `Authorization: Bearer`，是另一套机制）。
- **部署注意**：这是**破坏性改名**。`docker compose` 全量重启（`./mogo up`）后新旧头不兼容；若做**滚动升级**会出现"新服务收旧头 → 401"的窗口。当前实现**不兼容旧头**（如需过渡期，可让接收端同时接受两个头名）。
- **历史记录未回改**：`docs/WORK_LOG.md`、`specs/LANDING_AUDIT_2026-10-03.md`、`deliverables/gstack/permission-control-data-scope-2026-10-08.md` 仍保留旧名（它们记录当时的状态）。

---

## 目录

- [第 1 部分 · 总体规划](#第-1-部分--总体规划)
- [第 2 部分 · 业务系统场景（接口级）](#第-2-部分--业务系统场景接口级)
- [第 3 部分 · 实施方案（已确认决策）](#第-3-部分--实施方案已确认决策)
- [第 4 部分 · 022 安全加固对齐（已完成态）](#第-4-部分--022-安全加固对齐已完成态)
- [第 5 部分 · 本体清单与本体数据权限](#第-5-部分--本体清单与本体数据权限)
- [第 6 部分 · 约束与坑（汇总）](#第-6-部分--约束与坑汇总)
- [第 7 部分 · 选型速查](#第-7-部分--选型速查)
- [附录 A · 事实来源核对点](#附录-a--事实来源核对点)
- [附录 B · 文档沿革与拆分说明](#附录-b--文档沿革与拆分说明)

---

# 第 1 部分 · 总体规划

## 1.1 定位与四类关系

MOGO 是**一套自托管的多服务系统 + 一个统一入口网关**：对外默认只有一个入口（`MOGO_PORT` 默认 `3000`；TLS 侧 `MOGO_HTTPS_PORT` 默认 `443`），内部按路径分发给用户工作台、管理后台、Chat API、Admin API。

因此"和现有 Web 应用结合"本质上只有四类关系，先想清楚自己属于哪一类，再选模式：

| 关系 | 方向 | 典型诉求 | 对应模式 |
| --- | --- | --- | --- |
| A | 现有应用 → MOGO | 把 Agent 能力**嵌进**我现有的门户/产品里 | 模式一（嵌入） |
| B | 现有应用 → MOGO | 后端**调用** MOGO 的对话/任务/知识能力 | 模式二（API 化） |
| C | 平级并存 | 两套系统**同域/同 SSO** 一起运营 | 模式三（网关统一） |
| D | 双向 | MOGO **调用**你的业务系统，或你的系统**推事件**给 MOGO | 模式四（能力互操作） |

> 现实项目通常是 **C 打底 + B 为主 + A/D 按需叠加**。

```
┌──────────────┐       链路一（出站调用）        ┌─────────────────────┐
│              │  Bearer / Service Token  ────▶ │  MOGO 网关 :443     │
│  业务系统     │                                 │  /api/*             │
│  (ERP/CRM)   │  ◀────  SSE 流式结果 ──────────  │  chat / sessions    │
│              │                                 │  external-tools     │
│              │       链路二（入站调用）         │  business-index     │
│              │  ◀────  Agent 调你们的 API ────  │                     │
└──────────────┘                                 └─────────────────────┘
```

---

## 1.2 事实清单：MOGO 的对外接口面

### 1.2.1 入口与路由（v0.2.1：TLS 默认启用）

**默认**加载的是 **TLS 侧**配置 `deploy/nginx/nginx.conf`（compose 默认值 `MOGO_NGINX_CONF:-./deploy/nginx/nginx.conf`）：

| 路径 | 上游 | 说明 |
| --- | --- | --- |
| `/healthz` | 网关自身 | 健康检查，**恒 HTTP 200**（豁免 301，供 LB 探针） |
| 其余全部 | — | HTTP(80) → **301** → `https://$host$request_uri` |
| `/` | `user-web` | Vue3 用户工作台 |
| `/admin/` | `admin-web` | 管理后台 |
| `/api/` | `chat-api:8000` | 公开 API |
| `/askai-api/` | `chat-api:8000` | **注意见下** |
| `/admin-api/` | `admin-api:8100` | 管理 API |

**TLS 与安全响应头**（`deploy/nginx/nginx.conf`）：

| 项 | 值 |
| --- | --- |
| 协议 | `ssl_protocols TLSv1.2 TLSv1.3`（禁用 1.0/1.1），仅 AEAD 密码套件 |
| HSTS | `max-age=15552000; includeSubDomains; preload` |
| `X-Content-Type-Options` | `nosniff` |
| **`X-Frame-Options`** | **`DENY`** ← 见 1.3.1，**跨域与同源 iframe 均被禁止** |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `geolocation=(), microphone=(), camera=()` |

回退到 HTTP（仅限本地/内网调试）：把 `MOGO_NGINX_CONF` 指向 `./deploy/docker/nginx.conf`（HTTP 侧配置，其 `X-Frame-Options` 为 `SAMEORIGIN`）。

> ⚠️ **有效 API 前缀是 `/api/`**。`/askai-api/` 在网关中会**剥离前缀**转发到 chat-api 根路径，而 chat-api 未在根路径注册路由（`api_router` 挂载于 `/api`）——**请统一使用 `/api/`**。

### 1.2.2 三类认证（v0.2.1 有重要变化）

| 主体 | 凭据 | 用途 | 来源 |
| --- | --- | --- | --- |
| 终端用户 | `Authorization: Bearer <token>` | 用户态调用 `/api/*` | `POST /api/auth/login` 发放，落 `end_user_sessions` |
| 服务（机器对机器） | `X-MOGO-Service-Token: <token>` | 后端到后端调用，**跳过用户会话** | 新式：022 签名凭证；旧式：`ADMIN_BACKEND_SERVICE_TOKEN` 静态密钥（回退） |
| 管理后台 | Admin SSO 票据 | 免密进入 `/admin/` | `POST /api/auth/sso/exchange`（**POST 换票**，见下） |

**⚠️ 022 带来的三处时效变化（直接影响集成）**：

| 项 | 变化 | 对集成的影响 |
| --- | --- | --- |
| **access token TTL** | 7 天 → **3600s（1h）**（`END_USER_AUTH_TOKEN_TTL_SECONDS`；启动时超 1h 告警） | **路径 A（业务系统持用户 token）必须处理刷新/重登** |
| **会话超时** | **空闲 30min / 绝对 24h**（`app/security/session_timeout.py`，接入 `resolve_session_user`） | 长时间无活动的集成会话会被强制 401 |
| **Admin SSO** | 票据 TTL 收敛到 **60 秒**；新增 `POST /api/auth/sso/exchange`；**accept-once**（按票据内 `session_id` 打标记，二次换票 401） | SSO 跳转不能再拼 `?sso_token=` |

**作用域强校验（fail-closed）**：请求的 query/body 里若带 `userId`/`tenantId`，必须与 token 解析出的主体一致，否则 `403`（`user_scope_mismatch` / `tenant_scope_mismatch`，见 `app/api/principal.py`）。**不要伪造这两个字段**。

### 1.2.3 服务令牌：新式签名凭证（v0.2.1 已接线）

**这是 v1 → v2 最大的更正。** 022 已把服务间凭证从"单一共享静态密钥"升级为**签名令牌 + 三重绑定 + scope 最小权限**，并且**已经接线**：

| 组件 | 位置 | 职责 |
| --- | --- | --- |
| 签名令牌 | `app/security/service_token.py`（双服务） | `v1\|payload\|sig`；HMAC-SHA256；TTL ≤ 24h；主/备双密钥轮换 |
| 服务间校验 | `app/security/gatekeeper.py`（双服务） | `build_issuer_from_env()` / `verify_service_call()` / `bind_context_to_claim()`；**三重绑定** service_id + tenant_id + user_id；**scope** 最小权限 |
| 消费方 | `chat-api/app/api/principal.py`、`app/services/gatekeeper_client.py`、admin-api 多个路由、document-parser | 按上下文签发 / 接收端核对 |

**`verify_service_call` 的三重绑定**（`app/security/gatekeeper.py`）：

1. `claim.service_id` 必须等于 `expected_service_id`（防令牌被转发去访问另一个服务身份）
2. `tenant_id` 非空时与 `claim.tenant_id` 核对（防跨租户）
3. `user_id` 非空时与 **`claim.extra["user_id"]`** 核对（**"服务代表某用户"的能力已具备**）
4. `required_scope` 非空时令牌必须显式携带（`insufficient_scope` / `unknown_scope` 均 fail-closed）

**回退机制**：未配置新式凭据（环境变量缺失或密钥过弱）时，`build_issuer_from_env()` 返回 `None`，调用方**回退到静态 `ADMIN_BACKEND_SERVICE_TOKEN` 比对**——灰度可回滚。

**⚠️ 关键限制（W1 要解决的）**：

- `chat-api/app/api/principal.py` 里 **`EXPECTED_CALLER_SERVICE_ID = "admin-api"` 是硬编码单值** —— 业务系统作为新调用方**无法直接复用**。
- claim 分支返回的 `ApiPrincipal(kind="admin_service", tenant_id=tenant_id)` **丢弃了 user_id**。
- scope 注册表只登记了 3 条内部路径：`/api/v1/models`、`/api/v1/skills`、`/api/v1/external-tools`。
- **对话/Agent 入口仍只认终端用户 Bearer**（见下）。

**服务令牌的实际接受范围**：

| 端点组 | 是否接受服务令牌 |
| --- | --- |
| `/api/external-tools/*`、`/api/models/*`、`/api/skills/*`、`/api/skill-package-install/*`（走 `require_api_principal`） | ✓ |
| `/api/chat/completions`、`/api/chat`、`/api/sessions*`、`/api/tasks/*`（走 `resolve_session_user`） | ✗ **只认用户 Bearer** |

### 1.2.4 能力接口（用于互操作）

| 能力 | 路由（当前） | 关键点 |
| --- | --- | --- |
| A2A Agent 互通（012） | `/internal/a2a/agents/{agent_id}/card` + JSON-RPC `message/send` / `tasks/get` / `tasks/result` | AgentCard 为 Dify-first 映射；task id 幂等；治理拒绝 `-32000`，**不重试不 failover** |
| IM / 事件入站（013） | `POST /internal/im/webhook/{channel}` | HMAC 签名（`X-IM-Timestamp` / `X-IM-Nonce` / `X-IM-Signature`，密钥 `IM_WEBHOOK_SECRET`）+ 会话-渠道绑定 |
| 外部工具（HTTP 工具） | `/api/external-tools*` | 注册 HTTP 工具供 Agent 调用 |
| 业务系统语义索引（014） | `/api/business-index/*` | 实体指针索引，**只读业务库**，命中带 citation 锚点 |
| 知识 / 记忆 / 上下文 | `/api/` 下 `knowledge_sources` / `memory` / `context_space` | 三范围记忆 + `mogo://` 统一寻址（021，v0.2.1 已生产可达） |
| Skill 生态 | `/api/skills*` / `skill_package_install` | ZIP 安装 |
| 会话结束语义（002） | `POST /api/sessions/{id}/end` | v0.2.1 新增；触发 009 `SessionEnd` → 017 分层记忆沉淀 |

> ⚠️ `/internal/*` 前缀**默认不在网关路由表内**，需显式加 `location`（见 3.7）。

### 1.2.5 ⚠️ v0.2.1 的端点方法变更（T032：GET 无副作用）

022 把 4 个 GET 端点里的写操作拆成了 POST。**调用方若已按旧方法接入，必须改**：

| 原端点 | 变更后 |
| --- | --- |
| `GET /api/auth/me` | 只读；刷新租户列表拆到 **`POST /api/auth/me/refresh-tenants`** |
| `GET /api/sessions/{id}` | 只读；清除 `scheduled_unread` 拆到 **`POST /api/sessions/{id}/read`** |
| `GET /api/personal-knowledge/{id}` | 只读；写 `grant.seen_at` 拆到 **`POST /api/personal-knowledge/{id}/ack`** |
| `GET /admin-api/.../organizations/billing` | 只读（组织缺失返回 `needsInit`）；惰性建库拆到 **`POST /organizations/billing/init`** |

> 该约束由 `deploy/tests/test_no_side_effects_get.py` 用 AST 静态扫描守住——**将来任何人往 GET 端点塞写操作都会 CI 失败**，不要指望"改回 GET 顺便写点东西"。

### 1.2.6 部署与规模

- Docker Compose 一键起服务：网关、两个 Web 应用、chat-api、admin-api、document-parser（+ worker）、DSH Runtime Host 池 + sticky LB、MongoDB、Redis、Weaviate、密钥引导。
- **容器加固（022 T027）**：7 个服务 `no-new-privileges` + `cap_drop: [ALL]` + `read_only: true` + tmpfs；两个 nginx 服务仅保留 `NET_BIND_SERVICE`。**自定义挂载/写文件配置需注意只读根**。
- DSH Runtime Host 多副本，**按 `X-Session-Id` 一致性哈希做会话亲和**。前置再加代理时**必须原样透传 `X-Session-Id` 与 `Upgrade`/`Connection`**。
- 开源版为**单租户自托管**（租户标记 `community`），登录强制选择组织。

---

## 1.3 模式一：嵌入

### 1.3.1 iframe 嵌入（**v0.2.1 起必须显式改造**）

- **硬约束（已变化）**：默认网关配置下发 **`X-Frame-Options: DENY`** —— **任何 iframe（含同源）都会被浏览器拒绝**。v1 里"同源零改造"的说法已不成立。
- 要嵌入必须**显式放行**，二选一：
  1. 改网关响应头为 CSP `frame-ancestors 'self' https://portal.你们域名;`（推荐，粒度可控；`ALLOW-FROM` 已废弃）；
  2. 或在自定义 nginx 片段里把 `X-Frame-Options` 降为 `SAMEORIGIN`（仅解决同源，跨域仍不行）。
- 注意：iframe 内是 MOGO 自己的登录态，门户的登录态不会自动带入。

### 1.3.2 单点登录打通（免二次登录）

#### ⚠️ 先澄清：MOGO 现有的「SSO」不是标准单点登录

仓库里的 SSO **不是** OIDC/SAML 对接外部 IdP，而是 **MOGO 内部的单向免密跳转**：

```
user-web（已登录终端用户） ──免密跳转──▶ admin-web（管理后台）
        ▲ 发起方（source）                    ▲ 接收方（target）
```

链路（4 步，均已核对源码）：

| 步 | 位置 | 动作 |
| :-: | --- | --- |
| 1 | user-web 已登录 | 持 `end_user_sessions` 的 Bearer token |
| 2 | `apps/user-web/src/App.vue` → `getAdminSSOToken()` | `POST /api/auth/admin-sso`（chat-api）→ 拿到 `sso_token`（HMAC 票据，TTL **60s**） |
| 3 | `apps/user-web/src/utils/adminUrl.ts` | `window.open(url, '_blank', 'state=<token>')` —— **令牌不落 URL**（022 T030/T031） |
| 4 | `apps/admin-web/src/stores/auth.ts:84` → `exchangeSsoToken()` | 读 `window.history.state.ssoToken` → `POST /api/auth/sso/exchange`（admin-api）→ 换管理端 access token；**accept-once**（用一次即失效）+ `replaceState({}, '')` 清除 |

**关键前提**：`admin_sso` 要求该用户**已存在 `admin_accounts` 记录**、非 `member` 组、租户为 `enterprise` 且 `canAccessAdmin`。终端用户（`end_users` / `end_user_sessions`）与管理端账号（`admin_accounts` / `admin_sessions`）是**两套分离的账号体系**。

#### 因此：user-web 需不需要加 SSO？

| 你的目标 | 是否需要 | 说明 |
| --- | :-: | --- |
| **外部系统/门户免密进入 MOGO 用户工作台** | **需要新增** | user-web **完全没有接收方能力**（无换票端点、无 `history.state` 读取）；它只有发起方能力（`getAdminSSOToken`） |
| 觉得「admin 有 SSO、user-web 没有」不对称 | **不需要** | user-web 是这条链路的**起点**；它本身已有登录（`loginWithPassword` / `register` / `selectTenantAndLogin`） |
| 从 admin 免密跳回 user-web | **不需要** | 两套账号体系分离，`admin_accounts` 不一定有对应的 `end_users`；`apps/admin-web` 也无反向跳转代码 |

#### 若要新增（上表第 1 行）需要做

→ **详细设计见下一小节**。要点：后端 2 个新端点（签发 + 换票）、前端启动换票、**账号映射规则**（最关键）、租户映射、安全对齐 022。

> **已知坑**：`apps/user-web/src/App.vue:1297` 的注释提到 SSO 在**嵌入式 WebView** 下会被端点拒绝（token 已被消费或环境限制）。若要 iframe/WebView 场景，需先验证这一点。

#### 详细设计：为 user-web 新增 SSO 接收方（**已确认要做**）

**目标**：外部门户的用户，在**不二次登录**的前提下进入 MOGO 用户工作台。

**方案选型**

| 路径 | 做法 | 外部系统需要什么 | 评价 |
| --- | --- | --- | --- |
| **1. MOGO 签发 + 门户转发票据**（推荐） | 门户后端用**服务身份**调 MOGO 拿一次性票据 → 前端带票跳 user-web → user-web 换票建会话 | 只需服务令牌（022 已具备） | 外部系统**不持有** MOGO 签名密钥；票据一次性、短 TTL |
| 2. 外部系统自签票据 | 门户用自己的密钥签，MOGO 验签 | 共享签名密钥 + 实现 MOGO 票据格式 | 密钥管理面变大，不推荐 |
| 3. 服务令牌 + 后端渲染 | 门户后端调 MOGO API，结果渲染进门户 | 服务令牌 | 用户**不进** user-web，能力受限于 API |

**路径 1 时序**

```
① 用户已在外部门户登录
② 门户后端 ──X-MOGO-Service-Token──▶ POST /api/auth/portal-ticket
                                      （服务身份 + 声明外部身份）
③ MOGO 签发一次性票据（HMAC，TTL 60s，含 session_id）
④ 门户前端 ──跳转──▶ https://mogo.内网/  （票据经 state= 传入，不落 URL）
⑤ user-web 启动 → 读 window.history.state.portalToken → 立即 replaceState 清除
⑥ user-web ──POST /api/auth/portal-exchange {portal_token}──▶ MOGO
⑦ MOGO 验签 + accept-once + 匹配 end_users → 建 end_user_sessions
⑧ user-web 写 localStorage（auth_token / auth_account / auth_user_profile）→ 进入工作台
```

**后端改动（chat-api，2 个新端点）**

| 端点 | 鉴权 | 职责 |
| --- | --- | --- |
| `POST /api/auth/portal-ticket` | **服务身份**（`X-MOGO-Service-Token`，022 机制） | 校验调用方 → 按声明的外部身份解析 `end_users` → 签发一次性票据 |
| `POST /api/auth/portal-exchange` | 公开（凭票据） | 验签 → accept-once → **复用 `_create_session()`** 建会话 → 返回 `{token, profile, expiresAt}` |

- **票据格式复用 `admin_sso` 的形态**：`base64url(payload).base64url(HMAC-SHA256)`，payload 含 `sub` + `exp` + `session_id`。
- **换票内部复用现有 `_create_session(user_doc, available_tenants)`**（`chat-api/app/api/endpoints/auth.py`）—— 会话建立逻辑**零改动**。
- **accept-once** 复用 admin-api 的做法：在 `end_user_sessions` 上打 `exchanged: true`，二次换票 401。⚠️ 必须 `upsert=True` —— admin-api 的注释写明：若签发端未落库，不留幂等凭据则重放检查会失效。

**账号映射（最关键决策）**

| 方案 | 做法 | 前提 | 建议 |
| --- | --- | --- | --- |
| **(a) 预置账号 + 匹配**（推荐） | 外部用户必须已在 `end_users` 有记录，按**共享主键 `id`** 匹配（三表共用，业务系统用户 id 即 MOGO `end_users.id`） | 三表共用，记录天然同源 | ✅ 与已定决策一致 |
| (b) JIT 建号 | 首次 SSO 自动建 `end_users` 记录 | 需防滥用 + 需定租户归属 | 备选 |
| (c) 不落库 | ✗ **不可行** | `resolve_session_user` 要求 `end_users` 记录存在 | — |

> **(a) 与第 5 部分天然衔接**：既然「用户/租户/组织机构三表与业务系统共用」已定为目标态，`end_users` 由业务系统权威维护，SSO 只需**匹配**、不需建号。**匹配键用共享主键 `id`**（而非 email/login_name）—— 业务系统用户 id 与 MOGO `end_users.id` 是同一行，最稳。

**租户映射**

- 单租户：票据里直接带 `tenant_id`（签发时由门户声明）。
- 多租户：票据只带身份，换票时用 `load_tenant_candidates()` 取该用户可用租户；多个则返回 `requiresTenantSelection` —— **复用现有挑战流程** `_create_login_challenge` / `POST /api/auth/login/select-tenant`。

**前端改动（user-web）**

- `apps/user-web/src/App.vue` 的 `onMounted`（第 1819 行）开头加：读 `window.history.state.portalToken` → 立即 `replaceState({}, '')` 清除 → 调换票 → 成功则写 `localStorage` 的 `auth_token` / `auth_account` / `auth_user_profile`（key 定义在第 60–63 行）→ 继续正常启动。
- 失败（票据过期 / 已用 / 映射不到账号）→ **回落到登录弹窗，不要静默失败**。
- 写法照 `apps/admin-web/src/stores/auth.ts:80-100`。

**安全对齐 022**

| 项 | 做法 |
| --- | --- |
| 票据一次性 | `end_user_sessions.exchanged` 标记（照 admin-api） |
| 短 TTL | 60s（对齐 `ADMIN_SSO_TOKEN_TTL_SECONDS`） |
| 不落 URL | `state=` 传参 + 立即 `replaceState`（对齐 022 T030/T031） |
| 签名校验 | `hmac.compare_digest` 常数时间比较，**fail-closed** |
| 签发端点鉴权 | 走 022 服务身份（`verify_service_call`），**不裸暴露** |
| 密钥 | 复用 `END_USER_AUTH_SECRET`，或新增独立 `PORTAL_SSO_SECRET`（**推荐独立**，便于轮换） |

**落地阶段**

| 阶段 | 内容 |
| --- | --- |
| 1 | `portal-ticket` + `portal-exchange` 两端点 + 测试（正向 / 过期 / 重放 / 映射失败 / 跨租户） |
| 2 | user-web 启动换票 + 失败回落 |
| 3 | 门户侧接入（服务令牌 + 跳转） |
| 4 | 若多租户：接挑战流程 |

**已定决策（2026-10-13 用户确认）**

| # | 决策点 | 结论 | 对设计的影响 |
| --- | --- | --- | --- |
| 1 | 账号匹配字段 | **共享主键 `id`**（三表共用，业务系统用户 id = MOGO `end_users.id`） | `portal-ticket` 按 `id` 解析 `end_users`；不依赖 email / login_name |
| 2 | 是否 JIT 建号 | **否，仅匹配** | 映射不到 `id` 即回落登录弹窗；不自动建号 |
| 3 | 多租户 | **是** | 票据只带身份，换票走现有挑战流程（`load_tenant_candidates` + `POST /api/auth/login/select-tenant`）让用户选租户 |
| 4 | 域关系 | **跨域传票** | 票据经 `state=` / POST 传入，不依赖共享 Cookie（对齐 022 T030/T031） |

> 设计现已**完整可落地**：账号映射用共享 `id`、不做 JIT、租户走挑战流程、票据跨域传递。实施见「落地阶段」4 个阶段（端点 + 换票 + 门户接入 + 挑战流程）。

#### 现状与既有路径

- MOGO 有独立的 `end_users` 与 `end_user_sessions`，**不内置 OIDC/SAML 对接**。
- 可行路径（按成本递增）：
  1. **服务令牌换票**：门户后端用服务令牌调 MOGO，把结果渲染进门户页面 —— **推荐，改动最小**。
  2. **代登录**：需注意 `auth.py` **没有代登录接口**，需评估是否新增。
  3. **改前端登录页**：源码级改造，成本最高。
- 现实建议：**第一版一律走"服务令牌 + 后端渲染"，不要碰 MOGO 的登录页**。

### 1.3.3 组件级嵌入（自建 UI，复用 `/api`）

自己写 UI、后端调 `/api/*`。灵活度最高，但要自己维护流式渲染、文件上传、Markdown 渲染等。

---

## 1.4 模式二：API 化

### 1.4.1 后端到后端

```
你的后端  --X-MOGO-Service-Token-->  MOGO /api/*
```

- 用服务令牌（新式签名凭证），**不依赖终端用户会话**——但注意 1.2.3：**服务令牌不能调对话入口**，需走第 3 部分 W1。
- 建议加一层 **BFF 适配层**：统一错误码、超时、重试、固定 `tenantId`。
- 好处：MOGO 的治理链（Gatekeeper 六层门禁、PII 脱敏、配额、审计）**全部生效**。

### 1.4.2 用户态调用（前端直连）

- 前端自己处理 token 生命周期——**注意 TTL 只有 1h**，必须实现刷新。
- **跨域必须配 CORS 白名单（022 T033/T034）**：来源由 `CORS_ORIGINS` 配置（逗号分隔），**通配符 `*` 会被拒绝**（`parse_origins` 显式拦截并告警）；`allow_methods` / `allow_headers` 均为显式白名单（`allow_headers` 已含 `X-MOGO-Service-Token`、`X-Request-ID`）。来源为空是合法状态（拒绝所有跨域）但会告警。

### 1.4.3 流式输出

- chat-api 支持 SSE / WebSocket。**链路每一层都要 `proxy_buffering off`**，否则流式退化成一次性返回。

---

## 1.5 模式三：网关统一

### 1.5.1 同域名 + 路径前缀（推荐）

现有 nginx 前置，把某个前缀反代到 MOGO 网关。**注意 MOGO 侧已是 HTTPS**，所以上游写 `https://`：

```nginx
location /mogo/ {
    proxy_pass https://mogo-gateway:443/;    # 结尾斜杠：剥离 /mogo 前缀
    proxy_ssl_server_name on;                # 上游为 TLS，按 SNI 校验
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Upgrade $http_upgrade;              # 流式必需
    proxy_set_header Connection $connection_upgrade;     # 流式必需
    proxy_set_header X-Session-Id $http_x_session_id;    # 会话亲和必需
    proxy_buffering off;                                 # SSE 必需
    client_max_body_size 220m;
}
```

- MOGO 网关已设 `absolute_redirect off`，**适配路径前缀反代**。
- **同源**能简化登录态与 CORS，但**不会自动解决 iframe**——`DENY` 仍会拦，需按 1.3.1 放行。
- 若上游用自签证书，需在你们 nginx 侧配 `proxy_ssl_verify off;` 或信任该 CA。

### 1.5.2 子域名（最省事）

`mogo.内网域名` 独立解析。**零改造**、故障隔离清晰；缺点：跨域，iframe 需按 1.3.1 放行，跨域 Cookie 需处理，且**必须配 `CORS_ORIGINS`**。

### 1.5.3 选型建议

| 场景 | 推荐 |
| --- | --- |
| 要 iframe 嵌入门户 | **同域名路径前缀**（+ 显式放行 frame-ancestors） |
| 只是并列两个入口 | **子域名**（+ `CORS_ORIGINS`） |
| 门户已有严格网关/审计 | 同域名路径前缀（统一收口） |

---

## 1.6 模式四：能力互操作（双向）

### 1.6.1 MOGO → 你们的系统

- **HTTP 工具**：通过 `/api/external-tools` 注册。
- **业务语义索引**：`/api/business-index` 做实体指针索引——**只读、绝不写你们的库**。
- **A2A 出站**：`app/a2a/outbound.py` 的 `A2AClient`（超时 30s、failover、退避；治理拒绝不重试）。

### 1.6.2 你们的系统 → MOGO

- **事件入站（IM webhook 模式）**：`POST /internal/im/webhook/{channel}`。**前提**：网关放行 `/internal/im/`。
- **A2A 入站**：外部 Agent 平台通过 AgentCard 发现能力，走 JSON-RPC 调 MOGO。仅 `a2a_exposed` 标记的能力资产生成 AgentCard。需网关放行 `/internal/a2a/`。

### 1.6.3 沉淀为 Skill

把高频业务流程打包成 Skill（ZIP 安装）。这是把"一次性集成"变成"长期资产"的关键。

---

## 1.7 落地路线

### 阶段 0：决策（半天）
1. 确认关系类型。2. 确认部署形态。3. 确认认证策略。

### 阶段 1：打通最小闭环（1–2 天）
- [ ] 现有网关增加 MOGO 的反代规则（HTTPS 上游 + `Upgrade`/`Connection`/`X-Session-Id` 透传 + `proxy_buffering off`）。
- [ ] 配置服务令牌（**新式签名凭证优先**，见 3.3），跑通一次 `/api/` 调用。
- [ ] 若前端直连：**配 `CORS_ORIGINS`**（不能用 `*`）。
- [ ] 若需 iframe：**显式放行 `frame-ancestors`**（默认 `DENY`）。

### 阶段 2：业务接入（按需）
- [ ] 用 `/api/external-tools` 注册你们系统 API。
- [ ] 用 `/api/business-index` 建业务语义索引（只读）。
- [ ] 把高频流程做成 Skill 包并安装。

### 阶段 3：生态互操作（按需）
- [ ] 网关放行 `/internal/a2a/`。
- [ ] 网关放行 `/internal/im/webhook/`。
- [ ] 用 018 能力资产注册 + `a2a_exposed` 控制暴露范围。

---

# 第 2 部分 · 业务系统场景（接口级）

## 2.1 两条链路

| 链路 | 方向 | 阻塞点 |
| --- | --- | --- |
| 链路一 | 业务系统 → MOGO（调 Agent 干活） | **对话入口只认终端用户 token，不认服务令牌** |
| 链路二 | MOGO → 业务系统（查数据 / 调接口） | 工具注册可用服务令牌；但**业务语义索引只认用户 token** |

---

## 2.2 链路一：业务系统 → MOGO（认证三路径）

### 2.2.1 关键事实

对话/Agent 入口（`/api/chat/completions`、`/api/chat`、`/api/sessions*`、`/api/tasks/*`）**只认终端用户 Bearer**（`app/services/end_user_session.py::resolve_session_user`，校验 `end_user_sessions` 存在、`status=active`、未过期）。

> **结论**：业务系统后端**无法**仅凭服务令牌直接调用 `/api/chat/completions`。必须先选路径。

### 2.2.2 三条可选路径

#### 路径 A：业务系统侧持有用户态 token（零源码改造）

- **⚠️ v0.2.1 新增约束**：access token TTL 只有 **1h**，且会话**空闲 30min / 绝对 24h** 超时。业务系统必须实现**刷新或重登**，不能假设 token 长期有效。
- 优点：零源码改造；治理链全部生效。
- 缺点：token 生命周期管理（现在更频繁）；每个用户需在 MOGO 有账号。
- 适用：PoC、用户量小。

#### 路径 B：给对话入口加服务主体通道（最小源码改造，**推荐**）

- **前提已变化**：v0.2.1 里服务身份校验**已经实现**（`app/security/gatekeeper.py`），W1 不再需要从零造轮子，只需**扩展 + 接线**（详见第 3 部分 W1 与第 4 部分）。
- 优点：业务系统只持一个服务令牌；执行身份可追溯；治理链保持生效。
- 适用：生产集成。

#### 路径 C：走 A2A 入站（生态化）

- 前置：`/internal/a2a/` **不在默认网关路由表内**，必须新增 `location`。
- 适用：业务系统本身是"Agent 平台/编排器"。

### 2.2.3 请求 / 响应契约

**请求**：`POST /api/chat/completions`

```jsonc
{
  "messages": [
    { "role": "user", "content": "帮我汇总本月华东区延期订单，并按客户分组" }
  ],
  "modelId": "可选：指定模型实例",
  "output_spec": {
    "task_id": "biz-order-2026-10"     // 复用同一会话；也接受 session_id
  },
  "knowledgeQaEnabled": false,
  "knowledgeBaseIds": ["kb_xxx"],
  "timezone": "Asia/Shanghai"
}
```

- `messages` 每条可带 `images` / `documents`（附件对象）。
- 服务端只取**最后一条 `role=user`** 的消息；内容为空 `400`。

**响应**：`text/event-stream`（SSE），关键响应头：

| 响应头 | 含义 |
| --- | --- |
| `X-Session-Id` | 会话 ID（= `output_spec.task_id`，用于续聊） |
| `X-Message-Id` | 本轮消息 ID |
| `X-Execution-Protocol` | `3` |
| `X-Agent-Kernel` | `dsh` |

**错误码**：

| HTTP | 场景 | 处理建议 |
| :-: | --- | --- |
| 400 | 消息为空 / 参数非法 / 技能不可用 | 不重试 |
| 401 | token 无效 / **过期（TTL 1h）** / **会话空闲超时（30min）** | **重新登录**（路径 A 需实现） |
| 402 | 配额不足 | 不重试 |
| 403 | 岗位能力被拒 / 技能准入被拒 | 不重试 |
| 404 | 会话或模型不存在 | 不重试 |
| 409 | 同一会话并发（`session_already_running`） | **串行化**该会话请求 |
| 503 | DSH runtime 不可用（`retryable: true`） | **可重试**，指数退避 |

> `409` 是很实际的坑：同一个 `task_id` 同时发两个请求会被拒。BFF 必须对同一会话加互斥。

### 2.2.4 调用示例

```bash
# 登录换 token（路径 A；注意 token 只有 1h）
curl -sS -X POST 'https://mogo.内网/api/auth/login' \
  -H 'Content-Type: application/json' \
  -d '{"username":"zhangsan","password":"***","tenantId":"acme"}'

# 发起一轮对话并接流
curl -N -X POST 'https://mogo.内网/api/chat/completions' \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"messages":[{"role":"user","content":"汇总本月华东区延期订单"}],
       "output_spec":{"task_id":"biz-order-2026-10"}}'
```

```js
const res = await fetch(`${MOGO}/api/chat/completions`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
  body: JSON.stringify({ messages: [{ role: 'user', content: text }],
                         output_spec: { task_id: conversationId } }),
});
const sessionId = res.headers.get('x-session-id');
for await (const chunk of res.body) { /* 解析 SSE */ }
```

---

## 2.3 链路二：MOGO → 业务系统

### 2.3.1 方式一：注册 HTTP 工具

- 端点：`POST /api/external-tools/my?userId=<uid>&tenantId=<tid>`
- 认证：**服务令牌可用**（新式签名凭证需带对应 scope；见 1.2.3）
- 前置：目标 userId 的岗位策略 `tool_access_mode` 必须为 `all`（默认 `selected`）。

```jsonc
{
  "name": "order_query",
  "type": "http",
  "description": "按订单号查询订单详情（含状态、金额、交期）",
  "usageHint": "当用户提到具体订单号时调用",
  "status": "enabled",                       // 默认 disabled，必须显式置 enabled
  "config": {
    "url": "https://biz.内网/api/orders/{order_no}",
    "method": "GET",
    "headers": { "X-Internal-Call": "mogo" },
    "authType": "bearer",                     // none | bearer | api_key
    "authToken": "<业务系统颁发的只读令牌>"
  }
}
```

要点：`type` 支持 `http` / `mcp`（MCP 需 `plugin_gateway` + `gatewayUrl`）；URL 支持 `{param}` 占位符；**给 MOGO 的令牌请最小权限**；建好可先 `POST /api/external-tools/my/{tool_id}/test` 自测。

### 2.3.2 方式二：业务语义索引

- 端点组：`/api/business-index/index`、`/search`、`/align`
- **重要约束**：走 `require_end_user_principal`，**只接受终端用户 token，不接受服务令牌**。
- **只读设计**：MOGO **绝不回写**业务系统数据库。
- 实体白名单（`app/business_index/entities.py` 的 `ENTITY_TYPES`）：`customer`（`customer_code`）/ `order`（`order_no`）/ `supplier`（`supplier_code`）/ `account`（`account_period`）。
- **PII 自动脱敏**：索引前对 `phone` / `id_card` / `mobile` / `email` 掩码。

### 2.3.3 方式三：沉淀为 Skill

把固定流程打包成 Skill（ZIP 安装），让 Agent 稳定复用。

---

## 2.4 BFF 设计

| 职责 | 说明 |
| --- | --- |
| 认证收敛 | 路径 A 管 token 生命周期（**1h TTL + 30min 空闲**）；路径 B 只持服务令牌 + 注入 `userId` |
| SSE 转译 | SSE → WebSocket / 轮询 / 分片 |
| 会话互斥 | 按 `task_id` 加锁，避免 `409` |
| 错误归一 | 402/403/409/503 映射成业务系统错误码；**401 触发重登** |
| 租户固定 | 统一注入 `tenantId` |
| 幂等重试 | 仅对 `503 retryable` 退避重试 |
| 可观测 | 记录 `X-Session-Id` / `X-Message-Id` |

**红线**：**不要伪造 `userId`/`tenantId`**。

---

# 第 3 部分 · 实施方案（已确认决策）

## 3.1 决策回填

| # | 决策项 | 结论 |
| :-: | --- | --- |
| 1 | 业务系统是"用户在里面用 AI"还是"AI 自动处理业务事件" | **两者都有** |
| 2 | 能否接受对 MOGO 做源码改造 | **能 → 走路径 B** |
| 3 | 同域还是分域 | **同域路径前缀**（即使不同域也走 nginx 反代） |
| 4 | 业务系统是否允许 MOGO 直连其 API/数据库 | **允许** |

## 3.2 目标架构

```
                        ┌──────────────── BFF ────────────────┐
业务系统前端 ──HTTP──▶  │ 认证收敛 / SSE 转译 / 会话互斥       │
                        │ 错误归一 / 幂等重试 / 401 重登        │
                        └───────────────┬─────────────────────┘
                                        │  X-MOGO-Service-Token（签名凭证）
业务系统事件源 ──异步触发────────────────┤
                                        ▼
                          ┌──────────────────────────────┐
                          │  MOGO 网关 :443（TLS 默认）   │
                          │  /api/chat/completions  ◀── W1
                          │  /api/external-tools/*       │
                          │  /api/business-index/*       │
                          └──────────┬───────────────────┘
                                     ▼
                          业务系统 API / 只读数据（W3）
```

---

## 3.3 W1（核心）：对话入口的服务主体通道（v2 修订）

### 3.3.1 前提已变：不要从零造轮子

**v1 的设计前提作废。** v0.2.1 里 022 已经把服务身份校验做完并接线：

| 已有能力 | 位置 | 状态 |
| --- | --- | --- |
| 签名令牌（TTL ≤24h、轮换） | `app/security/service_token.py` | ✅ 已落地 |
| 三重绑定校验（service_id / tenant_id / user_id） | `app/security/gatekeeper.py::verify_service_call` | ✅ 已落地 |
| scope 最小权限 | `ServiceTokenClaim.scope` + `GATEKEEPER_ENDPOINT_SCOPES` | ✅ 已落地 |
| 接收端接线 | `chat-api/app/api/principal.py`（`require_api_principal`） | ✅ 已接线，但**只认 `admin-api`** |

### 3.3.2 W1 修订后的净增量（4 项）

| # | 增量 | 具体做法 |
| :-: | --- | --- |
| 1 | **接受的调用方服务身份从单值扩展为可配置列表** | `principal.py` 的 `EXPECTED_CALLER_SERVICE_ID = "admin-api"` 硬编码 → 改为可配置（如 `MOGO_CHAT_API_ACCEPTED_SERVICE_IDS=admin-api,biz-erp`） |
| 2 | **让服务主体携带 `user_id`** | `verify_service_call` 已支持核对 `claim.extra["user_id"]`，但 claim 分支返回的 `ApiPrincipal(kind="admin_service", tenant_id=...)` **丢弃了 user_id** → 需回填，并考虑把 `kind` 扩展为 `"service"` 以便审计区分 |
| 3 | **把校验接到对话入口** | `/api/chat/completions` 不走 `require_api_principal`；`dsh_chat.py::_identity()`（第 149 行）仍只认用户会话 → 增加服务令牌分支 |
| 4 | **为业务系统定义并登记 scope** | 例如 `chat.invoke`，加进 scope 注册表（当前只登记了 `/api/v1/models`、`/api/v1/skills`、`/api/v1/external-tools`） |

### 3.3.3 改动点清单

| 序 | 文件 | 改动 |
| :-: | --- | --- |
| 1 | `services/chat-api/app/api/principal.py` | `EXPECTED_CALLER_SERVICE_ID` 单值 → 可配置列表；claim 分支回填 `user_id` |
| 2 | `services/chat-api/app/api/endpoints/dsh_chat.py` | `_identity()` 增加服务令牌分支（**可选关键字参数**，默认空 → 既有 14 处调用点行为不变）；`/chat/completions` 与 `/chat` 透传 header/query |
| 3 | `services/chat-api/app/core/config.py` | 新增开关 `CHAT_SERVICE_PRINCIPAL_ENABLED: bool = False` + 接受的调用方身份列表 |
| 4 | scope 注册表 | 新增 `chat.invoke` |
| 5 | 测试 | 见 3.3.5 |

### 3.3.4 设计草案（伪代码，复用既有能力）

```python
# app/api/principal.py —— 增量 1 + 2
ACCEPTED_CALLER_SERVICE_IDS = _parse_csv(
    settings.CHAT_API_ACCEPTED_SERVICE_IDS or "admin-api"
)

async def require_api_principal(request, authorization=None,
                                service_token=Header(default="", alias="X-MOGO-Service-Token")):
    tenant_hint = _query(request, "tenantId", "tenant_id")
    user_hint = _query(request, "userId", "user_id")
    issuer = _incoming_service_issuer()

    # 先验签一次拿 claim，再比对身份（避免循环里反复验签）
    claim = _verify_once(service_token, issuer)          # 签名/有效期失败即 401
    if claim is not None:
        if claim.service_id not in ACCEPTED_CALLER_SERVICE_IDS:   # ← 增量 1
            raise HTTPException(401, "service_identity_not_accepted")
        _assert_bindings(claim, tenant_hint, user_hint)           # 复用三重绑定
        return ApiPrincipal(
            kind="service",                                        # ← 增量 2
            tenant_id=resolve_tenant_id(str(claim.tenant_id or tenant_hint)),
            user_id=str(claim.extra.get("user_id") or ""),         # ← 增量 2
            service_id=claim.service_id,
        )
    # ... 回退静态密钥 → 回退用户会话（不变）
```

> **实现提醒**：`verify_service_call` 在 `service_id` 不匹配时**直接抛 `GatekeeperDenied`**。多身份场景应**先验签拿 claim，再比对 `service_id`**，而不是循环里反复调用验签——否则"身份不在白名单"会被误报成"签名无效"。

### 3.3.5 测试与门禁

| 类型 | 用例 |
| --- | --- |
| 正向 | 业务系统令牌 + 合法 userId → 流式返回 |
| 负向 | 缺 userId → 400；跨租户 → 403；身份不在白名单 → 401；scope 不足 → 401；签名篡改 → 401；过期 → 401 |
| 回归 | 终端用户 Bearer 路径**完全不变**；`admin-api` 既有调用**不变** |
| 门禁 | `check_production_wiring.py`、`check_module_coverage.py` |

### 3.3.6 回滚设计

开关 `CHAT_SERVICE_PRINCIPAL_ENABLED` **默认 `false`**；关闭时行为与现状一致。另：新式凭据未配置时 `build_issuer_from_env()` 返回 `None` → **自动回退静态密钥**（022 已实现的灰度通道，可直接复用）。

### 3.3.7 签发端待定（新增问题）

业务系统要发令牌，但 `build_issuer_from_env()` 是**接收端**用的。需要决定**谁给业务系统签发令牌**：
- 方案 a：MOGO 提供签发工具/内部端点（业务系统按需取）；
- 方案 b：双方共享密钥，业务系统自己用 `ServiceTokenIssuer` 签发（需把接口文档化给业务系统）；
- 方案 c：先用静态密钥（回退通道）跑通，再升级到签名令牌。

---

## 3.4 W2：事件入站

### 3.4.1 路径 A：业务系统直接异步调用链路一（推荐）

```
业务系统事件 ──▶ BFF 异步任务 ──▶ POST /api/chat/completions
                                 （服务令牌 + userId=事件归属人）
```

- 优点：复用 W1，无需新网关放行、无需新签名体系。
- 代价：业务系统自维护"事件 → 会话"映射（用 `output_spec.task_id`）。

### 3.4.2 路径 B：走 IM webhook 范式（需放行）

`POST /internal/im/webhook/{channel}`，HMAC 签名 + 时间戳 + nonce 防重放 + 会话绑定 + 统一审计。**前置**：网关新增 `location` 并加网络层防护。

### 3.4.3 选择建议

| 情况 | 走 |
| --- | --- |
| 事件类型少、只需触发 Agent | 路径 A |
| 需要多渠道统一入口 + 签名验真 + 会话治理 | 路径 B |

---

## 3.5 W3：MOGO → 业务系统

### 3.5.1 HTTP 工具（推荐主用）

| 工具 | URL 形态 | 用途 |
| --- | --- | --- |
| `order_query` | `GET /api/orders/{order_no}` | 订单详情 |
| `order_list_delayed` | `GET /api/orders?status=delayed&region={region}` | 延期订单列表 |
| `customer_profile` | `GET /api/customers/{customer_code}` | 客户档案 |
| `ticket_create` | `POST /api/tickets` | 建工单（**写操作，需审批**） |

### 3.5.2 业务语义索引（跨系统关联查询）

见 2.3.2。建议：**先跑 HTTP 工具，确认覆盖不了跨系统关联查询再上语义索引**。

---

## 3.6 W4：BFF

见 2.4。

---

## 3.7 W5：网关与部署

### 3.7.1 同域路径前缀（已选定，注意上游是 HTTPS）

见 1.5.1 的 nginx 片段（**`proxy_pass https://...`**；上游为自签证书时需 `proxy_ssl_verify off;` 或信任 CA）。

### 3.7.2 iframe 放行（**v0.2.1 必需**）

默认 `X-Frame-Options: DENY`，需在你们侧或 MOGO 侧显式改为 CSP `frame-ancestors`。

### 3.7.3 若采用 W2 路径 B（IM webhook）

```nginx
location /internal/im/ {
    proxy_pass https://mogo-gateway:443;
    allow 10.0.0.0/8; deny all;      # 仅允许业务系统来源
}
```

### 3.7.4 回退到 HTTP（仅本地/内网调试）

`MOGO_NGINX_CONF=./deploy/docker/nginx.conf`。

---

## 3.8 排期与验收

| 阶段 | 工作项 | 验收标准 |
| --- | --- | --- |
| 1 | W1 服务主体通道（4 项增量） | 业务系统令牌跑通流式问答；`admin-api` 与终端用户路径回归全绿 |
| 1 | W4 BFF 骨架 | 前端拿到流式输出；同会话并发不再 409；401 能自动重登 |
| 2 | W5 网关 | 同域可访问；流式不断流；会话不漂移；iframe 可嵌入 |
| 2 | W3 HTTP 工具 | Agent 能正确调用订单/客户查询 |
| 3 | W2 事件入站 | 业务事件自动触发 Agent 并回写结果 |

## 3.9 风险与回滚

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| W1 触碰认证路径 | 影响面大 | 开关默认关闭 + 022 已有的静态密钥回退通道 |
| 服务令牌泄漏 | 可代表租户内用户调用 | 短 TTL（≤24h）+ 轮换 + **scope 最小权限**（022 已实现）+ 来源限制 + 审计 |
| 写操作工具放开 | 误操作业务系统 | 写类工具配 R3/R4 + 审批，只给只读令牌做查询 |
| 前置代理吃头 | 流式退化 / 会话漂移 | 逐层透传 `Upgrade`/`Connection`/`X-Session-Id`；逐层 `proxy_buffering off` |
| 容器只读根 | 自定义挂载/写文件失败 | 按 022 T027 的 tmpfs 模式 |
| 许可证 | 商用受限 | 不得做多租户托管 SaaS、不得改删前端标识 |

---

# 第 4 部分 · 022 安全加固对齐（已完成态）

> 依据：`specs/022-security-hardening/`（spec / plan / tasks）+ 实际提交。

## 4.1 状态：全部完成

| 项 | 状态 |
| --- | --- |
| 任务完成度 | **58 / 58**（`tasks.md` 无未勾选项） |
| Phase | 0–7 **全部已提交**（`c03d5f5` … `b6a7c65`） |
| 是否在 v0.2.1 内 | **是**（`git merge-base --is-ancestor b6a7c65 v0.2.1` 为真） |
| CHANGELOG 记录 | ⚠️ **v0.2.1 段几乎未提 022**（仅在 Fixed 里提了一句 dsh-runtime-host 加固）；022 的内容以 `specs/022-*` 与 README 的规格清单为准 |

## 4.2 与集成直接相关的交付物（v0.2.1 实测）

| 编号 | 交付 | 位置 | 对集成的影响 |
| --- | --- | --- | --- |
| QF-558 / T019 | 服务间独立凭证（签名令牌、TTL ≤24h、轮换） | `app/security/service_token.py`（双服务） | 服务令牌从静态密钥升级为签名令牌 |
| QF-561 / T020 | 服务身份**三重绑定**（service_id + tenant_id + user_id） | `app/security/gatekeeper.py`（双服务）+ `principal.py` 接线 | **W1 可复用**；但只认 `admin-api` |
| T028 | 服务身份**权限最小化**（`scope`） | `ServiceTokenClaim.scope` + `GATEKEEPER_ENDPOINT_SCOPES` | 业务系统令牌需带 scope |
| QF-532 / T014·T015 | access token TTL ≤ 1h | `END_USER_AUTH_TOKEN_TTL_SECONDS` | **路径 A 必须刷新** |
| QF-535 / T017·T018 | 空闲 30min / 绝对 24h 超时 | `app/security/session_timeout.py` | 长静默集成会话会被 401 |
| QF-634 / T030·T031 | SSO 令牌改 POST 换票、TTL 60s、accept-once | `POST /api/auth/sso/exchange` | SSO 集成方式改变 |
| QF-637 / T032 | GET 无副作用（4 处拆分） | 见 1.2.5 | 调用方需改用 POST 端点 |
| QF-640 / T033·T034 | CORS 白名单，拒绝通配符 | `app/middleware/cors.py`（双服务） | **必须配 `CORS_ORIGINS`** |
| QF-645 / T036·T037 | TLS 强制（443 + 301 + TLS≥1.2） | `deploy/nginx/nginx.conf`（**默认**） | 反代上游改 HTTPS；`X-Frame-Options: DENY` |
| QF-575 / T023–T027 | 容器非 root + 只读根 + `cap_drop ALL` | 7 个服务 | 自定义挂载/写文件需注意 |
| T042 | 生产 `debug=False` + 不回显堆栈 | 双服务 `main.py` | 排障需看服务端日志 |
| T044 | 审计保留期 ≥180 天 + 审计库分离 | `MONGODB_AUDIT_DB` | 生产建议显式配置 |

## 4.3 对 v1 结论的更正（重要）

v1 的第 4 部分判定「机制 B 当前**零生产引用**」——**该结论错误**。原因是当时的检索被结果条数上限截断，只看到测试文件命中就下了结论。

**实际状态**：`app/security/gatekeeper.py` 与 `service_token.py` 已被 `chat-api/app/api/principal.py`、`app/services/gatekeeper_client.py`、admin-api 的多个路由（`gatekeeper_internal` / `skills` / `tools` / `capability_assets` / `skill_canary` / `knowledge_documents` / `personal_knowledge_internal` / `skill_monitoring`）、`admin-api/app/core/internal_service_auth.py`、`document-parser` 多个路由等**广泛消费**。

> **教训**：检索结论必须覆盖全量结果，不能凭截断结果下"零引用"这类强判断。

## 4.4 仍然有效的提醒：文档路径与实现不一致

`tasks.md` / `plan.md` 里仍有几处路径与实际落点不符（**实施者实际已找到正确落点，但文档没回写**）：

| 文档写的 | 实际 | 状态 |
| --- | --- | --- |
| `services/chat-api/app/deps.py` | **不存在** → 实际落在 `app/api/principal.py` | 仍不符 |
| `services/admin-api/app/deps.py` | **不存在** → 实际是 `app/api/deps.py` | 仍不符 |
| `services/chat-api/app/api/routes/auth.py` | **不存在** → 实际是 `app/api/endpoints/auth.py` | 仍不符 |
| `services/chat-api/app/middleware/` | **已存在**（Phase 4 新建，含 `cors.py`） | ✅ 已解决 |
| plan.md 的「新增集合 `service_tokens`」 | 实现为**无状态**签名令牌，无该集合 | 仍不符（**不要建这个集合**） |

建议：把这几处回写进 `tasks.md`，避免后续会话按错路径找文件。

## 4.5 W1 与 022 的边界（修订）

| 能力 | 022 覆盖 | W1 需要 | 归属 |
| --- | :-: | :-: | --- |
| 签名令牌签发/校验（TTL、轮换） | ✅ | 复用 | 022 |
| 三重绑定（service_id / tenant_id / user_id） | ✅ | 复用 | 022 |
| scope 最小权限 | ✅ | 复用 | 022 |
| 接受的调用方身份**可配置多值** | ✗（硬编码 `admin-api`） | **需要** | **W1** |
| 服务主体**携带 user_id** | ✗（claim 分支丢弃） | **需要** | **W1** |
| 校验**接到对话入口** | ✗ | **需要** | **W1** |
| 为业务系统**登记 scope** | ✗ | **需要** | **W1** |

**结论**：W1 的净增量 = 上表最后 4 行，**全部是"扩展 + 接线"，不含从零实现**。

---

# 第 5 部分 · 本体清单与本体数据权限

> **已确认决策**：①「本体」= 业务主数据实体；②三表共用是目标态；③权限判定为纯用户级授权；④本体实际数据由业务系统提供、MOGO 清单只做展示；⑤Agent 执行时按 userId 从权限表取当前用户的本体清单。
>
> **与 022/v0.2.1 的关系**：本部分设计**尚未实现**；其 5.8 的内部接口依赖 022 的服务身份机制，而该机制**现已可用**（见第 4 部分），**落地障碍已消除**。

## 5.1 一句话方案

- **本体清单（只读展示）**：本体定义与数据都在业务系统；MOGO 侧只保存只读副本（或运行时取），`admin-web` 的「本体清单」页只做展示。
- **本体数据权限（唯一判定源）**：新建 `user_ontology_permissions`（用户↔本体），**纯用户级、fail-closed**。
- **运行时解析**：Agent 执行时按 `userId` 查该表 → 可见本体清单 → 用于检索与工具调用的数据权限过滤。
- **三表共用**：业务系统为权威源，MOGO **只读主表**；MOGO 专有字段迁到 MOGO 侧扩展表。

## 5.2 现状核对

### 5.2.1 三张表实际是四个集合

| 业务概念 | 集合 | 关键字段 | 代码位置 |
| --- | --- | --- | --- |
| 用户 | `end_users` | `tenant_id` / `login_name` / `email` / `mobile` / `name` / `status` / `primary_org_id` / `password_hash` / `password_salt` / `avatar_object_path` / `last_login_at` | `chat-api/app/api/endpoints/auth.py`（`USER_COLLECTION`） |
| 租户 | `tenants` | `tenant_id` / `status` | 同上 |
| 组织（租户侧） | `organizations` | `tenant_id` / `org_name` / `owner_user_id` | `app/core/billing.py::get_or_create_organization` |
| 组织机构（部门树） | `org_units` | `tenant_id` / `name` / `code` / `parent_id` / `path_ids` / `path_names` / `status` | `chat-api/app/api/endpoints/auth.py`（`DEPARTMENT_COLLECTION`） |

### 5.2.2 ⚠️ MOGO 目前**会写**这三张表（共用方案的前置阻塞点）

| 写入点 | 集合 | 代码位置 |
| --- | --- | --- |
| 自助注册建用户 + 写口令哈希/盐 | `end_users` | `auth.py::register` |
| 更新 `last_login_at` | `end_users` | `auth.py::_create_session` |
| 更新头像（URL + OSS 路径） | `end_users` | `auth.py::upload_profile_avatar` |
| 改姓名（同步写后台账号） | `end_users` + `admin_accounts` | `auth.py::update_profile` |
| 分配主部门 `primary_org_id` | `end_users` + `end_user_org_relations` | `auth.py::_assign_user_primary_department` |
| **自动创建根部门「企业总部」** | `org_units` | `auth.py::_ensure_root_department` |
| **自动创建组织** | `organizations` | `core/billing.py::get_or_create_organization` |

> **v0.2.1 补充**：T032 已把 `GET /organizations/billing` 的惰性建库拆到 `POST /organizations/billing/init` —— 但**自动创建逻辑本身仍在**，共用改造时仍需处理。

### 5.2.3 可复用的既有权限模式（锚点）

`apps/admin-web/src/views/organizations/EmployeeCapabilityOverrideDialog.vue` 的"岗位角色基线 + 临时能力覆盖（有原因、有失效时间）"，配套 API 在 `src/api/positionRoles.ts`。新的「本体数据权限」沿用同一交互风格，但按决策是**纯用户级、长期有效**。

### 5.2.4 接口与菜单的注册约定

| 项 | 约定 |
| --- | --- |
| 前端 baseURL | `apps/admin-web/src/api/client.ts`：`/admin-api` |
| 前端调用写法 | `apiClient.get('/api/position-roles')` |
| 对外实际路径 | `/admin-api/api/<prefix>/...`（网关剥离 `/admin-api/`；`admin-api/app/main.py:146` `include_router(api_router, prefix="/api")`） |
| 后端注册 | `services/admin-api/app/api/router.py`：`api_router.include_router(X.router, prefix="/xxx")` |
| 菜单注册 | `apps/admin-web/src/router/routes.ts` 的 `BasicLayout` children，`meta:{ title, icon }` + `src/icons/*.tsx` |

### 5.2.5 顺带发现：本体类型定义两处不一致

| 位置 | 取值 |
| --- | --- |
| `chat-api/app/services/business_semantic_index.py` | `("customer", "order", "product", "document", "ticket")` |
| `chat-api/app/business_index/entities.py` | `("customer", "order", "supplier", "account")` |

引入"本体"前需先统一口径。

---

## 5.3 设计一：三表共用（目标态）

### 5.3.1 主表共享（业务系统为权威源）+ MOGO 侧扩展表

```
        业务系统（权威源 / SoR）              MOGO（只读主表 + 自持扩展）
   ┌──────────────────────────────┐   ┌──────────────────────────────┐
   │  end_users（主数据）          │   │  mogo_user_identity_ext       │
   │  tenants / organizations      │◀──│   password_hash / mfa_secret  │
   │  org_units（部门树）           │只读│   avatar / last_login_at      │
   └──────────────────────────────┘   │   primary_org_id              │
                                       └──────────────────────────────┘
```

**字段归属拆分**：

| 字段 | 归属 |
| --- | --- |
| `login_name` / `email` / `mobile` / `name` / `status` | **业务系统主表** |
| `tenant_id` / `org_name` | **业务系统主表** |
| `org_units` 全树 | **业务系统主表** |
| `password_hash` / `password_salt` / `mfa_secret` | **MOGO 扩展表** |
| `avatar` / `avatar_object_path` | **MOGO 扩展表** |
| `last_login_at` / `last_seen_at` | **MOGO 扩展表** |
| `primary_org_id` | **MOGO 扩展表** |

新集合建议名：**`mogo_user_identity_ext`**，唯一键 `(tenant_id, user_id)`。

### 5.3.2 三种共用实现方式对比

| 方式 | 做法 | 优点 | 缺点 | 建议 |
| --- | --- | --- | --- | --- |
| **A. 同库直连** | 同一 MongoDB；MOGO 只读主表、写扩展表 | 最简单、无延迟 | 要求同库；schema 强耦合 | **首期推荐** |
| B. 跨库只读副本 | 定时/CDC 同步 | 解耦、可跨机房 | 有延迟；需处理删除 | 中期可选 |
| C. API 按需查询 | 业务系统提供 API + 缓存 | 最解耦 | 改动最大；登录链路引入外部依赖 | 长期演进 |

### 5.3.3 需要改造的 MOGO 写点

| 原行为 | 改造后 |
| --- | --- |
| `register` 写 `end_users` | **关闭自助注册**，或改调业务系统建号 API 后回写扩展表 |
| 写 `password_hash` / `password_salt` | 改写入 `mogo_user_identity_ext` |
| 更新 `last_login_at` | 改写入扩展表 |
| 更新头像 | 改写入扩展表 |
| `_ensure_root_department` 自动建根部门 | **移除** |
| `get_or_create_organization` 自动建组织 | **移除或改为只读** |

> 破坏性改造，需迁移脚本 + 回滚预案 + 停机窗口。

---

## 5.4 设计二：本体清单（只读展示）

- **本体定义与数据都在业务系统**：MOGO 不维护本体 CRUD，也不存本体实例数据。
- MOGO 侧的「本体清单」功能点**只做展示**。

**清单元数据获取**：① **同步只读副本**（推荐，业务系统提供清单接口/表 → 同步到 MOGO）；② 运行时实时取。

**只读副本集合（建议名 `ontologies`）**：

```jsonc
{
  "tenant_id": "acme",
  "ontology_id": "material",        // ★ 用业务系统的本体标识，避免额外映射表
  "name": "物料",
  "description": "原材料与半成品主数据",
  "source_system": "erp",
  "source_entity": "md_material",
  "key_field": "material_code",
  "synced_at": "…"
}
```

> **关键点**：`ontology_id` 直接用**业务系统的本体标识**，权限表与业务系统天然对齐。

---

## 5.5 设计三：用户本体数据权限（`user_ontology_permissions`）

**这是权限判定的唯一数据源。**

```jsonc
{
  "tenant_id": "acme",
  "user_id": "…",                 // end_users._id
  "ontology_id": "material",      // 业务系统本体标识
  "effect": "allow",              // 首期只有 allow；预留 deny
  "granted_by": "…",
  "granted_at": "…",
  "reason": "生产计划岗需要看物料主数据",
  "expires_at": null              // null = 长期有效
}
```

索引：`(tenant_id, user_id, ontology_id)` 唯一；`(tenant_id, user_id, effect)` 查询用。

**判定（fail-closed）**：

```text
visible_ontology_ids(tenant_id, user_id)
  = SELECT ontology_id FROM user_ontology_permissions
    WHERE tenant_id = :t AND user_id = :u AND effect = 'allow'
      AND (expires_at IS NULL OR expires_at > now)
```

- **默认不可见**，显式 `allow` 才可见。
- 按决策**不接岗位角色**。
- 纯用户级 → **批量授权**很实际，建议首期就提供批量接口。

---

## 5.6 设计四：运行时权限解析（核心）

### 5.6.1 新增解析服务（chat-api）

建议新增 `services/chat-api/app/services/ontology_permission.py`：

```python
async def visible_ontology_ids(tenant_id: str, user_id: str) -> frozenset[str]:
    """按 userId 取可见本体清单；fail-closed：查询失败返回空集。"""

async def ontology_scope_snapshot(tenant_id: str, user_id: str) -> dict:
    """给审计/上下文用的快照。"""
```

- **fail-closed**：DB 异常、空 userId 一律返回**空集**。
- **缓存**：进程内短 TTL（如 60s），授权变更后按 `(tenant_id, user_id)` 失效。
- **审计**：每次解析落一条事件，便于与业务系统对账。

### 5.6.2 生效点

| 生效点 | 位置 | 改造 |
| --- | --- | --- |
| **业务语义索引检索** | `business_semantic_index.py::semantic_search(query, *, tenant_id, user_id, ...)`（**已接收 `user_id`**） | 按可见本体过滤 |
| **外部工具调用** | `app/api/endpoints/external_tools.py` + 工具注册 | 工具关联本体标识，调用前校验 |
| **Agent 轮次上下文** | `dsh_chat.py::_start_chat_completions` | 可选：注入可见本体清单 |
| **业务系统侧过滤** | 业务系统 | 通过 5.8 的内部接口拉取 |

---

## 5.7 接口设计（`services/admin-api/app/api/routes/ontologies.py`）

注册：`api_router.include_router(ontologies.router, prefix="/ontologies", tags=["ontologies"])`

> 「本体清单」只做展示，**不提供本体 CRUD**。

| 方法 | 对外路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| **GET** | **`/admin-api/api/ontologies/mine`** | **当前账号可见的本体清单（展示用）** | 登录即可 |
| GET | `/admin-api/api/ontologies` | 全量清单（授权时勾选） | `ontology:list` |
| POST | `/admin-api/api/ontologies/sync` | 从业务系统同步只读副本 | `ontology:sync` |
| GET | `/admin-api/api/ontologies/users/{user_id}/permissions` | 查某用户权限 | `ontology:grant` |
| POST | `/admin-api/api/ontologies/users/{user_id}/permissions` | 批量授予 | `ontology:grant` |
| DELETE | `/admin-api/api/ontologies/users/{user_id}/permissions/{ontology_id}` | 撤销 | `ontology:grant` |

---

## 5.8 与业务系统的对接接口

```text
GET /admin-api/api/internal/ontology-permissions?tenantId=<t>&userId=<u>
→ { "ontologies": [ { "ontologyId": "material", "sourceEntity": "md_material", "keyField": "material_code" } ] }
```

要点：
- **走服务凭证鉴权** —— 022 的服务身份机制**现已可用**（见第 4 部分），落地障碍已消除。
- `/internal/...` **默认不在网关路由表内**，需显式加 `location` 并限制来源网段。
- 闭环：**MOGO 侧授权 → 业务系统侧过滤**。

---

## 5.9 前端设计（`apps/admin-web`）

| 项 | 文件 | 说明 |
| --- | --- | --- |
| 菜单 + 路由 | `src/router/routes.ts` | `BasicLayout` children 加 `/ontologies` → `OntologyCatalogPage.vue`，`meta:{ title:'本体清单', icon: OntologyIcon }` |
| 图标 | `src/icons/OntologyIcon.tsx` | 照 `PositionRolesIcon` 新增 |
| **清单页（只读）** | `src/views/ontologies/OntologyCatalogPage.vue` | 只读展示 `/ontologies/mine` |
| 授权弹窗 | `src/views/ontologies/UserOntologyPermissionDialog.vue` | 照 `EmployeeCapabilityOverrideDialog.vue` 写 |
| 用户入口 | `src/views/organizations/OrganizationUsersPage.vue` | 用户行加「本体数据权限」按钮 |
| API 层 | `src/api/ontologies.ts` | 照 `src/api/positionRoles.ts` 写 |

---

## 5.10 落地阶段

| 阶段 | 内容 | 依赖 |
| --- | --- | --- |
| **1** | 权限表 + 运行时解析 + 展示页 + 授权（**不碰三表**） | 无（022 已解除服务身份依赖） |
| **2** | 三表共用改造 + 迁移脚本 + 移除自动建组织/部门 | 阶段 1；需停机窗口 |
| **3** | 业务系统对接：内部权限接口 + 业务系统侧过滤 | 阶段 1；复用 022 服务身份 |
| **4** | 本体清单同步 | 阶段 3 |

## 5.11 风险与开放问题

| # | 风险 / 问题 | 说明 |
| :-: | --- | --- |
| 1 | 三表共用是破坏性改造 | 需迁移脚本 + 回滚预案 + 停机窗口 |
| 2 | 自助注册与权威源冲突 | `register` 要么关闭，要么改调业务系统建号 API |
| 3 | 自动建组织/部门要移除 | 会与业务系统主数据打架 |
| 4 | 权限表由谁写入未定 | MOGO 后台授权？还是业务系统同步？ |
| 5 | 本体粒度未定 | 实体级 vs 实例级 |
| 6 | 本体类型定义两处不一致 | 见 5.2.5 |
| 7 | 权限缓存一致性 | 授权变更后需失效缓存 |
| 8 | 运行时查询是热路径 | 必须缓存；fail-closed 不能退化成"超时即放行" |
| 9 | 清单同步时机 | 业务系统新增本体后 MOGO 未同步 → 授权时看不到 |
| 10 | 内部接口暴露面 | 需显式放行 + 来源限制 + 服务凭证 |

---

# 第 6 部分 · 约束与坑（汇总）

| # | 约束 | 影响 | 应对 |
| :-: | --- | --- | --- |
| 1 | **`X-Frame-Options: DENY`**（v0.2.1 默认） | 跨域**与同源** iframe 均被拒 | 显式改 CSP `frame-ancestors` 白名单 |
| 2 | **TLS 默认启用**（443 + 301，`/healthz` 例外） | 反代上游需 `https://`；自签证书需信任 | 见 1.5.1；或 `MOGO_NGINX_CONF` 回退 HTTP |
| 3 | **CORS 白名单拒绝通配符** | 前端直连跨域必须显式配来源 | 配 `CORS_ORIGINS` |
| 4 | **access token TTL 1h + 空闲 30min 超时** | 长会话/长静默集成会被 401 | BFF 实现刷新与重登 |
| 5 | **GET 端点无副作用（T032）** | 旧调用方方法不对会失败 | 改用 1.2.5 的新 POST 端点 |
| 6 | `/internal/*` 未在网关路由表 | A2A / IM webhook / 内部权限接口不可达 | 显式新增 `location` + 来源限制 + 服务凭证 |
| 7 | `X-Session-Id` 一致性哈希 | 前置代理吃掉该头 → 会话漂移 | 逐层原样透传 |
| 8 | 作用域强校验 fail-closed | 伪造 `userId`/`tenantId` 直接 403 | 不要伪造 |
| 9 | **对话入口只认用户 token** | 服务令牌调 `/api/chat/completions` 会 401 | 走路径 A 或 B（W1） |
| 10 | **服务令牌只认 `admin-api` 身份** | 业务系统令牌直接被拒 | W1 增量 1（可配置多值） |
| 11 | `/api/business-index/*` 只认用户 token | 服务令牌批量灌数据被拒 | 用用户 token 或内部批量脚本 |
| 12 | 同一会话并发 → `409` | 前端连点会失败 | BFF 按 `task_id` 加锁 |
| 13 | `/askai-api/` 前缀剥到根路径 | 用错前缀 → 404 | 统一用 `/api/` |
| 14 | 流式被中间层缓冲 | SSE 退化成一次性返回 | 链路每层 `proxy_buffering off` |
| 15 | **容器只读根 + `cap_drop ALL`** | 自定义挂载/写文件失败 | 用 tmpfs 或卷；参考 022 T027 |
| 16 | 开源版单租户 | 一套部署 = 一个组织 | 多组织走 020 或分环境 |
| 17 | 许可证（MOVO 社区许可） | 不得运营多租户托管 SaaS、不得改删前端 logo | 商用前确认授权 |
| 18 | DSH 内核钉版 | 升级 train 属兼容性变更 | 按 README 流程走 |
| 19 | 创建工具需岗位 `tool_access_mode=all` | 默认 `selected` 会 403 | 先调岗位策略 |
| 20 | 工具 `status` 默认 `disabled` | 建了不生效 | 显式置 `enabled` |
| 21 | MOGO 会写用户/租户/组织表 | 共用时产生写入竞争与字段污染 | 字段拆分 + 扩展表（第 5 部分） |
| 22 | **审计库分离需显式配置** | 不配 `MONGODB_AUDIT_DB` 则审计与业务同库 | 生产建议显式配置 |

---

# 第 7 部分 · 选型速查

| 你的诉求 | 推荐 | 需要改造 |
| --- | --- | --- |
| 只想让 AI 帮内部员工干活，界面无所谓 | 子域名 + 直接用 MOGO 工作台 | 无 |
| 要把 AI 嵌进现有门户且不跳走 | 同域路径前缀 + iframe | **必须改 `frame-ancestors`**（默认 DENY） |
| 产品要 AI 能力，但 UI 是自己的 | 服务令牌 + BFF | 后端适配层 + `CORS_ORIGINS` |
| 业务系统后端要驱动 Agent | **路径 B（W1 四项增量）** | MOGO 源码改造（开关默认关闭） |
| 业务系统里已有用户，不想再建一套登录 | 路径 A（用户态 token） | 无，但**需实现 1h TTL 刷新** |
| 业务系统本身就是 Agent 平台 / 要接 Dify | 路径 C（A2A 入站） | 网关放行 `/internal/a2a/` |
| 要让 Agent 会查你们的业务数据 | HTTP 工具 + 业务语义索引 | 只读连接 + 工具注册 |
| 外部系统事件要驱动 Agent | W2 路径 A（复用链路一） | BFF 异步任务 |
| 需要多渠道统一事件入口 + 签名验真 | W2 路径 B（IM webhook） | 网关放行 `/internal/im/` + 签名密钥 |
| 想沉淀长期可复用的能力 | Skill 打包 | Skill 开发 |
| 用户/租户/组织机构要和业务系统共用 | 字段拆分 + `mogo_user_identity_ext` | 破坏性改造 + 迁移脚本 |
| 要按"用户能看哪些业务主数据"做权限 | 本体清单 + `user_ontology_permissions` | 见第 5 部分（阶段 1 可独立交付） |

---

# 附录 A · 事实来源核对点

| 结论 | 核对位置 |
| --- | --- |
| **TLS 网关配置（默认）** | `deploy/nginx/nginx.conf`（`X-Frame-Options: DENY`、TLS≥1.2、HSTS） |
| HTTP 侧网关配置（回退） | `deploy/docker/nginx.conf` |
| compose 的 `MOGO_NGINX_CONF` 默认值 | `docker-compose.yml:647` |
| 用户态 token 校验 + 会话超时 | `services/chat-api/app/services/end_user_session.py` |
| **服务身份三重绑定 + scope** | `services/chat-api/app/security/gatekeeper.py`、`services/admin-api/app/security/gatekeeper.py` |
| 签名令牌实现 | `app/security/service_token.py`（双服务） |
| **`EXPECTED_CALLER_SERVICE_ID` 硬编码 + scope 注册表** | `services/chat-api/app/api/principal.py` |
| CORS 白名单（拒绝通配符） | `services/{chat-api,admin-api}/app/middleware/cors.py` |
| `/api/chat/completions` 契约、SSE 头、错误码 | `app/api/endpoints/dsh_chat.py` |
| `_identity` 的 14 处调用点 | 同上（第 149 行定义） |
| 工具配置字段 | `app/services/external_tools.py`、`app/api/endpoints/external_tools.py` |
| 岗位 `tool_access_mode` 语义 | `app/governance/position_policy.py` |
| 实体类型白名单 / 对齐键 / PII 字段 | `app/business_index/entities.py` |
| 业务语义索引端点与认证方式 | `app/api/endpoints/business_index.py` |
| `semantic_search` 已接收 `user_id` | `app/services/business_semantic_index.py` |
| A2A 契约 | `contracts/a2a-gateway.md`、`app/api/endpoints/a2a.py` |
| IM webhook 签名校验 | `app/api/endpoints/im_gateway.py`、`app/im_gateway/webhook.py` |
| 路由注册与前缀 | `app/main.py`（chat-api）、`app/api/router.py` + `main.py:146`（admin-api） |
| 用户/租户/组织的读写点 | `chat-api/app/api/endpoints/auth.py`、`app/core/billing.py` |
| 022 任务与完成状态 | `specs/022-security-hardening/tasks.md`（58/58） |
| 022 提交序列 | `git log --oneline`（`c03d5f5` … `b6a7c65`） |
| v0.2.1 内容 | `CHANGELOG.md`（`## v0.2.1 - 2026-10-12`） |
| 既有权限模式 | `apps/admin-web/src/views/organizations/EmployeeCapabilityOverrideDialog.vue`、`src/api/positionRoles.ts` |
| 前端接口与菜单约定 | `apps/admin-web/src/api/client.ts`、`src/router/routes.ts` |

---

# 附录 B · 文档沿革与拆分说明

## B.1 合并来源

本文由以下 5 份文档合并而成。**原件均保留未删除**（按 `AGENTS.md`：禁止删除文件）。

| 原文档 | 内容 | 合并稿位置 |
| --- | --- | --- |
| `docs/web应用集成规划.md` | 四种模式的总体规划 | 第 1 部分 |
| `docs/业务系统集成方案.md` | 业务系统场景的接口级展开 | 第 2 部分 |
| `docs/业务系统集成-实施方案.md` | 按已确认决策落到 W1–W5 | 第 3 部分 |
| `docs/022-W1-对齐备忘.md` | 与 022 的能力边界对齐 | 第 4 部分 |
| `docs/本体清单与数据权限-设计方案.md` | 本体清单与用户级本体数据权限设计 | 第 5 部分 |

**合并时做的处理**：去重（网关配置、认证事实、约束清单在原件中重复，现各留一处）；保留所有源码核对结论、集合/字段建议、伪代码草案、阶段清单、待确认项。

## B.2 修订历史

| 版本 | 日期 | 内容 |
| --- | --- | --- |
| v1 | 2026-10-13 | 5 份文档合并为单一文档（1204 行）；新增第 6 部分（约束汇总）与第 7 部分（选型速查） |
| **v2** | **2026-10-13** | 按 **022 完成态 + v0.2.1** 刷新：更正 8 处实质结论（见文首「v2 修订说明」）；重写第 3 部分 W1 与第 4 部分；补充 TTL/CORS/GET 副作用/SSO/容器加固等变化 |
| **v2.1** | **2026-10-13** | 服务令牌头 `X-MOVO-Service-Token` → **`X-MOGO-Service-Token`**（39 处 / 21 文件：代码 + 测试 + 本文档） |

## B.3 如需拆分

第 4 部分（022 对齐）与第 5 部分（本体清单与数据权限）相对独立，可直接切出为单独文档。
