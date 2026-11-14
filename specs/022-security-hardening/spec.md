# Feature Specification: Security Hardening

**Feature Branch**: `022-security-hardening`

**Created**: 2026-10-11

**Status**: Draft

**Input**: QualityForge 审计（96 个 P0/P1 安全缺陷，覆盖认证、授权、输入、数据、供应链 5 个子域）

## User Scenarios & Testing *(mandatory)*

以下用户故事按优先级排列，每个都是可独立交付、可独立测试的垂直切片。本特性为**缺口新特性**（非回溯固化），目标是建立生产级安全基线。

### User Story 1 (P1) — 口令与 MFA 强制策略

当前 `admin-api` 登录仅当 `mfa_enabled && mfa_secret_hash` 同时存在才走二次校验，否则 `_issue_login_response` 直接签发完整 access token；弱口令仅 `min_length=10` 但无复杂度；`/auth/mfa/verify` 无失败计数；TOTP 无 `used_step` 持久化；`/auth/mfa/disable` 强校验只完成一半，解绑后不通知持有人。

- **QF-521** 弱口令拒绝（服务端拒绝纯数字/纯字母/无特殊字符/长度不足）
- **QF-525** MFA 强制（高权限账号未绑定 MFA 时无法进入业务）
- **QF-526** 第二因子限流（`/auth/mfa/verify` 按 username+tenant_id+IP 限流并冷却）
- **QF-527** TOTP 不可重放（持久化 `used_step`，同一时间窗内不可重复使用）
- **QF-530** MFA 解绑强校验（`/auth/mfa/disable` 成功后通知账号持有人 + 审计）

**Acceptance Scenarios:**
- 弱口令被拒：含大写字母/小写字母/数字/特殊字符且长度 ≥ 12，否则 400
- MFA 未绑定无法进入：平台管理员/租户管理员账号未绑定 MFA → 登录后必须完成 MFA 绑定流程才能进入业务
- TOTP 同码 90s 内不可重复：同一 `code` 在 `verify_totp` 窗口（±1 步）内第二次验证 → 拒绝
- MFA 解绑通知持有人：解绑成功后向绑定邮箱/手机发送变更通知（邮件通道未接入时降级为审计事件）

### User Story 2 (P1) — 令牌与会话生命周期

当前 `chat-api` 默认 `END_USER_AUTH_TOKEN_TTL_SECONDS = 7 天`；`/auth/refresh` 链路不可达（死代码）；`last_activity_at` 只写不判；`backend_service_token` 全服务共享；gatekeeper 仅校验 token 即放行任意 tenantId/userId；重置密码可直提 `newPassword`，无强制改密。

- **QF-524** 重置无明文旁路（`/reset-password` 与 `/platform/tenants/{id}/admin/reset-password` 走一次性临时凭据 + 首次登录强制改密）
- **QF-532** 访问令牌短时效（`chat-api` 与 `admin-api` access token TTL ≤ 1h，TTL 上限护栏启动告警）
- **QF-533** 刷新令牌一次性轮换（`/auth/refresh` 链路可达，一次性轮换 + 重放检测吊销整个 family）
- **QF-535** 空闲/绝对超时（`last_activity_at` 判定生效，空闲 30min 超时，绝对 24h 超时）
- **QF-558** 服务间独立凭证（每个服务独立 service token，禁止 `backend_service_token` 共享）
- **QF-561** 服务身份审计（gatekeeper 对服务身份做权限最小化校验，token + tenantId/userId 双因子核对）
- **QF-562** 无长期静态密钥（服务间 token 生命周期 ≤ 24h，支持轮换；仓库/镜像中不存在长期静态服务密钥）

**Acceptance Scenarios:**
- 重置后强制改密：管理端重置密码 → 用户下次登录必须以临时凭据登录 → 立即强制改密 → 旧凭据作废
- 访问令牌 ≤ 1h：`chat-api` 与 `admin-api` access token TTL 均 ≤ 3600s，启动时超过 1h 告警
- 刷新令牌一次性轮换：使用 refresh token 一次后即失效，重放被检测 → 吊销整个 token family
- 空闲 30min 超时生效：`last_activity_at` 距当前 > 30min → 401 强制重新登录
- 服务间独立凭证：每个服务使用独立 service token，gatekeeper 校验 token + 声明的 tenantId/userId 一致

### User Story 3 (P1) — 授权与权限最小化

当前 4 个 Dockerfile（`admin-api`、`chat-api`、`document-parser`、`admin-web`）无 `USER` 指令，容器以 root 运行；gatekeeper 对服务身份仅校验 token 即放行任意 tenantId/userId。

- **QF-575** 容器非 root（4 个 Dockerfile 均以非 root 用户运行，UID ≥ 10001）
- **QF-561** 服务身份权限最小化（服务身份仅持有必要权限码，不允许跨租户越权）

**Acceptance Scenarios:**
- 容器以非 root 运行：4 个 Dockerfile 均以 `USER appuser`（UID 10001）运行，`docker exec` 验证
- 服务身份最小权限：服务身份 token 仅携带最小权限码，跨租户调用被拒绝（403）

### User Story 4 (P1) — 输入安全加固

当前 SSO 令牌 `sso_token` 拼入 URL 查询串；4 个 GET 端点执行写操作；CORS `allow_methods=['*'], allow_headers=['*']`。

- **QF-634** SSO 令牌不在 URL（SSO 令牌走 POST 换票，不落 URL 查询串）
- **QF-637** GET 无副作用（4 个 GET 端点改为 POST，GET 端点不执行写操作）
- **QF-640** CORS 预检收敛（`allow_methods` 与 `allow_headers` 改为显式白名单）

**Acceptance Scenarios:**
- SSO 令牌 POST 换票：SSO 令牌通过 POST 请求体传递，URL 查询串不含 `sso_token`
- GET 端点无副作用：4 个原 GET 写端点改为 POST，GET 端点仅查询
- CORS 白名单：`allow_methods` 与 `allow_headers` 收敛为显式白名单，拒绝 `*`

### User Story 5 (P1) — 数据安全与加密

当前无强制 HTTPS；内部链路明文；敏感字段明文存储；无 KMS 托管；日志含明文敏感字段；调试模式未关闭；错误提示泄漏内部标识；无数据地图；审计留痕不完整。

- **QF-645** HTTPS 强制（全站 TLS 终结，HTTP 请求 301 跳转，TLS 版本 ≥ 1.2）
- **QF-649** 内部链路加密（服务间调用使用 mTLS 或内网隔离 + 加密）
- **QF-650** 敏感字段密文存储（`password_hash`、`mfa_secret`、`api_key` 等敏感字段以密文或不可逆形式存储）
- **QF-651–656** KMS 托管、密钥分离与轮换、加密算法基线（数据密钥与主密钥分离，KMS 集成接口预留）
- **QF-659–666** 日志脱敏、响应裁剪、调试关闭、错误不泄漏（`password`/`token`/`sso_token` 等字段日志脱敏；响应按调用者权限裁剪；`debug=False`；错误不泄漏账号存在性与内部标识）
- **QF-667–671** 数据地图、GDPR 能力、留存期限（个人信息字段标注；访问/更正/导出/删除能力；留存期限明确）
- **QF-675–678** 审计留痕、防篡改、日志保留（关键操作全部留痕；审计日志防篡改且与业务库分离；日志保留期 ≥ 180 天）

**Acceptance Scenarios:**
- 全站 HTTPS：反向代理终结 TLS，HTTP → HTTPS 301 跳转，TLS 版本 ≥ 1.2
- 敏感字段加密存储：`password_hash` 已不可逆；`api_key`、`mfa_secret` 等以密文存储
- 密钥 KMS 托管：主密钥托管于 Vault/KMS（首期环境变量 + KMS 集成接口预留），数据密钥不入库不入码
- 日志无明文：审计日志与错误上报中无明文敏感字段（`password`/`token`/`sso_token`/`api_key`）

### User Story 6 (P1) — 供应链安全

当前 3 个 Python 服务无依赖漏洞扫描；构建/部署权限未分离；提交钩子未阻止密钥；容器 root 运行；流水线无高危漏洞阻断。

- **QF-679–682** 依赖漏洞扫描（`pip-audit` / `osv-scanner` 流水线阻断高危 CVE）、修复时限、残余风险豁免
- **QF-692–698** 构建权限分离（CI/CD 中构建与部署使用独立凭证）、不可变版本、来源校验、提交钩子阻止密钥
- **QF-702–706** 漏洞工单（分级 + 修复披露时限）、安全公告（受影响与修复版本）、容器非 root、内核能力最小化

**Acceptance Scenarios:**
- 高危漏洞阻断构建：`pip-audit --require-highest-version` 或 `pnpm audit --audit-level high` 在 PR 门禁阻断高危 CVE
- 构建/部署权限分离：CI 与部署使用独立 OIDC/service account，构建 job 无部署权限
- 提交钩子阻止密钥：`git push` 钩子或 CI 步骤阻止新增 `.pem`/`.key`/`BEGIN PRIVATE KEY` 等
- 容器非 root：4 个 Dockerfile 均以非 root 运行（与 US3 联动）

### Notes / Assumptions

- 本特性补齐 `QualityForge` 审计 96 个 P0/P1 安全缺陷（覆盖认证/授权/输入/数据/供应链 5 个子域）
- 为**缺口新特性**（非回溯固化），目标是建立生产级安全基线，不改变现有认证架构
- MFA 邮件/短信通道未接入时，降级为审计事件（QF-530 以审计事件满足最小合规）
- 首期密钥管理用环境变量 + KMS 集成接口预留，不引入第三方密钥管理（Vault 为可选集成）
- 本特性依赖 001 gatekeeper（权限码模型）、006 RBAC（角色授权）、017 memory（scope 可见性）的既有基础设施

## Functional Requirements

- **FR-1**: 弱口令在服务端被拒绝，策略：长度 ≥ 12 + 大写 + 小写 + 数字 + 特殊字符四类至少三类（QF-521）
- **FR-2**: 高权限账号（平台管理员/租户管理员）未绑定 MFA 时无法进入业务，登录流程强制 MFA 绑定（QF-525）
- **FR-3**: `/auth/mfa/verify` 按 username+tenant_id+client_ip 限流，5 次失败/300 秒后锁定并强制重新登录（QF-526）
- **FR-4**: TOTP 校验持久化 `used_step`，同一时间窗（±1 步）内同一 code 不可重复使用（QF-527）
- **FR-5**: `/auth/mfa/disable` 成功后通知账号持有人（邮箱/手机，未接入时降级为审计事件），并写审计事件（QF-530）
- **FR-6**: 口令重置与管理端改密走一次性临时凭据 + 首次登录强制改密，无明文旁路（QF-524）
- **FR-7**: `chat-api` 与 `admin-api` access token TTL ≤ 3600s，启动时超过 1h 告警，无 TTL 护栏视为配置错误（QF-532）
- **FR-8**: `/auth/refresh` 链路可达，刷新令牌一次性轮换 + 重放检测吊销整个 family（QF-533）
- **FR-9**: 空闲 30min / 绝对 24h 超时同时生效，`last_activity_at` 判定生效（QF-535）
- **FR-10**: 服务间调用使用独立 service token，每个服务 token 生命周期 ≤ 24h 且支持轮换（QF-558、QF-562）
- **FR-11**: gatekeeper 对服务身份做权限最小化校验，token 与声明的 tenantId/userId 双因子核对，拒绝跨租户越权（QF-561）
- **FR-12**: 4 个 Dockerfile 均以非 root 用户运行（UID ≥ 10001），镜像最小化（QF-575、QF-704）
- **FR-13**: 容器文件系统与内核能力最小化（`read_only: true` + 必要的 tmpfs 挂载，`cap_drop: ALL`）（QF-705、QF-706）
- **FR-14**: SSO 令牌不在 URL 查询串，走 POST 换票端点传递（QF-634）
- **FR-15**: GET 端点不执行写操作，4 个原 GET 写端点改为 POST（QF-637）
- **FR-16**: CORS `allow_methods` 与 `allow_headers` 收敛为显式白名单，拒绝 `*`（QF-640）
- **FR-17**: 全站 HTTPS（反向代理 TLS 终结，TLS ≥ 1.2），HTTP 请求 301 跳转 HTTPS，明文请求不返回业务内容（QF-645）
- **FR-18**: 内部服务间调用使用 mTLS 或内网隔离 + 加密（QF-649）
- **FR-19**: 敏感字段（`password`、`mfa_secret`、`api_key`、`sso_token`、`access_token`、`refresh_token`）以密文或不可逆形式存储，主密钥托管于 KMS（首期环境变量 + KMS 集成接口预留）（QF-650、QF-651–656）
- **FR-20**: 审计日志与错误上报中无明文敏感字段（`password`/`token`/`sso_token`/`api_key` 等），按策略脱敏（QF-659–660）
- **FR-21**: 接口响应按调用者权限裁剪敏感字段（QF-660）
- **FR-22**: 生产环境关闭调试模式与详细堆栈，调试端点在公网不可达或需鉴权（QF-664–666）
- **FR-23**: 关键操作（登录/登出/权限变更/MFA 操作/数据导出/删除）全部留痕，审计日志防篡改且与业务库分离，保留期 ≥ 180 天（QF-675–678）
- **FR-24**: 个人信息字段数据地图标注（PII 处理依据、留存期限、删除能力），GDPR 能力（访问/更正/导出/删除）（QF-667–671）
- **FR-25**: 依赖漏洞扫描（`pip-audit` / `pnpm audit`）在 PR 门禁阻断高危 CVE，修复时限按严重级别定义（高危 7 天/中危 30 天），残余风险有书面豁免与到期日（QF-679–682）
- **FR-26**: CI/CD 构建与部署使用独立 OIDC/service account，构建 job 无部署权限（QF-692）
- **FR-27**: 第三方构建步骤固定到不可变版本，产物发布前经过评审与来源校验（QF-695–696）
- **FR-28**: 提交钩子或 CI 步骤阻止新增 `.pem`/`.key`/`BEGIN PRIVATE KEY`/`AKIA` 等密钥模式（QF-698）
- **FR-29**: 漏洞工单分级 + 修复披露时限，安全公告标明受影响与修复版本（QF-702–703）

## Non-Goals

- 不引入外部 IDS/WAF（依赖反向代理层，不在应用层实现）
- 不改变现有认证架构（仍为 JWT + refresh token，仅加固）
- 不引入第三方密钥管理（首期用环境变量 + KMS 集成接口预留，Vault 为可选集成）
- 不实现 LLM 网关韧性（属特性 007）
- 不实现 DAG 通用编排（属特性 010）
- 不实现自进化 / Dream Cycle（属特性 011）
- 不实现会话级版本化（属特性 002）
- 不重建权限码模型（沿用 001 gatekeeper + 006 RBAC）
- 不重建审计落点（沿用 001 gatekeeper 的审计体系，扩展范围）

## Success Criteria

- 认证/授权/输入/数据/供应链 5 域 P0/P1 缺陷清零（QualityForge 报告中相关 QF 条目全部关闭或标记为豁免）
- 弱口令拒绝率 100%（策略：长度 ≥ 12 + 四类至少三类）
- MFA 强制覆盖率 100%（高权限账号）
- 访问令牌 TTL ≤ 1h 覆盖率 100%（`chat-api` + `admin-api`）
- 容器非 root 覆盖率 100%（4 个 Dockerfile）
- 依赖漏洞扫描 PR 门禁阻断覆盖率 100%（3 个 Python 服务 + 2 个前端）
- 审计日志覆盖率 100%（关键操作），保留期 ≥ 180 天
- 日志明文敏感字段 0 泄漏（`password`/`token`/`sso_token`/`api_key`）

## Further Details

- 技术实现由 plan.md 承载
- 各子域的启用步骤与验证命令见 quickstart.md
- 任务拆分与并行机会见 tasks.md

## 跨特性关系

- **与 001 gatekeeper-governance**：001 的六层门禁链是 022 的**受管入口**——022 加固后的服务身份/令牌/权限变更事件 100% 过 001 门禁审计；022 的 FR-11（服务身份最小化）建立在 001 的权限码模型之上
- **与 006 position-rbac-admin**：006 的岗位角色权限码是 022 FR-11（服务身份最小权限）的预设组基础；022 不重建权限码模型
- **与 017 three-scope-memory**：017 的 scope 可见性是 022 FR-11（服务身份跨租户越权拒绝）的语义基础
- **与 020 platform-multi-tenancy**：020 的租户隔离是 022 FR-11（服务身份校验 tenantId 一致）的租户维度基础
- **依赖 QualityForge 审计**：本特性为**缺口新特性**，输入是 QualityForge 审计的 96 个 P0/P1 安全缺陷清单（QF-521–706 范围）

## Clarify 记录（2026-10-11）

### OQ-1 MFA 通知通道
- **决策**：邮件/短信通道未接入时，MFA 解绑通知降级为审计事件（QF-530 以审计事件满足最小合规）。邮件通道由后续特性（如 025 通知中心）接入。
- **影响**：`/auth/mfa/disable` 实现包含通知触发点，通道可用时发通知，不可用时仅落审计。

### OQ-2 KMS 集成策略
- **决策**：首期密钥管理用**环境变量 + KMS 集成接口预留**（`services/*/app/security/kms.py` 定义 `KMSProvider` 抽象接口），不引入第三方密钥管理。Vault 为可选集成实现（实现 `KMSProvider` 接口即可接入）。
- **影响**：FR-19 主密钥托管在环境变量（首期）或 KMS（后续接入 Vault 时），数据密钥不入库不入码。

### OQ-3 HTTPS 终结点
- **决策**：TLS 终结在反向代理层（nginx/traefik），应用层不直接暴露 TLS。`docker-compose.yml` 中 admin-web/user-web 服务通过 `ports` 暴露 HTTPS 端口（443），HTTP（80）仅用于 301 跳转。
- **影响**：FR-17 全站 HTTPS 由反向代理配置实现，应用层通过 `SECURE_PROXY_SSL_HEADER` 感知 TLS 状态。

### OQ-4 服务间加密
- **决策**：内部服务间调用首期使用内网隔离（Docker 网络）+ 服务间独立凭证（FR-10），mTLS 为可选增强（不纳入首期范围）。
- **影响**：FR-18 首期以内网隔离满足，mTLS 集成接口预留。

### OQ-5 CORS 白名单来源
- **决策**：CORS 白名单来源由环境变量配置（`CORS_ORIGINS`），默认空（拒绝所有跨域），生产环境按租户配置。
- **影响**：FR-16 CORS 白名单由运维配置，不硬编码在代码中。
