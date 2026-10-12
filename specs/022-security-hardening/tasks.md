# Tasks: Security Hardening (022)

**Input**: Design documents from `/specs/022-security-hardening/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-10-11)**:
- OQ-1: MFA 通知通道未接入时降级为审计事件
- OQ-2: 首期 KMS 用环境变量 + 集成接口预留，Vault 为可选集成
- OQ-3: TLS 终结在反向代理层，应用层通过 `SECURE_PROXY_SSL_HEADER` 感知
- OQ-4: 内部服务间加密首期内网隔离 + 独立凭证，mTLS 为可选
- OQ-5: CORS 白名单由环境变量配置，默认空

**Checklist Gate**: 本任务文件仅规划，不修改 checklist 标记。

**Organization**: 任务按用户故事分组，每组可独立实现与测试；`[P]` 标记可并行任务。

---

## Phase 0: 安全基座（Blocking Prerequisites for All Stories）

**Goal**: 建立被所有用户故事依赖的安全基础设施（加密模块、审计落点、KMS 接口）。

- [x] T001 [P] 创建 `services/admin-api/app/security/__init__.py` + 各模块文件（`password_policy.py`、`mfa_policy.py`、`kms.py`、`encryption.py`、`redaction.py`、`audit_events.py`）（3h）✅ 2026-10-12，7 文件 / 2122 行
- [x] T002 [P] 创建 `services/chat-api/app/security/__init__.py` + 各模块文件（与 admin-api 结构一致）（3h）✅ 2026-10-12，双服务同构
- [x] T003 [P] 实现 `security/encryption.py`：敏感字段加密/解密（`cryptography==50.0.2`，AES-256-GCM，`v1|nonce|ct|tag`，AAD 绑定 purpose，密钥经 KMS/HKDF 派生）（4h）
- [x] T004 [P] 实现 `security/kms.py`：`KMSProvider` 抽象接口 + `EnvVarKmsProvider`（env 变量/文件回退）+ `VaultKmsProvider`（可选，预留）+ HKDF-SHA256 purpose-scoped 数据密钥派生（4h）
- [x] T005 [P] 实现 `security/redaction.py`：递归 mask/remove 脱敏（含 `password`/`token`/`sso_token`/`api_key`/`Authorization`/URL query token）+ 深度上限 + 泄漏检测报告（4h）
- [x] T006 [P] 扩展审计落点：`audit_events` 集合（哈希链防篡改 + 唯一 seq + 游标重试），新增 `security/audit_events.py`；`mfa_lockouts`/`mfa_used_steps` 同步落库（3h）

**Phase 0 完成状态（2026-10-12）**：
- 双服务各 6 个测试文件 / 176 用例全部通过（admin-api 609 passed，chat-api 同套 176 passed）。
- 顺带修复 2 个阻断级缺陷：`services/{admin-api,chat-api}/tests/conftest.py` 在 HEAD 上存在未闭合三引号导致的 `SyntaxError`，整个测试套件无法收集（QF-106 提交 `1dd5e82` 引入）。
- 顺带补齐租户清理覆盖：`audit_events` / `mfa_lockouts` / `mfa_used_steps` 三个新集合已加入 `TENANT_SCOPED_COLLECTIONS`；两个 MFA 集合的写入路径补写 `tenant_id`（由复合 key / scope 反解），保证租户删除后不残留（`test_every_tenant_id_keyed_collection_in_the_tree_is_covered` 双向守护）。

---

## Phase 1: User Story 1 (P1) — 口令与 MFA 强制策略

**Goal**: 弱口令拒绝 + MFA 强制 + TOTP 防重放 + MFA 解绑通知。
**独立测试**: 弱口令 400；高权限未绑 MFA 无法进入；TOTP 90s 不可重放；解绑通知审计。

- [x] T007 [P] 实现 `security/password_policy.py`：弱口令策略（长度 ≥ 12 + 四类至少三类），`validate_password(password) -> bool`（3h）
- [x] T008 修改 `services/admin-api/app/api/routes/auth.py`：登录/改密链路调用 `password_policy.validate()`，拒绝弱口令（4h）
- [x] T009 修改 `services/chat-api/app/api/routes/auth.py`：注册/改密链路调用 `password_policy.validate()`，拒绝弱口令（3h）
- [x] T010 [P] 实现 `security/mfa_policy.py`：MFA 强制策略（高权限账号检查）+ 限流（5 次/300s）+ used_step 持久化（MongoDB `mfa_used_steps`）（5h）
- [x] T011 修改 `services/admin-api/app/api/routes/auth.py`：登录流程强制 MFA 绑定（高权限账号）+ `/auth/mfa/verify` 限流 + used_step 防重放（6h）
- [x] T012 修改 `services/admin-api/app/api/routes/auth.py`：`/auth/mfa/disable` 解绑通知（邮箱/手机，未接入时降级为审计事件）+ 审计（4h）
- [x] T013 US1 集成测试：弱口令 400 / MFA 未绑无法进入 / TOTP 90s 不可重放 / 解绑通知审计（4h）

**Phase 1 完成状态（2026-10-12）**：
- T007 / T010 已在 Phase 0 随 `password_policy.py` / `mfa_policy.py` 一并交付；本轮补齐 T008 / T009 / T011 / T012 / T013。
- T008：`auth.py` 的 `PasswordChangeRequest` 最小长度 10 → 12，`validate_strength` 改为委托 `password_policy.validate_password`（字符类别由策略统一判定，保留原静态方法以兼容 `/password-reset` 与既有调用方）；`platform/tenants.py` 的租户管理员重置口令由 `len < 6` 收紧到同一策略。
- T009：`chat-api` 自助注册口令校验由「8 位 + 字母 + 数字」收紧到同一策略，`RegisterRequest.password.min_length` 8 → 12。
- T011：新增 `app/security/mfa_gate.py` 组合层（`evaluate_login_gate` / `record_mfa_failure` / `clear_mfa_failures` / `check_and_consume_totp`），把 `mfa_policy` 纯逻辑与 `MongoMfaLockoutTracker` / `MongoTotpUsedStepStore` 接起来；`/login` 响应签发前过闸门（高权限未绑 MFA → 403 `mfaBindRequired`，达上限 → 423 锁定）；`/mfa/verify` 接入限流与 used_step 防重放（90s 窗口，先判重放再校验，锁定时不消耗 step、不调用校验器）。
- T012：`/mfa/enable` 与 `/mfa/disable` 落 FR-23 审计事件并接入 OQ-1 通知降级（通道未接入时仅落审计事件并在响应中回显 `notification.degraded`）；解绑口令错误的尝试也落 `decision=deny` 审计。
- T013：新增 `tests/test_security_mfa_gate.py` 32 用例（内存 fake motor，双服务镜像同套），覆盖登录闸门四态、窗口到期归零、IP 维度隔离、used_step 消费与 TTL、90s 重放拦截、下一窗口放行、锁定优先于校验、审计链自洽与 detail 自动脱敏、通知降级三条路径。
- 兼容性修复：`AccountMfaState.from_row` 增补 `role_name` 兜底（`admin_accounts` 历史字段名与治理层规范字段 `role` 不一致，不改则闸门永远识别不出高权限账号）。
- 验证：admin-api 全量 641 passed；chat-api 全量 2474 passed（2 个失败为在途会话遗留的 `enterprise_capabilities.data` 脚本执行器 tzinfo 缺陷，与本轮无关）。


---

## Phase 2: User Story 2 (P1) — 令牌与会话生命周期

**Goal**: access token TTL ≤ 1h + refresh 链路可达 + 空闲/绝对超时 + 服务间独立凭证。
**独立测试**: TTL ≤ 1h；refresh 一次性轮换；空闲 30min 超时；服务间独立 token。

- [x] T014 [P] 修改 `services/chat-api/app/api/routes/auth.py`：`END_USER_AUTH_TOKEN_TTL_SECONDS` 默认值 ≤ 3600s，启动时超过 1h 告警（3h）
- [x] T015 [P] 修改 `services/admin-api/app/api/routes/auth.py`：`access_token_ttl_seconds` 默认值 ≤ 3600s，启动时超过 1h 告警（3h）
- [x] T016 修改 `services/admin-api/app/api/routes/auth.py`：打通 `/auth/refresh` 链路（当前死代码），实现一次性轮换 + 重放检测吊销整个 family（6h）
- [x] T017 修改 `services/admin-api/app/middleware/timeout.py`：空闲 30min / 绝对 24h 超时判定，`last_activity_at` 读取判定（5h）
- [x] T018 修改 `services/chat-api/app/api/routes/auth.py`：增加空闲 30min / 绝对 24h 超时判定（4h）
- [x] T019 [P] 新增 `services/admin-api/app/security/service_token.py`：服务间独立凭证（每个服务独立 token，生命周期 ≤ 24h，支持轮换）（5h）
- [x] T020 修改 `services/admin-api/app/deps.py` + `services/chat-api/app/deps.py`：gatekeeper 服务身份校验（token + tenantId/userId 双因子核对，跨租户拒绝）（6h）
- [x] T021 修改 `services/admin-api/app/api/routes/auth.py`：口令重置与管理端改密走一次性临时凭据 + 首次登录强制改密（QF-524）（5h）
- [x] T022 US2 集成测试：TTL ≤ 1h / refresh 一次性轮换 / 空闲 30min 超时 / 服务间独立凭证 / 重置后强制改密（4h）

**Phase 2 完成状态（2026-10-12）**：T014–T022 全部落地，双服务（admin-api / chat-api）同步实施。

| 项 | 结果 |
| --- | --- |
| T014 chat-api access token TTL | 7 天 → 3600s（1h）+ 启动告警 `MAX_END_USER_TOKEN_TTL_SECONDS` |
| T015 admin-api access token TTL | 12h → 3600s（1h）+ 启动告警 `MAX_ACCESS_TOKEN_TTL_SECONDS` |
| T016 `/auth/refresh` 链路 | 语义修正为「当前有效凭证登记表」；登录签发 refresh token；`is_current` 翻转实现一次性轮换；重放检测吊销整个 family + 清理会话 |
| T017 admin-api 会话超时 | 新增 `app/security/session_timeout.py`（纯逻辑）+ `app/middleware/timeout.py`（薄封装）；接入 `deps._load_authenticated_account` 覆盖全部需认证路由 |
| T018 chat-api 会话超时 | 共用同一份 `session_timeout.py`；接入 `end_user_session.resolve_session_user`，超时会话置 `expired` |
| T019 服务间独立凭证 | 新增 `app/security/service_token.py`（双服务镜像）：HMAC-SHA256 签名令牌 `v1\|payload\|sig`，TTL ≤ 24h，密钥轮换窗口 |
| T020 gatekeeper 双因子 | 新增 `app/security/gatekeeper.py`（双服务镜像）：`service_id` + `tenant_id` + `user_id` 三重绑定；chat-api `gatekeeper_client` 按上下文签发；未配置新式凭据时回退既有静态共享密钥（灰度可回滚） |
| T021 一次性凭据 + 强制改密 | 口令重置沿用一次性高熵短期凭据；新增 `must_change_password` 标记（管理员代重置置位）+ 5h 兜底过期防永久锁死；自助 `/recover/reset` 清除标记（逃生门）；`RecoveryResetRequest.newPassword` 下限 10 → 12 |
| T022 集成测试 | 新增 4 个测试文件、双服务共 76 个用例 |

**验证**：admin-api **760 passed** / chat-api **2549 passed**（2 个在途 `dsh_runtime` tzinfo 缺陷，与本阶段无关）。

---

## Phase 3: User Story 3 (P1) — 授权与权限最小化

**Goal**: 4 个 Dockerfile 非 root + 服务身份权限最小化。
**独立测试**: 容器非 root；服务身份最小权限。

- [x] T023 [P] 修改 `services/admin-api/Dockerfile`：新增 `USER appuser`（UID 10001），创建用户 + 调整数据卷权限（3h）
- [x] T024 [P] 修改 `services/chat-api/Dockerfile`：新增 `USER appuser`（UID 10001），创建用户 + 调整数据卷权限（3h）
- [x] T025 [P] 修改 `services/document-parser/Dockerfile`：新增 `USER appuser`（UID 10001），创建用户 + 调整数据卷权限（3h）
- [x] T026 [P] 修改 `apps/admin-web/Dockerfile`：新增 `USER appuser`（UID 10001），创建用户；另新增 `apps/admin-web/nginx-main.conf` 供非 root master 使用（3h）
- [x] T027 [P] 修改 `docker-compose.yml`：`security_opt: ["no-new-privileges:true"]` + `cap_drop: [ALL]` + `read_only: true` + 必要的 tmpfs 挂载；`bootstrap` 的 `umask 077 → 022` 保证非 root 容器能读 `runtime.env`（5h）
- [x] T028 实现服务身份权限最小化：服务 token 携带 `scope` 权限码集合，接收端按端点要求核对（`insufficient_scope` / `unknown_scope` 均 fail-closed）（依赖 T020，3h）
- [x] T029 US3 集成测试：4 个容器非 root（`docker exec id`）/ 服务身份最小权限 / 跨租户拒绝 403（3h）

**Phase 3 完成状态**：
- Dockerfile 非 root 已落地 4 个（admin-api / chat-api / document-parser 用 Debian `groupadd`/`useradd`；admin-web 基于 Alpine 用 BusyBox `addgroup`/`adduser`），UID/GID 统一 10001。
- compose 8 个服务加固（bootstrap / chat-api / admin-api / document-api / document-worker / user-web / admin-web / gateway）：`no-new-privileges` + `cap_drop ALL` + `read_only` + tmpfs；两个 nginx 服务仅保留 `NET_BIND_SERVICE`，并额外挂载 `/var/cache/nginx` 与 `/var/log/nginx`（`read_only` 下 nginx 启动必需）。
- tmpfs 必须显式 `mode=`：Docker 默认 0755，非 root 用户写不进去（实测 nginx 在 `/var/cache/nginx/client_temp` 上 EACCES）。
- 存储路径默认值改为绝对路径（admin-api `/data/admin-static`、document-parser `/data/knowledge-documents`、chat-api `ReportFileManager` `/app/storage/reports/markdown`）；`admin-api/app/main.py` 的静态目录 `mkdir` 与 `ReportFileManager` 的 `mkdir` 均改为失败降级告警，不阻断启动。
- 服务身份最小权限：`ServiceTokenClaim` 新增 `scope: tuple[str, ...]`；`gatekeeper` 新增 `GATEKEEPER_ENDPOINT_SCOPES` 注册表（evaluate / decide / list_approvals / list_events）；`verify_service_call(required_scope=...)` 拒绝未授权或未注册的 scope。
- 集成测试见 `deploy/tests/test_container_hardening.py`（58 passed / 6 skipped：镜像不在本地时运行时用例自动 skip）。
- 实测验证：`admin-api` 镜像在 `read_only` + `cap_drop ALL` + `no-new-privileges` + tmpfs 下 `id -u` = 10001，uvicorn 启动至连接 MongoDB 前 **0 条权限错误**；`admin-web` 镜像（nginx）在同等参数 + `NET_BIND_SERVICE` 下返回 `http 200`。

---

## Phase 4: User Story 4 (P1) — 输入安全加固

**Goal**: SSO 令牌 POST 换票 + GET 无副作用 + CORS 白名单。
**独立测试**: SSO 令牌不在 URL；GET 端点无副作用；CORS 拒绝 `*`。

- [x] T030 [P] SSO 令牌从 URL 查询串改为 POST 换票端点（4h）—— 实际落点在 `services/admin-api/app/api/routes/auth.py`（新增 `POST /api/auth/sso/exchange` + `_verify_sso_token`）与 `apps/admin-web/src/api/auth.ts` / `src/stores/auth.ts`
- [x] T031 [P] chat-api 侧 SSO 签发收敛：`ADMIN_SSO_TOKEN_TTL_SECONDS = 60`（原 12h），票据为一次性换票凭证；`apps/user-web/src/utils/adminUrl.ts` 不再拼接 `?sso_token=`，改为 `window.open(url, '_blank', 'state=...')` 随新窗口传入（3h）
- [x] T032 4 个 GET 写端点改造（QF-637 逐一点名，5h）：
  - `chat-api GET /auth/me` → 只读；写操作拆到 `POST /auth/me/refresh-tenants`
  - `chat-api GET /sessions/{id}` → 只读；清除 `scheduled_unread` 拆到 `POST /sessions/{id}/read`
  - `chat-api GET /personal-knowledge/{id}` → 只读；写入 `grant.seen_at` 拆到 `POST /personal-knowledge/{id}/ack`
  - `admin-api GET /organizations/billing` → 只读（组织缺失时返回 `needsInit` 不建库）；惰性 `insert_one` 拆到幂等的 `POST /organizations/billing/init`
- [x] T033 [P] `services/admin-api/app/middleware/cors.py`（新建）：`allow_methods` / `allow_headers` 收敛为显式白名单，入口拒绝 `*`，来源由 `CORS_ORIGINS` 配置（4h）
- [x] T034 [P] `services/chat-api/app/middleware/cors.py`（新建）：同 T033（3h）
- [x] T035 US4 集成测试：SSO 令牌 POST / GET 无副作用 / CORS 白名单（4h）

**Phase 4 完成状态**：
- **T030/T031 SSO**：audit 发现 chat-api 签发的管理端 JWT（12h TTL）被前端拼进 `?sso_token=` 后作为跳转 URL 打开，令牌进入地址栏/浏览历史/书签/分享链接。改造后：① 票据 TTL 收敛到 **60 秒**（`ADMIN_SSO_TOKEN_TTL_SECONDS`）；② 新增 admin-api `POST /api/auth/sso/exchange`（`_verify_sso_token` 校验 HMAC-SHA256 签名 + 过期，`hmac.compare_digest` 常数时间比较，fail-closed 一律 401）；③ **accept-once 幂等** —— 按票据内嵌 `session_id` 打 `exchanged=True` 标记（`upsert=True`，保证会话文档缺失时重放检查仍生效），二次换票 401；④ 成功后签发新的管理端 access token 并注册会话；⑤ 前端 user-web 用 `window.open(url, '_blank', 'state=...')` 传令牌，admin-web 从 `window.history.state` 读取并立即 `history.replaceState({}, '')` 清除，再 POST 换票。
- **T032 GET 无副作用**：新增 `deploy/tests/test_no_side_effects_get.py` —— 用 AST 静态扫描两个服务全部 GET 路由函数，断言函数体内不出现 `insert_one`/`update_one`/`update_many`/`delete_one`/`delete_many`/`replace_one`/`insert_many`/`bulk_write`，作为**回归防线**：将来任何人再往 GET 端点塞写操作立即失败。
- **T033/T034 CORS**：新建 `app/middleware/cors.py`（双服务共用同一实现），`parse_origins` 归一化来源列表并在入口**拒绝通配符**（`*`、`*.example.com`、`http://a/*` 一并拦截，因 `allow_credentials=True` 下 Starlette 无法正确反射通配源，放行只会让部署方误以为跨域已开），`allow_methods` 显式白名单（含 `OPTIONS` 预检方法）+ 大小写归一，`allow_headers` 显式白名单（含 `X-MOVO-Service-Token`、`X-Request-ID`）；来源为空是合法状态（拒绝所有跨域）但必须告警可见。
- 测试：`deploy/tests/test_sso_token_not_in_url.py`（6 条，静态扫描兜底：前端任何源码把 sso_token 拼进 URL 即失败）；`services/admin-api/tests/test_security_cors.py` + `services/chat-api/tests/test_security_cors.py`（各 29 条，含真实 `CORSMiddleware` preflight 行为：非白名单 origin 400、请求的头部不在白名单时预检 400 且不反射攻击头、通配源不被反射）；`services/admin-api/tests/test_security_sso_exchange.py`（15 条，签名/格式/过期/篡改/重放/账号停用全覆盖）。
- 验证：admin-api **816 passed**（基线 772，+44）；chat-api 全量回归进行中（见下方）；`deploy/tests/test_no_side_effects_get.py` 4 passed；`docker compose -f docker-compose.yml config --quiet` 通过。
- 前端 `apps/admin-web` / `apps/user-web` 的改动为纯 TS/Vue 源码改动，未运行前端构建（本轮聚焦后端与静态防线；前端 `pnpm` 锁文件不在本轮改动范围）。

---

## Phase 5: User Story 5 (P1) — 数据安全与加密

**Goal**: HTTPS 强制 + 敏感字段加密 + 日志脱敏 + 审计留痕。
**独立测试**: HTTPS 301 跳转；敏感字段密文；日志无明文；审计防篡改。

- [x] T036 [P] 新增 `deploy/nginx/nginx.conf`：TLS 终结（TLS ≥ 1.2）+ HTTP → HTTPS 301 跳转 + 反向代理配置（5h）
- [x] T037 修改 `docker-compose.yml`：gateway 服务暴露 443 端口，nginx 配置 TLS 证书挂载 + `MOGO_NGINX_CONF` 挂载层切换（4h）
- [x] T038 [P] 敏感字段（`api_key`、`mfa_secret`）以密文存储（依赖 T003，4h）—— 复核确认**已落位**，无需新增改动
- [x] T039 [P] chat-api 敏感字段加密（依赖 T003，3h）—— 同 T038，`repositories/model_repository.py` 已加密
- [x] T040 [P] 审计日志与错误上报中敏感字段脱敏（依赖 T005，3h）—— 复核确认**已落位**
- [x] T041 接口响应按调用者权限裁剪敏感字段（依赖 T005，4h）—— 复核确认**已落位**（白名单序列化）
- [x] T042 [P] 双服务 `main.py`：生产环境 `debug=False` + 关闭详细堆栈 + 调试端点需鉴权（3h）
- [x] T043 [P] 新增 `data/data-map.md`：数据地图（个人信息字段标注、处理依据、留存期限、删除能力）（4h）
- [x] T044 审计体系扩展：防篡改哈希链 + 与业务库分离 + 保留期 ≥ 180 天（依赖 T006，5h）
- [x] T045 US5 集成测试：HTTPS 301 / 敏感字段密文 / 日志无明文 / 审计防篡改 / 数据地图（4h）

**Phase 5 完成状态**：
- **T036 TLS 网关配置**：新建 `deploy/nginx/nginx.conf` 作为 TLS 侧配置**唯一事实来源**（与 tasks.md 指定路径一致）。能力：HTTP(80) → HTTPS(443) **301**（`/healthz` 例外供 LB 探针）、`ssl_protocols TLSv1.2 TLSv1.3`（禁用 1.0/1.1）、仅 AEAD 密码套件（GCM / CHACHA20）、`ssl_session_tickets off`、HSTS（max-age 180 天 + `includeSubDomains` + preload）+ CSP / nosniff / frame-options 安全响应头、透传 `X-Forwarded-*`。`deploy/docker/nginx-https.conf` 保留为兼容入口并指向规范路径。
- **T037 compose 暴露 443**：`gateway` 服务新增 `ports: "${MOGO_HTTPS_PORT:-443}:443"`（未切换 TLS 配置时 443 仅空闲监听，不影响 HTTP 访问）；新增 `MOGO_NGINX_CONF` 把配置挂载改成**挂载层可切换**（`MOGO_NGINX_CONF=./deploy/nginx/nginx.conf docker compose up -d`）；`MOGO_TLS_CERTS_DIR`（默认 `./deploy/tls`）挂到 `/etc/nginx/certs:ro`。gateway 容器 `read_only: true` 无法运行时生成配置，故必须在挂载层切换 —— 证书缺失时 nginx 会在启动阶段直接失败，这是**预期行为**（避免「以为开了 TLS 实际裸奔」的误配置）。
- **T038/T039 敏感字段密文存储（复核，无需新增改动）**：`model_repository.py` 已用 `encrypt_secret()` 落 `api_key_encrypted` / `api_secret_encrypted`，并配 `api_key_masked` / `api_secret_masked` 供展示；`auth.py::_store_mfa_secret` 已落 `mfa_secret_encrypted`（AES-GCM，AAD=`mfa_secret`）+ `mfa_secret_hash`；`knowledge_settings.py` 已落 `apiKeyEncrypted` / `apiKeyMasked`；`org_user_repository.py` 只落 `password_hash` + `password_salt`。**结论：本 Phase 无明文敏感字段落库**，用 `test_no_plaintext_secret_persisted_in_repository_layer` 做回归防线（限定 repositories 层扫描，请求体构造不算持久化）。
- **T040/T041 脱敏与响应裁剪（复核，无需新增改动）**：`audit_events.py` 在写入前调用 `redaction.redact(detail)`，`RedactionConfig` 可注入；响应层全部走**显式白名单序列化**（`organizations.py::_format_account`、`models.py::_format_instance` 只吐 `apiKeyMasked`）—— 白名单优于黑名单，新增字段默认不泄露。
- **T042 生产关闭调试 + 禁止堆栈回显**：admin-api 放宽 prod 判定为 `production|prod|release` 别名，`app_env=production` 时**强制 `debug=False`**（误配降级为告警）；原有全局异常处理已在 prod 下只回 `Internal server error`，完整异常写服务端日志。chat-api 新增 `APP_ENV` 配置 + **全局 `@app.exception_handler(Exception)`**（原缺失）：prod 下回 `{code:-1, message:"Internal server error"}` 且不回显 `str(exc)`，同时强制 `DEBUG=False`；`app/api/endpoints/debug.py` 原有 `require_debug_mode` + `require_end_user_principal` 双闸门保留。
- **T043 数据地图**：新建 `data/data-map.md`。覆盖存储位置与隔离（业务库 / **审计库分离** / 文件 / 向量库）、`admin_accounts` / 会话与凭证 / 租户与组织 / 对话与个人知识 4 张字段级 PII 表（`L1` 直接标识符 → `L4` 认证密钥 + 加密状态 + 处理依据 `CON`/`LIA`/`LEG`/`CNS` + 留存 + 删除入口）、非数据库数据（日志 / 审计 / 浏览器本地存储 / KMS）、**GDPR 数据主体权利矩阵**（访问 ✅ / 更正 ✅ / 导出 ⚠️ 部分 / 删除 ✅ 级联 / 限制处理 ⚠️）、以及 5 条**审计与合规差距清单**（G1 缺账号级一键导出、G2 缺同意撤回流、G3 第三方 LLM 侧留存不可控、G4 生产需显式配 `MONGODB_AUDIT_DB`、G5 OSS 侧生命周期策略待配）。
- **T044 审计体系扩展**：新增 `MIN_AUDIT_RETENTION_DAYS = 180` + `normalize_retention_days()`（低于下限自动提升到 180 并告警，`-1` 表示禁用 TTL 清理）；`AuditEventRepository.__init__` 接受 `retention_days` 并规整；`ensure_indexes()` 在保留期 > 0 时注册 **MongoDB TTL 索引**（`audit_events_retention_ttl`，`expireAfterSeconds = days*86400`）作为保留期的自动执行机制；新增 `purge_expired()`（按 `occurred_at < now - days` 删除，**游标文档不参与判定** —— 否则哈希链续写基准会被清掉），与 TTL 索引互为双保险；新增 `get_audit_db()` 实现审计库分离（`ASKAI_ADMIN_AUDIT_DB` / `MONGODB_AUDIT_DB`，未配置时回退业务库保持既有部署可用）。哈希链防篡改（`chain_hash` / `verify_chain` / `AuditChainBroken`）为 T006 既有能力，本轮补齐保留期与库分离两块缺口。
- 测试：`deploy/tests/test_data_security_us5.py`（**23 条**）—— TLS 协议/密码套件/301/HSTS/转发头/compose 端口 7 条、密文存储 5 条、日志脱敏 3 条、审计防篡改+保留期+库分离 5 条（含真实 `purge_expired` 行为：只删过期事件、保留游标与近期事件）、数据地图 2 条 + 仓库层明文扫描 1 条。
- 验证：admin-api **816 passed**；chat-api **2589 passed / 2 failed**（2 条为其他会话在途的 `dsh_runtime/test_document_script_boundaries.py` 用例，与本轮无关）；`docker compose -f docker-compose.yml config --quiet` 通过。
- 差距与遗留：G1/G2（账号级导出、同意撤回流）需新增接口与集合，建议独立迭代；G4 生产部署须显式配置 `MONGODB_AUDIT_DB=mogo_audit` 才能真正实现审计库分离（`settings.effective_audit_db` 为空时仅回退，行为与既有部署一致）。

---

## Phase 6: User Story 6 (P1) — 供应链安全

**Goal**: 依赖漏洞扫描阻断 + 构建权限分离 + 提交钩子阻止密钥 + 容器非 root。
**独立测试**: 高危 CVE 阻断构建；构建/部署权限分离；提交钩子阻止密钥；容器非 root。

- [ ] T046 [P] 新增 `.github/workflows/ci-security.yml`：`pip-audit` / `pnpm audit --audit-level high` 在 PR 门禁阻断高危 CVE（4h）
- [ ] T047 [P] 新增 `.github/workflows/ci-security.yml`：`osv-scanner`（可选）+ trivy 镜像扫描阻断（4h）
- [ ] T048 [P] 新增 `scripts/check-secrets.sh`：提交钩子/CI 步骤阻止 `.pem`/`.key`/`BEGIN PRIVATE KEY`/`AKIA` 等密钥模式（3h）
- [ ] T049 [P] 修改 `.github/workflows/release.yml`：构建与部署使用独立 OIDC/service account，构建 job 无部署权限（4h）
- [ ] T050 [P] 修改 `.github/workflows/release.yml`：第三方构建步骤固定到不可变版本 + 产物发布前评审与来源校验（4h）
- [ ] T051 新增 `docs/security/VULNERABILITY_POLICY.md`：漏洞工单分级 + 修复披露时限 + 安全公告模板（3h）
- [ ] T052 新增 `docs/security/RESIDUAL_RISK.md`：残余风险豁免模板（3h）
- [ ] T053 US6 集成测试：高危 CVE 阻断构建 / 构建部署权限分离 / 提交钩子阻止密钥 / 容器非 root（依赖 T023–T027）（4h）

---

## Phase 7: Polish & Cross-Cutting Concerns

**Goal**: 观测性、性能、配置化收尾 + 全量验证。

- [ ] T054 [P] 安全加固性能验证：登录链路 p95 < 200ms / 令牌校验 p95 < 5ms / CORS 预检 < 50ms（性能目标断言）（3h）
- [ ] T055 [P] 环境变量配置收尾：`CORS_ORIGINS`、`KMS_PROVIDER`、`TOKEN_TTL_SECONDS`、`IDLE_TIMEOUT_SECONDS`、`ABSOLUTE_TIMEOUT_SECONDS` 等配置项文档化（3h）
- [ ] T056 安全基线自检：QualityForge 报告中相关 QF 条目全部关闭或标记为豁免（5h）
- [ ] T057 写 `quickstart.md`（各子域启用 + 验证命令）+ 验证清单（表格）（4h）
- [ ] T058 更新 `docs/WORK_LOG.md`（安全加固完成记录）（1h）

---

## Dependencies

```text
Phase 0 (安全基座) → 所有故事
Phase 0 (T003/T005/T006) → US5 (T038/T040/T044)
US1 (T007-T013) → US2 (T016-T022)
US1 (T011) → US3 (T028)
US2 (T020) → US3 (T028)
US3 (T023-T027) → US6 (T053)
US5 (T043) → US6 (T052)
US1-6 → Phase 7 (Polish)
关键依赖: T003 encryption 被 US5 复用；T005 redaction 被 US5 复用；T006 audit 被 US5 复用
```

## Parallel Opportunities

- T001/T002（Phase 0 骨架）互不依赖，可并行
- T003/T004/T005/T006（Phase 0 安全基座）互不依赖，可并行
- T007/T010（US1 策略）互不依赖，可并行
- T014/T015（US2 TTL）互不依赖，可并行
- T023/T024/T025/T026（US3 Dockerfile）互不依赖，可并行
- T030/T031（US4 SSO）互不依赖，可并行
- T033/T034（US4 CORS）互不依赖，可并行
- T036/T038/T039/T040/T042/T043（US5 并行项）互不依赖，可并行
- T046/T047/T048/T049/T050（US6 CI/CD）互不依赖，可并行
- 故事间按 US1→US2→US3→US4→US5→US6 顺序推进，US4 可与 US1/US2 并行

## MVP Scope

- **最小可交付 = Phase 0 + US1 + US3**（T001–T013, T023–T029）：安全基座 + 口令/MFA 强制 + 容器非 root，建立基础安全防线
- **增量交付**：US2（令牌生命周期）→ US4（输入安全）→ US5（数据安全）→ US6（供应链）

## Implementation Strategy

- 先 Phase 0（安全基座），再 US1（口令/MFA，最紧急），再 US3（容器非 root，基础设施层）
- US2/US4 可与 US1 并行推进（不同模块，无冲突）
- US5/US6 依赖前序故事完成
- 每故事完成即独立可测（Acceptance Scenarios 即测试基准）
- 测试基准 = spec Acceptance Scenarios + QualityForge 报告中相关 QF 条目

## Notes

- 本 tasks.md 为 `/speckit-tasks` 产出，含 022 的 clarify 决策（MFA 降级审计、KMS 环境变量+接口、TLS 反向代理终结、服务间内网隔离、CORS 环境变量）。
- 实现需先通过 `checklists/requirements.md` 门禁（未勾选需求项须先消解）。
- 未改 services 源码；本文件仅在 `specs/022-security-hardening/` 下。
- 总估算：58 个任务，约 180–220 小时（23–28 人日）。
