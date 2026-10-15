# Feature Specification: 为 user-web 新增 SSO 接收方（门户免二次登录进入 MOGO 用户工作台）

**Feature Branch**: `029-user-web-sso-receiver`

**Created**: 2026-10-15

**Status**: Draft

**Input**: User description: "为 user-web 新增 SSO 接收方：门户以服务身份签发票据，user-web 换票建会话，实现外部门户免二次登录进入 MOGO 用户工作台"

> **设计来源**：本规约是对 `docs/MOGO-Web应用集成方案.md` §1.3.2「单点登录打通（免二次登录）→ 详细设计：为 user-web 新增 SSO 接收方（已确认要做）」的**回溯补规格**。§1.3.2 的设计已闭环，含 4 项用户确认的决策（见下方「已定决策」）。本文件将设计固化为 spec/plan/tasks，落地仍按「端点 + 换票 + 门户接入 + 挑战流程」4 个阶段推进。

## 已定决策（2026-10-13 用户确认，设计已闭环）

| # | 决策点 | 结论 | 对设计的影响 |
| --- | --- | --- | --- |
| 1 | 账号匹配字段 | **共享主键 `id`**（三表共用，业务系统用户 id = MOGO `end_users.id`） | `portal-ticket` 按 `id` 解析 `end_users`；不依赖 email / login_name |
| 2 | 是否 JIT 建号 | **否，仅匹配** | 映射不到 `id` 即回落登录弹窗；不自动建号 |
| 3 | 多租户 | **是** | 票据只带身份，换票走现有挑战流程（`load_tenant_candidates` + `POST /api/auth/login/select-tenant`）让用户选租户 |
| 4 | 域关系 | **跨域传票** | 票据经 `state=` / POST 传入，不依赖共享 Cookie（对齐 022 T030/T031） |

> 设计现已**完整可落地**：账号映射用共享 `id`、不做 JIT、租户走挑战流程、票据跨域传递。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 外部门户用户免密进入 MOGO 用户工作台（单租户 / 核心路径）(Priority: P1)

外部门户（如企业自有门户、业务系统）里已登录的用户，点击进入 MOGO 后**无需在 MOGO 再次输入账号密码**，直接落座到自己的用户工作台。门户后端用**服务身份**向 MOGO 申领一次性票据，前端带票跳转 user-web，user-web 启动即换票建会话。

**Why this priority**: 这是整个特性的核心价值——打通「外部系统 ↔ MOGO 用户工作台」的免登链路。其余故事（多租户选租户、门户接入、攻击防护）均建立在此之上。

**Independent Test**: 准备一个已在 `end_users` 存在（共享 `id` 匹配）的门户用户；门户后端用有效服务令牌调 `POST /api/auth/portal-ticket` 拿到票据 → 前端 `POST /api/auth/portal-exchange` 换票 → 断言返回 `{token, profile, expiresAt}` 且 `end_user_sessions` 出现 `exchanged: true` 记录。该链路可独立验证，不依赖多租户或门户真实部署。

**Acceptance Scenarios**:

1. **Given** 门户用户已在 `end_users` 存在且共享 `id` 匹配，**When** 门户后端持有效 `X-MOGO-Service-Token` 调 `portal-ticket` 并声明该外部身份，**Then** MOGO 返回一次性 HMAC 票据（TTL 60s，含 `sub`/`exp`/`session_id`）。
2. **Given** 拿到有效票据，**When** user-web `POST /api/auth/portal-exchange {portal_token}`，**Then** MOGO 验签 + accept-once + 复用 `_create_session()` 建会话，返回 `{token, profile, expiresAt}`，user-web 写入 `localStorage` 进入工作台。
3. **Given** 同一票据被第二次换票，**When** 再次 `portal-exchange`，**Then** 返回 401（accept-once 生效，`exchanged` 标记已置位）。

---

### User Story 2 - 多租户下用户选租户（挑战流程）(Priority: P2)

当目标用户属于多个租户时，票据只携带身份、不绑定具体租户；换票阶段用 `load_tenant_candidates()` 取可用租户，多个则返回 `requiresTenantSelection`，由用户在前端**复用现有挑战流程**选租户后进入。

**Why this priority**: 决策 #3 要求支持多租户。它不影响单租户核心链路（US1），但决定了换票端点必须能返回「待选租户」而非直接失败。

**Independent Test**: 构造一个在多个租户下均有效的 `end_users` 记录；走 `portal-exchange` 后断言返回 `requiresTenantSelection` 与候选租户列表；随后复用 `POST /api/auth/login/select-tenant` 完成选租户并建会话。

**Acceptance Scenarios**:

1. **Given** 用户可用租户数 > 1，**When** `portal-exchange` 验票通过，**Then** 返回 `requiresTenantSelection` 与 `tenants` 候选列表（不建会话、不返回 token）。
2. **Given** 用户选完租户调 `POST /api/auth/login/select-tenant`，**When** 携带挑战凭证，**Then** 复用现有挑战流程建会话并返回 token。
3. **Given** 单租户用户，**When** `portal-exchange`，**Then** 直接进入工作台，不触发选租户挑战。

---

### User Story 3 - 异常与攻击防护（过期 / 重放 / 映射失败 / 跨租户 / 不落 URL）(Priority: P3)

票据生命周期与边界条件必须对齐 022 安全规约：短 TTL、一次性、签名 fail-closed、不落 URL、跨租户拒绝。任何异常都**回落登录弹窗，不静默失败**。

**Why this priority**: 决定特性能否上线的是安全边界。它横切 US1/US2，但可独立用单测 + 集成测试穷尽验证。

**Independent Test**: 用参数化测试覆盖：① 过期票据（exp 已过）→ 401；② 重放（二次换票）→ 401；③ 映射失败（`id` 不在 `end_users`）→ 401 + 前端回落登录弹窗；④ 跨租户（票据 tenant 与用户可用租户不符）→ 401；⑤ 票据仅经 `state=`/POST 传递，URL 中无令牌。

**Acceptance Scenarios**:

1. **Given** 过期 / 篡改签名的票据，**When** `portal-exchange`，**Then** `hmac.compare_digest` 常数时间比较失败 → 401，fail-closed。
2. **Given** `portal-ticket` 声明一个在 `end_users` 中无匹配 `id` 的外部身份，**When** 签发，**Then** 拒绝（400/401），绝不 JIT 建号。
3. **Given** user-web 启动拿到无效票据，**When** 换票失败，**Then** 立即 `replaceState` 清除 state 并回落登录弹窗，不静默卡死。

---

### Edge Cases

- 票据 `exp` 已过（>60s）→ 验签阶段直接 401，不建会话。
- 同一 `session_id` 被第二次换票 → accept-once 拦截（401），`exchanged` 标记已置位且 `upsert=True` 保证重放检查凭据落库。
- `portal-ticket` 声明的外部身份在 `end_users` 无匹配共享 `id` → 拒绝，不落库、不建号（决策 #2）。
- 跨租户：票据携带 `tenant_id` 与用户可用租户集合不符 → 401（决策 #1/#3 的安全兜底）。
- 票据经 `state=` 传入 user-web 后立即 `replaceState({}, '')` 清除，URL 中不出现令牌（对齐 022 T030/T031）。
- 嵌入式 WebView 场景（`apps/user-web/src/App.vue:1297` 注释提示令牌可能已被消费）→ 换票失败须回落登录弹窗而非白屏。
- 换票成功写入 `localStorage` 的 key 必须与 `apps/user-web/src/App.vue:60-63` 定义一致（`auth_token` / `auth_account` / `auth_user_profile`）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: chat-api MUST 提供 `POST /api/auth/portal-ticket`，鉴权方式为 022 服务身份（`X-MOGO-Service-Token` + `verify_service_call(required_scope=...)`），不得裸暴露。
- **FR-002**: `portal-ticket` MUST 按声明的外部身份（共享主键 `id`）在 `end_users` 解析目标用户；解析失败 MUST 拒绝（不 JIT 建号，决策 #2）。
- **FR-003**: `portal-ticket` MUST 签发一次性 HMAC 票据（`base64url(payload).base64url(HMAC-SHA256)`），payload 含 `sub` + `exp` + `session_id`，TTL **60s**（对齐 `ADMIN_SSO_TOKEN_TTL_SECONDS`）。
- **FR-004**: chat-api MUST 提供 `POST /api/auth/portal-exchange`，鉴权为「凭有效票据」（公开端点）。
- **FR-005**: `portal-exchange` MUST 用 `hmac.compare_digest` 常数时间验签，fail-closed（签名或 `exp` 不通过 → 401）。
- **FR-006**: `portal-exchange` MUST 实现 accept-once：在 `end_user_sessions` 打 `exchanged: true`（复用 admin-api 做法，`upsert=True`），二次换票 401。
- **FR-007**: `portal-exchange` MUST 复用既有 `_create_session(user_doc, available_tenants)`（`chat-api/app/api/endpoints/auth.py`）建会话——会话建立逻辑零改动。
- **FR-008**: `portal-exchange` MUST 返回 `{token, profile, expiresAt}`。
- **FR-009**: 账号匹配 MUST 仅用共享主键 `id`（三表共用），不得依赖 email / login_name，不得 JIT 建号（决策 #1/#2）。
- **FR-010**: 多租户 MUST 走现有挑战流程：`load_tenant_candidates()` 取候选 → 多个返回 `requiresTenantSelection` → 复用 `_create_login_challenge` / `POST /api/auth/login/select-tenant`（决策 #3）。
- **FR-011**: user-web `onMounted`（`apps/user-web/src/App.vue` 约 1819 行）MUST 读取 `window.history.state.portalToken` → 立即 `replaceState({}, '')` 清除 → `portal-exchange` → 成功写 `localStorage`（`auth_token`/`auth_account`/`auth_user_profile`）→ 继续正常启动。
- **FR-012**: 换票失败（过期/已用/映射不到账号）MUST 回落登录弹窗，不得静默失败（参考 `apps/admin-web/src/stores/auth.ts:80-100` 写法）。
- **FR-013**: 票据 MUST 仅经 `state=` / POST 传递，不出现在 URL（对齐 022 T030/T031，决策 #4）。
- **FR-014**: 签名密钥 MUST 优先使用独立 `PORTAL_SSO_SECRET`（便于轮换），可降级复用 `END_USER_AUTH_SECRET`。
- **FR-015**: 门户侧接入（阶段 3）MUST 使用服务令牌 + 前端跳转；MOGO 不要求门户持有签名密钥（路径 1 选型）。
- **FR-016**: 跨租户 MUST 被拒绝：票据 tenant 绑定与用户可用租户不符时 `portal-exchange` 返回 401。

### Key Entities

- **PortalTicket（一次性 HMAC 票据）**：`payload = {sub, exp, session_id}`；形如 `base64url(payload).base64url(HMAC-SHA256(payload, key))`。状态：单次有效，消费后置 `exchanged`。
- **end_users（终端用户主数据）**：由业务系统权威维护；SSO 仅**匹配**其 `id`，不创建。复用既有集合。
- **end_user_sessions（会话）**：换票成功后新建；承载 `exchanged` 标记（accept-once 幂等凭据）。复用既有集合，无新集合。
- **ServiceToken Claim（022 服务身份）**：`service_id` / `tenant_id` / `user_id` + `scope`（最小权限）。`portal-ticket` 需登记 scope（如 `portal:issue-ticket`）于 gatekeeper 端点注册表。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 外部门户用户从点击跳转到进入 MOGO 用户工作台**无需二次输入账号密码**，端到端耗时受票据 60s TTL 约束内完成。
- **SC-002**: 重放（二次换票）与过期票据被拒（401），accept-once 落库生效。
- **SC-003**: 映射不到共享 `id` 的用户**回落登录弹窗**，不静默失败、不自动建号。
- **SC-004**: 多租户用户经选租户挑战流程最终进入**正确租户**的工作台。
- **SC-005**: 测试覆盖**正向 / 过期 / 重放 / 映射失败 / 跨租户**五类场景，全部通过。
- **SC-006**: 票据签名使用 `hmac.compare_digest` 常数时间比较，fail-closed；密钥独立 `PORTAL_SSO_SECRET` 可轮换。

## Assumptions

- `end_users` / `end_user_sessions` 由业务系统权威维护，三表共用 `id`（决策 #1 前提）。
- 022 服务身份机制已就绪：`app/security/service_token.py` + `app/security/gatekeeper.py`，`verify_service_call(required_scope=...)` 对 `insufficient_scope`/`unknown_scope` fail-closed。
- 既有 `_create_session(user_doc, available_tenants)` 与 `load_tenant_candidates()` / `_create_login_challenge` / `POST /api/auth/login/select-tenant` 已实现可复用，本特性不改动其逻辑。
- 前端 `localStorage` key 名在 `apps/user-web/src/App.vue:60-63` 定义，换票成功须写这些 key。
- 票据格式与 `admin_sso` 同源（复用其 HMAC 形态与 60s TTL 约定）。
- 门户侧接入为「外部系统」职责，MOGO 侧提供端点 + 服务令牌；门户示例代码可置于 `docs/samples/` 或等价位置，不进入核心服务代码（除非用户另行要求）。
