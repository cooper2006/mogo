# MOVO 数据地图（Data Map）

> 022 FR-24 / T043 —— 个人信息字段标注、处理依据、留存期限、删除能力。
> 对应审计项 QF-667–671（个人信息字段标注 / 访问、更正、导出、删除能力 / 留存期限明确）。
>
> **范围**：本文件覆盖 MOVO 平台持久化的全部用户可识别数据。
> 服务间临时缓存、进程内状态、第三方托管数据（LLM 供应商、OSS、向量库）在
> 「非数据库数据」一节单独说明。
>
> **约定**：
> - **PII 等级**：`L1` 直接标识符（可直接定位到个人）/ `L2` 准标识符（组合可定位）/ `L3` 敏感属性 / `L4` 认证密钥。
> - **处理依据**：`CON` 合同必需 / `LIA` 正当利益 / `LEG` 法定义务 / `LEG-SEC` 安全合规义务 / `CNS` 用户明示同意。
> - **留存**：明确天数 / 事件驱动（随业务对象生命周期） / 未设（需整改）。

---

## 1. 存储位置与隔离

| 层 | 位置 | 说明 |
| --- | --- | --- |
| 业务库 | MongoDB `mogo_dev`（生产为 `mogo`） | 租户数据按 `tenant_id` 逻辑隔离 |
| **审计库** | MongoDB `mogo_audit`（`ASKAI_ADMIN_AUDIT_DB` / `MONGODB_AUDIT_DB`） | 022 FR-17（T044）：与业务库分离，独立备份与权限，哈希链防篡改 |
| 文件存储 | 本地 `/data/knowledge-documents`（`knowledge_storage_type=local`）或阿里云 OSS（`oss`） | 用户上传文档 |
| 向量库 | Weaviate | 文档切片的语义索引 |
| 报告 | `/app/storage/reports/markdown` | 生成的分析报告 |
| 静态资源 | `/data/admin-static` | 管理台前端构建产物 |

> 未配置审计库时审计事件回退写入业务库 —— 这是向后兼容的默认，
> 生产部署应显式配置 `MONGODB_AUDIT_DB=mogo_audit`。

---

## 2. 管理后台账号（`admin_accounts`）

| 字段 | PII | 加密 | 说明 |
| --- | --- | --- | --- |
| `username` | L1 | 明文 | 登录标识 |
| `display_name` | L1 | 明文 | 展示名 |
| `email` | L1 | 明文 | 联系/找回 |
| `phone` | L1 | 明文 | 联系 |
| `avatar` | L2 | 明文（路径） | 头像文件引用 |
| `password_hash` | L4 | `bcrypt` + `password_salt` | 口令，**永不明文存储** |
| `mfa_secret_encrypted` | L4 | **AES-GCM 密文**（`encryption.py`，AAD=`mfa_secret`） | TOTP 密钥 |
| `mfa_secret_hash` | L4 | `sha256` | 完整性校验，与密文配对 |
| `role_name` / `group_code` / `status` | L2 | 明文 | 权限 |
| `tenant_id` / `org_name` | L2 | 明文 | 租户归属 |
| `last_login_at` / `must_change_password` | L2 | 明文 | 会话策略 |

- **处理依据**：`CON`（账号是用户使用平台的合同前置条件）。
- **留存**：随账号生命周期；账号删除时同步清除（见 §7）。
- **删除能力**：`POST /api/organizations/accounts/{id}` → 删除；`PUT /api/platform/tenants/{id}` purge 时级联删除。

## 3. 会话与凭证

| 集合 / 载体 | PII | 加密 | 留存 |
| --- | --- | --- | --- |
| `admin_sessions`（session_id → 用户） | L2 | `ip` 明文（§5 脱敏后落日志） | 30 分钟空闲 / 24 小时绝对超时自动失效；登出立即吊销 |
| `refresh_tokens` | L4（令牌本体） | 只存哈希，**明文令牌不落库** | 24 小时，一次性轮换 |
| `mfa_otps` | L2 | 明文 | 90 秒防重放窗口 |
| `user_invites`（邀请令牌） | L2 | 明文令牌（`secrets.token_urlsafe(32)` 承载型） | `invite_token_ttl_hours`（默认 72h），`used_at` 置位后即失效 |
| JWT access token（仅内存/客户端） | L2 | 签名保护 | 1 小时（`access_token_ttl_seconds`，上限硬编码） |
| SSO 换票凭证（仅内存/客户端） | L2 | 签名保护 | **60 秒**，一次性消费 |

## 4. 租户与组织

| 字段 | PII | 说明 |
| --- | --- | --- |
| `tenants.tenant_id` / `org_name` / `space_type` | L2 | 租户标识 |
| `organizations.owner_user_id` | L2 | 组织所有者 |
| `members.user_id` / `username` | L1 | 成员关系 |
| `departments.*` / `roles.*` | L2 | 组织结构 |
| `account_groups.*` | L2 | 账号分组 |

- **处理依据**：`CON`。
- **删除能力**：租户 purge（平台管理员）级联删除租户下全部集合。

## 5. 对话与个人知识（chat-api）

| 字段 | PII | 说明 |
| --- | --- | --- |
| `chat_sessions.user_id` / `tenant_id` / `title` | L1 | 会话归属 |
| `messages`（用户输入 / 模型输出） | **L3**（内容含用户主动披露的信息） | 会话内容 |
| `users.*`（chat-api 侧终端用户） | L1 | 用户资料 |
| `knowledge_documents`（上传文档） | **L3** | 用户文档本体 |
| `knowledge_document_chunks` | L3 | 文档切片 |
| 向量库（Weaviate）中的 embedding | L3 | 派生数据，随文档删除级联清除 |
| 向量库连接 `apiKeyEncrypted` | L4 | **AES-GCM 密文**（`knowledge_settings.py`） |
| 模型实例 `api_key_encrypted` / `api_secret_encrypted` | L4 | **AES-GCM 密文**（`model_repository.py`） |
| 模型实例 `api_key_masked` / `api_secret_masked` | L4 | 脱敏展示值（`sk-…abcd`） |
| `reports`（生成的分析报告） | L3 | 派生自会话内容 |

- **处理依据**：`CON`（用户主动发起对话/上传文档）。
- **删除能力**：会话删除、文档删除（级联删除 chunk 与向量索引）、报告文件删除。
- **LLM 供应商链路**：请求内容会发送给配置的第三方模型服务。平台不在本地留存供应商响应体
  （`LOG_DEBUG_PAYLOADS=false` 时日志不回显 payload）。供应商侧留存受其自身政策约束 —— 部署方
  需在合同层面确认，见 §6。

## 6. 非数据库数据

| 载体 | 内容 | 留存 | 说明 |
| --- | --- | --- | --- |
| 应用日志（stdout / 文件） | 请求元数据、脱敏后的主体信息 | `LOG_FILE_ENABLED` 开启时按外部日志系统轮转 | 022 FR-20（T040）：敏感字段经 `redaction.py` 脱敏后才落盘 |
| 审计事件（`audit_events`） | 关键操作留痕（登录/登出/权限/MFA/导出/删除） | **≥ 180 天**（`audit_retention_days`，下限硬编码） | 哈希链防篡改；TTL 索引 + 显式 purge 双保险 |
| 浏览器本地存储（`localStorage` / `sessionStorage`） | access token、profile 缓存 | 登出清除；access token 1h 过期 | 前端 `clearSession()` 会清空 |
| KMS 密钥材料 | 主密钥（AES-256-GCM 加密密钥） | 持久 | 022 OQ-2：默认走环境变量，可选 Vault 托管 |

## 7. 删除与数据主体权利（GDPR 能力）

| 权利 | 能力 | 入口 |
| --- | --- | --- |
| **访问**（数据主体获取自身数据） | ✅ | 管理台账号详情、会话列表、个人知识列表；导出见下 |
| **更正** | ✅ | `PATCH /api/auth/me`（姓名/邮箱/电话）、账号更新接口 |
| **导出** | ⚠️ 部分 | 会话内容导出（chat-api 导出接口）、管理台报表导出；**缺**账号全量自导出 |
| **删除**（被遗忘权） | ✅ 级联 | 账号删除、会话删除、文档删除（含向量索引）、租户 purge |
| **限制处理 / 撤回同意** | ⚠️ | 账号 `status=disabled` 等效限制；无独立的同意撤回流 |

## 8. 审计与合规差距（待办）

| # | 差距 | 处置 |
| --- | --- | --- |
| G1 | 缺账号级「一键导出全部个人数据」能力 | 建议在 US5 后续迭代补 `GET /api/export/me` |
| G2 | 缺独立的同意管理与撤回流 | 建议新增 `consent_records` 集合 + 撤回接口 |
| G3 | 第三方 LLM 供应商侧留存不可控 | 部署合同约束 + 可选「禁用外部模型」开关（`PLAN_ONLY_MODE`） |
| G4 | 生产部署需显式配置 `MONGODB_AUDIT_DB` 才能实现审计库分离 | 部署清单已记录，`settings.effective_audit_db` 为空时告警 |
| G5 | 上传文档的文件本体在 OSS 时依赖 OSS 侧生命周期策略 | 需在 OSS bucket 侧配置与 `audit_retention_days` 一致的 TTL |

---

## 9. 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-10-12 | v1 | 首次建立数据地图（022 T043 / FR-24） |
