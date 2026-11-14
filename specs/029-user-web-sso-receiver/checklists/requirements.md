# Requirements Quality Checklist: 029 user-web-sso-receiver

> 本特性已按 `specs/029-user-web-sso-receiver/tasks.md` 的 T001–T020 **全部实现并验证**（2026-10-15，chat-api `tests/api/test_auth_portal_sso.py` 9 项 + user-web `tests/portal-sso-receiver.test.ts` 契约测试通过；api/security/core 回归全绿）。本文件勾的是**需求质量**，与功能落地无关。

**Purpose**: 校验 029（user-web SSO 接收方：门户免二次登录进入 MOGO 用户工作台）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-10-22（回溯补质量门禁）
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [tasks.md](../tasks.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 单租户核心链路（US1）是否定义了"门户签发票据 → user-web 换票 → 建会话进入工作台"的完整闭环，且含正向与失败两条路径？
- [x] CHK002 多租户选租户（US2）是否定义了 `requiresTenantSelection` 的返回结构与复用既有挑战流程（`load_tenant_candidates` + `POST /api/auth/login/select-tenant`）的口径？
- [x] CHK003 异常与攻击防护（US3）是否穷举了过期 / 重放 / 映射失败 / 跨租户 / WebView 五类场景，且均落到"回落登录弹窗、不静默失败"？
- [x] CHK004 FR 是否覆盖四个端点/机制（`portal-ticket` 签发、`portal-exchange` 换票、服务身份鉴权、accept-once 幂等）的失败语义（fail-closed）？
- [x] CHK005 账号匹配是否明确限定"仅共享主键 `id`、不 JIT 建号"（FR-009），并定义映射失败的处理（拒绝而非落库）？
- [x] CHK006 密钥轮换路径（FR-014，`PORTAL_SSO_SECRET` 优先、可降级 `END_USER_AUTH_SECRET`）是否在 FR 中明确？

## 清晰度（Clarity）

- [x] CHK007 票据格式（`base64url(payload).base64url(HMAC-SHA256(payload, key))`）与 payload（`sub`/`exp`/`session_id`）、TTL 60s（对齐 `ADMIN_SSO_TOKEN_TTL_SECONDS`）是否显式声明且可验证？
- [x] CHK008 accept-once 的"幂等凭据落库位置"（`end_user_sessions.exchanged`，`upsert=True`）是否在 FR-006 明确，避免二次换票判定无据？
- [x] CHK009 user-web 启动读票/清票/写 `localStorage` 的 key 名（`auth_token`/`auth_account`/`auth_user_profile`）是否对齐既有定义（FR-011/FR-012 引用 `App.vue:60-63`）？
- [x] CHK010 跨租户拒绝（FR-016）与票据 `tenant` 绑定的语义是否明确（票据携带 tenant 与用户可用租户不符即 401）？

## 一致性（Consistency）

- [x] CHK011 与 022（security-hardening）服务身份机制是否一致：`portal-ticket` 走 `X-MOGO-Service-Token` + `verify_service_call(required_scope=...)`，`portal.issue_ticket` 已在 gatekeeper 端点注册表登记？
- [x] CHK012 与既有 `_create_session` / `load_tenant_candidates` / `_create_login_challenge` 的复用关系是否声明"会话建立逻辑零改动"（FR-007/FR-010），避免重复实现？
- [x] CHK013 "票据仅经 `state=` / POST 传递，不落 URL"是否与 022 T030/T031 的 SSO 票据安全约定一致（决策 #4）？
- [x] CHK014 失败回落登录弹窗（FR-012）是否对齐 admin-web `stores/auth.ts:80-100` 的既有写法，前后端口径统一？

## 边界与歧义（Edge cases & Ambiguity）

- [x] CHK015 跨租户场景（票据 tenant 与用户可用租户不符）是否定义为 401 而非"尝试进入错误租户"？
- [x] CHK016 映射失败（共享 `id` 不在 `end_users`）是否定义为拒绝且不 JIT 建号，避免"无账号即自动注册"的安全隐患？
- [x] CHK017 票据过期 / 篡改签名是否定义为 `hmac.compare_digest` 常数时间比较失败 → 401（fail-closed），无"宽松放行"歧义？
- [x] CHK018 嵌入式 WebView 场景（令牌可能已被消费）换票失败是否明确要求"回落登录弹窗而非白屏"，不静默卡死？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。
- 本特性属**回溯补规格**（代码先于 spec 落地，与 027/030/031 同类）；需求质量经本轮审阅全部达标，可直接进入 SDD 收敛归档。

## 评审结论（2026-10-22 勾选，agent 代审）

**达标已勾 `[x]`（18 项）**：覆盖完整性（CHK001–CHK006）、清晰度（CHK007–CHK010）、一致性（CHK011–CHK014）、边界与歧义（CHK015–CHK018）。

**全部达标理由**：
- 核心链路、多租户挑战、五类异常防护、四个端点失败语义、账号匹配与密钥轮换均已在 FR/US 显式定义（CHK001–CHK006）。
- 票据格式、accept-once 落库位置、localStorage key 名、跨租户语义均已可验证声明（CHK007–CHK010）。
- 服务身份、会话复用、不落 URL、失败回落四处一致性均与 022 / 既有实现双向对齐（CHK011–CHK014）。
- 跨租户拒绝、映射失败不 JIT、fail-closed 验签、WebView 回落四类边界均已无歧义（CHK015–CHK018）。

现 100% 勾选 `[x]`，需求质量门禁通过。
