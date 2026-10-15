# Tasks: 为 user-web 新增 SSO 接收方

**Input**: Design documents from `/specs/029-user-web-sso-receiver/`（spec.md / plan.md），设计闭环于 `docs/MOGO-Web应用集成方案.md` §1.3.2

**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Tests**: 本特性 spec 明确要求测试覆盖（FR + SC-005），故测试任务为**必需**。

**Organization**: Tasks 按「端点 + 换票 + 门户接入 + 挑战流程」4 阶段分组，并映射到 spec 的 US1/US2/US3，使每阶段可独立实现与验证。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1（核心免登链路）/ US2（多租户挑战）/ US3（异常与攻击防护）
- Include exact file paths in descriptions

---

## Phase 0: Setup（共享基础设施）

**Purpose**: 密钥与配置注入，为后续端点提供签名材料

- [ ] T001 [P] [US1] 在 `services/chat-api/app/core/config.py` 新增 `PORTAL_SSO_SECRET` 配置项（可选；缺省降级复用 `END_USER_AUTH_SECRET`），并在 `.env.example` 追加说明（不改 `.env` 默认值，mogo 只读 `.env`）

**Checkpoint**: 签名密钥可经配置注入，缺省路径不破坏现有行为

---

## Phase 1: Foundational（阻塞前置）

**Purpose**: 票据签名 / 验签工具 + 服务身份 scope 登记，US1/US2/US3 均依赖

**⚠️ CRITICAL**: 本阶段未完成前不得开始端点实现

- [ ] T002 [P] [US1] 在 `services/chat-api/app/api/endpoints/auth.py`（或新建 `app/security/portal_ticket.py`）实现票据签发与验签辅助函数：`sign_portal_ticket(sub, tenant_id, session_id, secret)` 与 `verify_portal_ticket(token, secret)`——`base64url(payload).base64url(HMAC-SHA256)`，payload 含 `sub`/`exp`(TTL 60s)/`session_id`，验签用 `hmac.compare_digest` 常数时间比较、fail-closed
- [ ] T003 [P] [US1] 在 `services/chat-api/app/security/gatekeeper.py` 端点注册表登记 `portal-ticket` 的 `required_scope`（如 `portal:issue-ticket`），并在 `ServiceTokenClaim` 的 `scope` 集合语义中确认最小权限
- [ ] T004 [P] [US3] 在 `services/chat-api/app/api/endpoints/auth.py` 实现 accept-once 幂等辅助：换票时按 `session_id` 在 `end_user_sessions` 打 `exchanged: true`（`upsert=True`），二次换票返回 401（对齐 admin-api `sso/exchange` 做法）

**Checkpoint**: 签名 / 验签 / scope 校验 / accept-once 基础就绪，可进入端点实现

---

## Phase 2: User Story 1 — 端点（portal-ticket + portal-exchange）(Priority: P1) 🎯 MVP

**Goal**: 外部门户后端可签票据、user-web 可换票建会话（单租户核心链路）

**Independent Test**: 用有效服务令牌调 `portal-ticket` 拿票 → `portal-exchange` 换票 → 断言返回 `{token, profile, expiresAt}` 且 `end_user_sessions.exchanged` 已置位；单测 / 集成测试覆盖正向路径

### Tests for User Story 1（必需）⚠️

> **NOTE: 先写测试并确保实现前 FAIL**

- [ ] T005 [P] [US1] 契约 / 集成测试：有效服务令牌签发 + 换票成功，返回 `{token, profile, expiresAt}` —— `services/chat-api/tests/.../test_portal_sso.py`
- [ ] T006 [P] [US3] 参数化安全测试：过期 / 重放（二次换票）/ 篡改签名 → 均 401 —— 同上文件

### Implementation for User Story 1

- [ ] T007 [US1] 在 `services/chat-api/app/api/endpoints/auth.py` 新增 `POST /api/auth/portal-ticket`：鉴权走 022 服务身份 `verify_service_call(required_scope="portal:issue-ticket")`；按声明外部身份（共享 `id`）解析 `end_users`；解析失败拒绝（不 JIT）；签发一次性 HMAC 票据（TTL 60s）返回（FR-001/002/003）
- [ ] T008 [US1] 在 `services/chat-api/app/api/endpoints/auth.py` 新增 `POST /api/auth/portal-exchange`：验签（fail-closed）→ accept-once（T004）→ 复用既有 `_create_session(user_doc, available_tenants)` 建会话 → 返回 `{token, profile, expiresAt}`（FR-004/005/006/007）
- [ ] T009 [US1] 账号匹配严格走共享 `id`（T007 内），不依赖 email / login_name、不建号（FR-009）

**Checkpoint**: User Story 1 独立完成——门户可签票、user-web 可换票建会话；正向 + 安全测试通过

---

## Phase 3: User Story 1 续 — user-web 启动换票（换票落地到前端）

**Goal**: user-web 启动即从 `history.state` 取票、换票、写 `localStorage`、进入工作台；失败回落登录弹窗

**Independent Test**: 在 user-web 启动注入 `window.history.state.portalToken` 模拟跳转 → 断言调用 `portal-exchange`、写 `auth_token`/`auth_account`/`auth_user_profile`、清除 state；注入无效票 → 断言回落登录弹窗

- [ ] T010 [US1] 在 `apps/user-web/src/App.vue` 的 `onMounted`（约 1819 行）开头：读取 `window.history.state.portalToken` → 立即 `replaceState({}, '')` 清除 → 调 `POST /api/auth/portal-exchange {portal_token}`（FR-011/013）
- [ ] T011 [US1] 换票成功：写入 `localStorage` 的 `auth_token` / `auth_account` / `auth_user_profile`（key 名对齐 `App.vue:60-63`），继续正常启动（FR-011）
- [ ] T012 [US3] 换票失败（过期 / 已用 / 映射不到账号）：立即 `replaceState` 清除 state 并**回落登录弹窗**，不静默失败（参考 `apps/admin-web/src/stores/auth.ts:80-100`）（FR-012）

**Checkpoint**: 前端换票闭环；成功进工作台、失败回落登录

---

## Phase 4: User Story 2 — 多租户挑战流程（阶段 4）(Priority: P2)

**Goal**: 多租户用户换票后选租户，复用现有挑战流程进入正确租户

**Independent Test**: 构造多租户 `end_users` → `portal-exchange` 返回 `requiresTenantSelection` + 候选列表 → 复用 `POST /api/auth/login/select-tenant` 完成选租户并建会话

- [ ] T013 [US2] 在 `portal-exchange`（T008）内：换票验签通过后用 `load_tenant_candidates()` 取可用租户；>1 个返回 `requiresTenantSelection` + `tenants` 候选（不建会话、不返 token）（FR-010）
- [ ] T014 [US2] 单租户分支：候选 = 1 时直接复用 `_create_session` 进入，不触发选租户挑战（FR-010）
- [ ] T015 [US2] 跨租户兜底：`portal-exchange` 校验票据 `tenant_id` 与用户可用租户集合；不符返回 401（FR-016）；选租户阶段复用既有 `_create_login_challenge` / `POST /api/auth/login/select-tenant`，零改动

**Checkpoint**: 多租户用户经挑战流程进入正确租户；跨租户被拒

---

## Phase 5: User Story 3 收口 — 门户侧接入示例（阶段 3）(Priority: P3)

**Goal**: 交付门户侧接入参考实现（外部系统职责），验证端到端链路可复现

**Independent Test**: 用示例门户后端（服务令牌）调 `portal-ticket` → 前端 `state=` 跳转 user-web → 完成换票；确认 MOGO 不要求门户持有签名密钥

- [ ] T016 [P] [US3] 在 `docs/samples/portal-sso-integration/` 提供门户后端示例：用服务令牌（`X-MOGO-Service-Token`）调 `portal-ticket` + 前端带 `state=` 跳转（FR-015）
- [ ] T017 [P] [US3] 示例说明「MOGO 不要求门户持有签名密钥」「票据仅经 `state=`/POST 传递」两条关键约束（决策 #4 / FR-013）

**Checkpoint**: 端到端链路有可复现的外部系统示例

---

## Phase 6: Polish & Cross-Cutting

**Purpose**: 安全对齐兜底与文档同步

- [ ] T018 [P] [US3] 在 `docs/MOGO-Web应用集成方案.md` §1.3.2 标注「已实现 / 规约号 029」，并同步 `specs/INDEX.md` 增加 029 行（spec/plan/tasks 完成度）
- [ ] T019 [P] [US3] 安全复盘：确认 `portal-ticket` 端点不裸暴露（走 `verify_service_call`）、密钥独立 `PORTAL_SSO_SECRET` 可轮换（FR-001/014）、票据不落 URL（FR-013）
- [ ] T020 [P] [US1] 运行 quickstart / 既有 auth 测试套件，确认未破坏 `admin_sso` / `_create_session` 现有行为

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 0)**: T001，无依赖
- **Foundational (Phase 1)**: T002/T003/T004，依赖 T001；**阻塞** Phase 2/3/4
- **User Story 1 端点 (Phase 2)**: T005–T009，依赖 Phase 1
- **User Story 1 前端 (Phase 3)**: T010–T012，依赖 Phase 2（换票端点可用）
- **User Story 2 多租户 (Phase 4)**: T013–T015，依赖 Phase 2（复用 `load_tenant_candidates`）
- **User Story 3 门户示例 (Phase 5)**: T016–T017，依赖 Phase 2
- **Polish (Phase 6)**: T018–T020，依赖全部实现完成

### User Story Dependencies

- **US1（P1）**: Phase 2 + Phase 3，核心 MVP，可独立验证与演示
- **US2（P2）**: Phase 4，依赖 US1 端点，多租户分支可独立测试
- **US3（P3）**: 横切，测试与门户示例贯穿各阶段

### Parallel Opportunities

- T002 / T003 / T004（Foundational）可并行（不同文件）
- T005 / T006（US1 测试）可并行
- T016 / T017（门户示例）可并行

---

## Implementation Strategy

### MVP First（US1 端点 + 前端）

1. Phase 0 + Phase 1（密钥 + 签名/scope/accept-once）
2. Phase 2（端点）+ Phase 3（前端换票）
3. **STOP and VALIDATE**：单租户免登链路端到端跑通、测试全绿 → 可演示 MVP

### Incremental Delivery

1. MVP（US1）→ 演示
2. US2 多租户挑战 → 演示
3. US3 门户示例 + 安全复盘 → 交付
4. 每阶段不破坏上阶段行为

---

## Notes

- [P] tasks = different files, no dependencies
- 复用既有 `_create_session` / `load_tenant_candidates` / `_create_login_challenge` / `POST /api/auth/login/select-tenant`，**会话建立逻辑零改动**
- 不新增集合、不新增服务；密钥经配置注入，缺省降级不破坏现有行为
- 测试先于实现并确保 FAIL；每阶段后独立验证
- 提交只 `git add` 具体路径（AGENTS.md）；不越出工作区
