# Feature Specification: 凭证存储加密接线（工具连接凭证明文 → AES-256-GCM 密文存储）

**Feature Branch**: `034-credential-encryption`

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description: "租户工具连接的凭证（authToken / apiKeyHeader / headers）当前明文存于工具 config；加密能力已实现但零生产调用方。把加密接线到工具连接的 config 存取：写入时加密、读取时解密、API 响应掩码，存量凭证明文一次性迁移，密钥轮换有演练脚本。"

> **设计来源**：本规约落地《MOGO × 企业 Agent OS 整合方案》§4.3「凭证存储加密接线」（文章界面 7「连接器市场——凭证托管」的存储侧缺口）。
>
> **性质说明**：**这是修复而非新建**——`services/admin-api/app/security/encryption.py`（AES-256-GCM）与 `services/admin-api/app/security/kms.py`（KMSProvider 抽象 + EnvVarKmsProvider）已由 022 实现，但全仓无生产调用方（仅测试引用）；本特性负责把既有能力**接线**到 `external_tools` 的 config 存取路径，不新建加密模块。代码尚未开工，任务清单全部未勾选。

## 定位（一句话）

把 022 已实现但零生产调用方的加密/KMS 模块接线到工具连接（`external_tools`）的 config 存取路径——**写入时对识别出的凭证字段加密落库、读取时解密、API 响应掩码回显（`***`）**，并以一次性幂等脚本完成存量明文凭证迁移，使 DB 中不再存在明文凭证，同时保持 Agent 侧"服务端注入、拿不到明文"的现有行为不回退。

## 已定决策（2026-10-23，spec 撰写时拍板）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | 加密范围（仅凭证字段 vs 整个 config） | **仅识别出的凭证字段**：默认清单 `authToken`、`token`、`apiKey`、`secret`、`password`、`accessToken`、`refreshToken`（`config.headers` 内的同名键同样处理）；config 其余字段（`endpoint`/`url`/`authType`/`apiKeyHeader`/`timeoutSeconds`/`enabledToolNames` 等）保持明文，避免把非敏感配置拖入密文导致检索/校验困难。密钥名清单**可配置**（环境变量追加自定义键名） | 存取路径的凭证字段识别函数 |
| 2 | KMS 首期形态 | **环境变量**（复用 `EnvVarKmsProvider`：`MOGO_KMS_MASTER_KEY` / `MOGO_KMS_MASTER_KEY_FILE`），`KMSProvider` 抽象接口直接复用、Vault 预留不实现——与 022 OQ-2 决策逐字一致，不重新决策 | `services/admin-api/app/security/kms.py`（复用） |
| 3 | 迁移策略 | **一次性脚本 + 幂等 + 双跑校验**：`is_encrypted_blob()` 跳过已加密行；对每个迁移行"加密后立即解密校验"再写回；支持 `--dry-run`；执行前要求先做 `mongodump` 备份（沿用 `scripts/migrate_main_id_to_tenant_id.py` 的"先备份、评审后执行"惯例） | `scripts/migrate_tool_credentials_encryption.py` |
| 4 | 掩码口径 | API 响应中**已设置**的凭证字段回显固定串 `***`（不反映原值长度、不回显部分字符）；**编辑提交时该字段留空 = 保持原密文不变，非空 = 用新值重新加密**；`authType=none` 或无该字段时不注入掩码键（保持响应结构稳定） | admin-api `tools.py::_serialize` + chat-api `external_tools.py::_serialize` |
| 5 | 与 022 既有加密模块的关系 | **直接复用，不新建**：`encryption.py`（`encrypt_value`/`decrypt_value`/`decrypt_optional`/`is_encrypted_blob`/`reencrypt`）+ `kms.py`（`KMSProvider`/`EnvVarKmsProvider`/`derive_data_key`）；加密 `purpose` 固定为 `external_tool_credential`（同时作 AAD，不同用途密文不可互换） | `services/admin-api/app/security/`（复用，零新增） |
| 6 | 解密失败时的行为 | **fail-closed**：解密失败（密钥错误 / 密文被篡改 / 版本不支持）时工具调用直接报错，不回退明文、不跳过注入、不静默成功；与 022 加密模块"认证失败统一成 `EncryptionError`"的既有语义衔接 | 读取/注入路径（`external_tools.py`） |
| 7 | chat-api 侧 KMS 依赖 | chat-api 复用 admin-api 的 `app/security/` 实现（同仓同版本部署，022 已在 admin-api 落地该模块）；不向 chat-api 复制一份实现，避免双份密钥语义漂移 | `services/chat-api/app/services/external_tools.py` 引用 admin-api 模块或经共享包导入（plan 收敛） |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 工具连接保存时凭证字段加密落库（Priority: P1）

租户管理员在 admin-web「工具连接」页新增/编辑 HTTP 或 MCP 工具，填写 authType=bearer/api_key 与 Token/Key 后保存。系统把 config 中识别出的凭证字段加密后写入 MongoDB `external_tools` 集合，DB 中该工具的 config 只含密文（`v1|nonce|ciphertext||tag` 形态），明文凭证不落盘。

**Why this priority**: 这是整个特性的**核心缺口**——`services/chat-api/app/services/external_tools.py:141-142` 与 `services/admin-api/app/api/routes/tools.py:113-114` 两条写入路径都直接 `_safe_dict(payload.get("config"))` 原样存取，明文凭证长眠数据库。写入加密不成立，其余故事（掩码、迁移）都无从谈起。

**Independent Test**: 用 `tests/test_security_encryption.py` 风格的 fake DB，对 admin-api `POST /api/tools` 与 chat-api `ExternalToolService.create/update` 各发一次带 `config.authToken="sk-test-123"` 的请求；直接查库断言 `doc["config"]["authToken"]` 是密文（`is_encrypted_blob` 为真）且不含子串 `sk-test-123`；其余字段（`endpoint`/`authType`）保持明文。

**Acceptance Scenarios**:

1. **Given** 一个 `authType=bearer`、`authToken=sk-live-abc` 的 HTTP 工具 payload，**When** 经 admin-api `create_tool` 或 chat-api `ExternalToolService.create` 写入，**Then** 库中 `config.authToken` 为 `encrypt_value()` 产出的密文，`config.authType`/`config.endpoint` 等非凭证字段保持明文。
2. **Given** 已存在一个已加密凭证的工具，**When** 用 `PUT`（全量）提交**不含** `authToken` 的 config，**Then** 已存密文不被覆盖丢失（全量更新时缺失的凭证键保留原密文）；提交含新 `authToken` 时用新值重新加密。
3. **Given** 一个 `authType=none` 的工具，**When** 保存，**Then** config 不做任何加密处理（无凭证字段），响应结构不变。
4. **Given** config.headers 中含 `{"X-Token": "secret-value"}`，**When** 保存，**Then** headers 内命中凭证清单的键同样加密，未命中的头保持明文。

---

### User Story 2 - API 响应掩码回显（Priority: P1）

admin-web 工具列表/详情页拉取工具连接时，后端对已设置的凭证字段回显 `***`；管理员编辑已有工具时，Token/Key 输入框显示 `***`（表示已设置），留空提交保持原值不变。

**Why this priority**: 掩码是加密存储的**可见性闭环**——若响应仍回显明文，则任何有读权限的调用方（含日志、代理层）都能重新拿到凭证，加密落库的意义被抵消；同时"留空即保持"的编辑语义依赖掩码约定，否则用户无法区分"未填"与"已设置"。

**Independent Test**: 预置一个含密文凭证的工具文档，调 admin-api `GET /api/tools` 与 `GET /api/tools/{id}`、chat-api `ExternalToolService.get`，断言响应 `config.authToken == "***"`；再以「编辑表单留空提交」走一次 `PATCH`，断言库中密文未变（`request_id`/`updated_at` 之外的字段不变）。

**Acceptance Scenarios**:

1. **Given** 库中某工具 `config.authToken` 为密文，**When** 调 `GET /api/tools`（列表）或 `GET /api/tools/{id}`，**Then** 响应中 `config.authToken` 为 `***`，不出现任何明文片段。
2. **Given** 管理员在编辑页把 Token 输入框留空（显示 `***`）提交 `PATCH`，**When** 请求只含 `name` 等非 config 字段或 config 不含 authToken，**Then** 库中凭证密文保持不变。
3. **Given** 管理员在编辑页填写了新的 Token 值，**When** 提交，**Then** 新值被加密覆盖旧密文。
4. **Given** 某工具从未设置过凭证（无 authToken 键），**When** 拉取详情，**Then** 响应不出现 `authToken` 键（不注入空掩码），前端按"未设置"渲染。

---

### User Story 3 - Agent 侧服务端注入行为不回退（Priority: P1）

chat-api 执行 HTTP/MCP 工具调用时，从 config 解密出凭证并以服务端方式注入（bearer/api_key header），叠加不可伪造的 `X-MOGO-Main-ID`/`X-MOGO-User-ID` 身份头；Agent（LLM）侧始终拿不到凭证明文。本故事是**回归保护**：加密接线不得改变这套注入语义。

**Why this priority**: 这是整合方案明确背书的既有安全姿态（附录 B：`external_tools.py:947-977` bearer/api_key 注入 + 身份头不可伪造）。加密接线改的是"存取形态"，一旦注入侧行为回退（如把明文经 output_spec/消息体透给 LLM），等于用存储安全换执行安全，不可接受。与 US1/US2 并列 P1，因为它定义了接线的安全边界。

**Independent Test**: 沿用 `services/chat-api/tests/services/test_external_tools_mcp_transport.py` 的 fake 客户端范式：预置密文凭证工具，执行一次 HTTP/MCP 调用，断言（a）出站请求头含正确解密的 Bearer/api_key；（b）身份头 `X-MOGO-Main-ID`/`X-MOGO-User-ID` 存在且覆盖任何用户可控的同名头；（c）落库的 token usage / 日志记录中无凭证明文。

**Acceptance Scenarios**:

1. **Given** 一个 `authType=bearer` 且凭证为密文的工具，**When** Agent 触发该工具调用，**Then** 出站请求带 `Authorization: Bearer <解密后的 token>`，LLM 侧消息与工具描述中不含该 token。
2. **Given** 同上但 `authType=api_key`、`apiKeyHeader=X-API-Key`，**When** 调用，**Then** 出站请求带 `X-API-Key: <解密后的 token>`。
3. **Given** 调用方尝试在工具参数/headers 中伪造 `X-MOGO-Main-ID`/`X-MOGO-User-ID`，**When** 注入叠加，**Then** 平台身份头最后覆盖（`external_tools.py:965-973` 的"applied last"语义保持），伪造值被丢弃。
4. **Given** 库中凭证密文因密钥错误无法解密，**When** 工具调用，**Then** 调用失败并返回可读错误（fail-closed），不出站、不回退明文。

---

### User Story 4 - 存量明文凭证一次性迁移（Priority: P2）

运维执行一次性迁移脚本，把 `external_tools` 集合中存量明文凭证加密后写回；脚本幂等（已加密行跳过）、支持 `--dry-run`、对每个迁移行做"加密→解密→比对"双跑校验，输出迁移报告（扫描数/迁移数/跳过数/失败数）。

**Why this priority**: 没有迁移，已上线部署的数据库里明文凭证依旧存在，特性只对"新写入"生效——那是半成品。优先级低于 US1–US3 是因为新写入路径的加密可先上线（双跑期读路径宽容解密兼容存量明文），迁移脚本可在维护窗口执行；但它仍是验收口径"DB 中无明文凭证"的必要组成。

**Independent Test**: 造一个含 3 条明文凭证工具 + 1 条已加密工具 + 1 条无凭证工具的集合，先 `--dry-run` 断言零写入，再 `--apply` 跑两次，断言：明文行全部变密文、已加密行非加密行原样保留（密文字节不变）、第二次运行迁移数为 0（幂等）、失败数为 0。

**Acceptance Scenarios**:

1. **Given** 集合中存在明文 `authToken` 的工具，**When** 执行 `--apply`，**Then** 该字段被加密写回，且写回前通过"解密回原文"校验。
2. **Given** 集合中已存在密文凭证的工具，**When** 再次执行脚本，**Then** 该行被跳过（`is_encrypted_blob` 判定），密文不被重复加密。
3. **Given** 某行凭证为空串或键不存在，**When** 扫描到该行，**Then** 跳过且不计入失败。
4. **Given** 脚本执行中途某行加密失败，**When** 继续执行，**Then** 该行记入失败清单并保持原状（不写半截状态），脚本最终以非零退出码汇报失败数。

---

### User Story 5 - 密钥轮换演练（Priority: P2）

提供密钥轮换演练文档与脚本：用 `reencrypt()` 把存量密文从旧主密钥迁移到新主密钥，演练全程可验证（轮换后工具调用正常、旧密钥密文在保留期内仍可解密回滚、指纹变更可核对）。

**Why this priority**: 022 FR-19/OQ-2 把密钥轮换列为 KMS 能力但首期无轮换流程；本特性把凭证押在加密存储上后，必须证明"换钥匙"这条路走得通，否则运维不敢上线。优先级 P2：首期环境变量密钥轮换频率低，但演练脚本是验收口径明文要求。

**Independent Test**: 以旧主密钥加密一批工具凭证 → 按演练文档执行轮换脚本（新主密钥 + `reencrypt`）→ 断言全部密文可用新密钥解密、`kms.describe()` 的 `master_key_fingerprint` 已变更；再做一次反向演练（旧密钥 + 备份密文）证明可回滚。

**Acceptance Scenarios**:

1. **Given** 全部凭证以旧主密钥加密，**When** 执行轮换脚本，**Then** 所有密文被 `reencrypt()` 重加密，轮换后抽查解密均成功。
2. **Given** 轮换已完成，**When** 用旧主密钥尝试解密新密文，**Then** 解密失败（`EncryptionError`），证明旧密钥已失效而非双轨并存。
3. **Given** 轮换后保留了轮换前备份，**When** 需要回滚，**Then** 旧备份密文仍可用旧主密钥解密恢复（演练文档给出回滚步骤）。
4. **Given** 轮换脚本输出，**When** 运维核对，**Then** 输出含指纹前后对比（不含密钥本身）与每工具轮换结果清单。

---

### Edge Cases

- **明文/密文双跑期读取**：迁移前与迁移窗口期，库中同时存在明文与密文。读路径 MUST 用 `decrypt_optional()` 宽容解密（非密文原样返回），保证渐进式迁移期间工具调用不中断；迁移完成后读路径仍保持宽容（不强制），避免个别漏网明文导致全站工具不可用。
- **全量 PUT 丢凭证**：`PUT /api/tools/{id}` 走 `_normalize_payload(payload)`（非 partial），config 整体替换。若前端按掩码约定不回传 authToken，全量更新会把凭证打成空——必须定义「全量更新时缺失的凭证键保留原密文」语义（US1 场景 2），否则掩码改版会直接引发凭证丢失事故。
- **PATCH 部分更新**：`PATCH` 走 `partial=True`，仅更新携带的键；未携带 config 时不触碰凭证（现有语义保持）。
- **日志明文泄漏**：`external_tools.py:309-317` 的 `external_tool_test_received` 日志把整个 config（含明文 authToken）以 `_short_text(tool.get("config"), 5000)` 落盘——本特性 MUST 一并脱敏（022 FR-20 的延伸），否则"DB 无明文"被日志侧击穿。
- **空 config / 无凭证工具**：`authType=none` 或 config 为空的工具不加密、不注入掩码键，行为与现状逐字节一致。
- **密钥未配置**：`MOGO_KMS_MASTER_KEY` 缺失时 `EnvVarKmsProvider` 抛 `KmsConfigError`（fail-closed，022 既有语义）。含凭证的工具保存请求 MUST 返回可读错误（500/503 + 配置提示），不允许落明文兜底；本地开发用 `MOGO_ALLOW_INSECURE_DEV_KEY=1` 显式 opt-in。
- **密文被外部篡改**：有人直接改库把密文换掉，AES-GCM 认证标签校验失败 → 调用 fail-closed 报错，不静默出站。
- **user scope 工具**：chat-api `ExternalToolService` 同时服务 organization/user 两种 scope，两条 scope 走同一 config 存取路径，加密/掩码/迁移 MUST 无差别覆盖（迁移脚本按租户+scope 全量扫描）。
- **明文超长误用**：`encrypt_value` 拒绝超过 1MB 的明文（`MAX_PLAINTEXT_BYTES`）。凭证字段是小字符串；若某自定义键误入清单且值巨大，保存返回可读错误而非静默截断。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 在两条写入路径——admin-api `services/admin-api/app/api/routes/tools.py`（`_normalize_payload` 的 config 存取）与 chat-api `services/chat-api/app/services/external_tools.py`（`_normalize_payload` 的 config 存取）——对识别出的凭证字段加密后落库。
- **FR-002**: 凭证字段识别 MUST 基于可配置密钥名清单（默认 `authToken`/`token`/`apiKey`/`secret`/`password`/`accessToken`/`refreshToken`，含 `config.headers` 内同名键），清单 MUST 支持经环境变量追加自定义键名；未命中清单的 config 键 MUST 保持明文。
- **FR-003**: 加密 MUST 复用 `app/security/encryption.py::encrypt_value`（AES-256-GCM，`purpose="external_tool_credential"`），密文格式为 `v1|nonce|ciphertext||tag`（base64url）；MUST NOT 新建加密实现或引入新加密依赖。
- **FR-004**: 读取路径（工具调用注入侧）MUST 复用 `decrypt_optional()` 宽容解密，兼容明文/密文双跑期；注入侧行为 MUST 与现状逐项一致——bearer/api_key header 注入 + `X-MOGO-Main-ID`/`X-MOGO-User-ID` 身份头最后覆盖（`external_tools.py:947-977` 语义不回退），并由回归测试覆盖。
- **FR-005**: API 响应（admin-api `tools.py::_serialize` 与 chat-api `external_tools.py::_serialize`）MUST 对已设置的凭证字段回显固定串 `***`，MUST NOT 回显明文、长度或任何片段。
- **FR-006**: 编辑语义 MUST 定义为：凭证字段留空提交 = 保留原密文不变；非空提交 = 新值重新加密；全量更新（`PUT`）时 config 缺失的凭证键 MUST 保留原密文。
- **FR-007**: 解密失败（`EncryptionError`：密钥错误/篡改/版本不支持）MUST fail-closed——工具调用返回可读错误，MUST NOT 出站、MUST NOT 回退明文、MUST NOT 静默跳过注入。
- **FR-008**: KMS MUST 首期使用 `EnvVarKmsProvider`（`MOGO_KMS_MASTER_KEY` / `MOGO_KMS_MASTER_KEY_FILE`），`KMSProvider` 抽象接口与 Vault 预留保持 022 OQ-2 原状；主密钥缺失或过短 MUST 启动/保存时即报配置错误（不落明文兜底）。
- **FR-009**: 系统 MUST 提供一次性存量迁移脚本（`scripts/` 下，遵循 `migrate_main_id_to_tenant_id.py` 惯例）：幂等（`is_encrypted_blob` 跳过已加密行）、`--dry-run` 支持、加密后立即解密校验再写回、输出扫描/迁移/跳过/失败计数、失败行保持原状且退出码非零。
- **FR-010**: 系统 MUST 提供密钥轮换演练脚本与文档：基于 `reencrypt()` 用新主密钥重加密存量密文，输出指纹前后对比（不含密钥本身），并给出旧备份回滚步骤。
- **FR-011**: 日志与错误信息 MUST NOT 出现凭证明文——含修复 `external_tools.py:309-317` 测试路径对 config 的整包日志（脱敏或只记键名）。
- **FR-012**: chat-api 侧加密能力 MUST 复用 admin-api 已实现的 `app/security/` 模块（同仓部署、零复制实现），避免两份密钥语义漂移。

### Key Entities

- **工具连接 config 凭证字段**: `external_tools.config` 中命中凭证清单的键（默认 `authToken` 等；`headers` 内同名键同规则）。敏感数据主体，本特性的加密/掩码/迁移对象。
- **KMSProvider / EnvVarKmsProvider**（复用，022）: 主密钥来源抽象；首期环境变量实现，`data_key_for(purpose)` 经 HKDF-SHA256 派生 32 字节数据密钥，主密钥与数据密钥分离。
- **encryption.py 函数族**（复用，022）: `encrypt_value` / `decrypt_value` / `decrypt_text` / `decrypt_optional` / `is_encrypted_blob` / `reencrypt`；密文格式 `v1|nonce(12)|ciphertext||tag(16)`，AAD = purpose。
- **迁移脚本**: 一次性、幂等、dry-run、双跑校验的 `external_tools` 集合明文凭证加密工具。
- **轮换演练**: 基于 `reencrypt()` 的密钥轮换脚本 + 演练文档（含回滚）。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: DB 中无明文凭证——对 `external_tools` 集合全量 grep 已知测试凭证值（如 `sk-live-abc`）零命中；`config` 中凭证字段 100% 为 `is_encrypted_blob()` 为真的密文。
- **SC-002**: Agent 侧仍只拿服务端注入——现有注入行为零回退：bearer/api_key 注入 + 身份头不可伪造，既有 `services/chat-api/tests/services/test_external_tools_mcp_transport.py` 及新增回归测试全绿。
- **SC-003**: 密钥轮换有演练脚本且旧密文可解密迁移——轮换后 100% 密文可用新密钥解密、旧备份可回滚、指纹变更可核对。
- **SC-004**: API 响应 100% 掩码——列表/详情/获取接口的凭证字段回显 `***`，响应体（含错误响应）无凭证明文片段。
- **SC-005**: 迁移脚本双跑结果一致——第二次运行迁移数为 0、失败数为 0，已加密行密文字节不变（幂等可证）。
- **SC-006**: 022 既有加密测试（`tests/test_security_encryption.py` / `tests/test_security_kms.py`）保持全绿，证明复用未破坏原模块语义。

## Assumptions

- 假设 `services/admin-api/app/security/` 两个模块在 022 中已落地且测试全绿（已代码级核实：AES-256-GCM + KMSProvider + EnvVarKmsProvider + VaultKmsProvider 预留，测试见 `services/admin-api/tests/test_security_encryption.py`、`test_security_kms.py`），本特性只接线不改其实现。
- 假设 admin-api 与 chat-api 同仓同版本部署，chat-api 可引用 admin-api 的 `app/security/`（或经既有共享机制导入）；不为 chat-api 复制一份加密实现。
- 假设运维已按 022 约定配置 `MOGO_KMS_MASTER_KEY`（生产）或 `MOGO_ALLOW_INSECURE_DEV_KEY=1`（仅本地开发）；迁移执行前有 `mongodump` 备份能力。
- 假设前端 admin-web `ToolEditPage.vue` 的 authToken 输入框已是 `type="password"`（已核实，`ToolEditPage.vue:117`），掩码改造只需把"回显已存值"改为"回显 `***` + 留空保持"语义，不新增输入组件。
- 假设工具 config 的凭证键名以 `authToken` 为主（已核实 admin-web `ToolEditPage.vue:111-117` 与 chat-api 注入点 `external_tools.py:736-741`、`958-964` 三处一致），默认清单覆盖现网全部已知凭证键。

## 跨特性关系

- **与 022-security-hardening（被依赖方）**：022 的 `app/security/encryption.py`（QF-650/651–656、FR-19）与 OQ-2 KMS 决策（环境变量 + 接口预留 + Vault 可选）是本特性的**唯一加密能力来源**；本特性是 022 加密模块的第一个生产调用方，把"已实现的密标"变成"已接线的存储"。反向声明：本特性不修改 encryption.py/kms.py 的任何语义；若 022 后续调整密文格式版本（`v1`→`v2`），本特性的 `decrypt_optional` 宽容解密与迁移脚本是兼容升级的落点。
- **与 013-multi-im-entry（被依赖方/关联）**：013 的多 IM 入口经 chat-api 触发同一工具调用路径（`external_tools.py` 注入侧）。本特性不改注入语义（US3 回归保证），013 的工具调用行为不受影响；反向声明：013 无需任何改动即继承凭证加密。
- **与 018-capability-asset-registration（关联）**：018 的能力资产引用工具时，经同一 `external_tools` 存取路径解析工具定义。本特性加密/掩码后，资产侧看到的是解密后的可用凭证（服务端）而非明文，资产引用链路无需改动；反向声明：若 018 后续在资产文档中镜像工具 config，必须同样掩码，不得把明文带入资产存储。
- **与后续连接器市场（整合方案 §4.10，未立项）**：预置连接器目录的"凭证托管"以本特性的加密存储为前提；本特性交付后该缺口只剩目录本身。

## Non-Goals

- 不新建加密模块、不引入新加密依赖（`cryptography` 库 022 已在用）——只做接线。
- 不引入 Vault 或任何第三方 KMS（022 OQ-2 已拍板首期环境变量；`VaultKmsProvider` 保持预留不实现）。
- 不改变 Agent 侧注入行为（bearer/api_key 注入 + 身份头覆盖语义逐项保持）。
- 不改造 admin-web 工具编辑页的交互范式（沿用 password 输入框，只把回显值改为 `***` + 留空保持语义）。
- 不做预置连接器目录/连接器市场（属整合方案 §4.10，另需立项）。
- 不扩展到其他敏感字段存储（如 `admin_model_instances` 的 api_key——031 的 `_decrypt_api_key` 已有既有加密路径，不在本特性范围）。
- 不做密钥自动轮换调度（只做演练脚本 + 文档；自动轮换属运维体系，YAGNI）。
