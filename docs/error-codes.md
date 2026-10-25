# 错误码字典（025 契约硬化 · FR-30 / FR-31 / FR-11）

> 本文档是全仓库错误码的**唯一权威字典**，对应 FR-30（错误码字典含触发条件与处理建议）、FR-31（错误码映射稳定性）、FR-11（稳定错误码）与 QF-269 / QF-270。文档按服务分节，跨服务汇总。
>
> 机器校验配套：`tools/api_check/error_codes_uniqueness.py`（CI 校验错误码跨服务全局唯一）。

## 1. 命名空间与范围

- 错误码命名空间：`api.<domain>.<error>`，例 `api.internal_error`、`api.not_found`（FR-11）。
- **服务前缀不写进 code**（避免与 022 既有码冲突），所属服务写在本字典的 `service` 列。
- 当前三个服务（`admin-api` / `chat-api` / `document-parser`）的 `app/core/errors.py` 定义**同一套 15 个通用码**，语义与拼写跨服务一致。
- 通用码之外的**业务错误码**（非 `api.*` 前缀，散落在各路由/服务层）见 §3，属已知待集中登记项。

## 2. 通用错误码字典（三服务共享，15 个）

来源：各服务 `app/core/errors.py` 的 `ApiErrorCode` 枚举与 `DEFAULT_HTTP_STATUS` 映射表（三处内容一致）。

| `code` | `http_status` | `trigger`（触发条件） | `remedy`（处理建议） |
|---|---|---|---|
| `api.internal_error` | `500` | 未处理异常兜底；代码缺陷、依赖抛未预期异常 | 携带 `trace_id` 反馈；客户端可带退避重试；查服务日志按 `trace_id` 定位 |
| `api.not_found` | `404` | 资源不存在（路径/ID 无效） | 校验资源 ID 与路径；确认资源是否已删除 |
| `api.method_not_allowed` | `405` | 对资源使用了不支持的方法 | 改用正确 HTTP 方法；对照 OpenAPI 文档 |
| `api.validation_error` | `422` | 请求体/查询参数校验失败（Pydantic `RequestValidationError`） | 按 `fields[]`（`field`/`path`/`message`）修正请求体；对照契约 schema |
| `api.bad_request` | `400` | 请求语义错误（非校验类，如缺 userId、非法 token 格式） | 检查必填字段与格式；对照契约 `required` |
| `api.unauthorized` | `401` | 未认证/凭证失效；**不泄漏资源存在性（FR-12）** | 重新登录或刷新 token；带 `Authorization` 重发 |
| `api.forbidden` | `403` | 已认证但无权访问；**与 401 同形，不区分资源存在性（FR-12）** | 检查岗位权限/租户隔离；联系管理员授权 |
| `api.conflict` | `409` | 幂等键冲突 / 资源状态冲突（同名文件、已安装 skill 等） | 处理冲突（如 `replaceExisting=true`、确认替换）；重试需幂等键 |
| `api.rate_limited` | `429` | 超出配额（FR-13） | 尊重 `Retry-After` 头；降低请求频率或申请提额 |
| `api.payload_too_large` | `413` | 请求载荷超限（FR-5，如上传文件超 `knowledge_max_upload_mb`） | 缩小载荷/分片上传；查询上限值 |
| `api.unsupported_media_type` | `415` | 请求 `Content-Type` 不支持 | 发送 `application/json` 等声明媒体类型 |
| `api.not_acceptable` | `406` | 内容协商失败（FR-9，`Accept` 头不支持响应媒体类型） | 调整 `Accept` 头；或降级接受 `application/json` |
| `api.precondition_failed` | `412` | `ETag`/`If-Match` 不匹配（FR-8） | 重新获取资源最新版本；带正确 `If-Match` 重试 |
| `api.service_unavailable` | `503` | 依赖不可用 / 熔断打开 | 尊重 `Retry-After`；待依赖恢复后重试；关注告警 |
| `api.partial_failure` | `200` | 批量操作部分成功（FR-14，响应含 `partial=true`） | 检查返回体里失败项明细；对失败项单独重试 |

## 3. 业务错误码登记表（非 `api.*` 前缀）

这些码**尚未纳入统一 `ApiErrorCode` 枚举**，散落在路由/service 层通过 `HTTPException(detail={"code": ...})` 或业务异常抛出。T043/T051 阶段登记在案（FR-30），集中化迁移待后续 US。

| `code` | `service` | `http_status` | `trigger` | `remedy` | 来源 |
|---|---|---|---|---|---|
| `DUPLICATE_FILENAME` | `admin-api` | `409` | 知识文档上传时组织内已存在同名文件，且未带 `replaceExisting` | 带 `replaceExisting=true` 覆盖，或改名后重传 | `services/admin-api/app/api/routes/knowledge_documents.py:777` |
| `skill_upgrade_confirmation_required` | `chat-api` | `409` | 安装 Skill 覆盖已有版本，需显式 `confirm_replace` | 带 `confirm_replace=true` 重发 | `services/chat-api/app/api/endpoints/skill_package_install.py:49,95` |
| `metadata_mismatch` | `chat-api` | `400` | Skill `_meta.json` 的 `slug` 与 `SKILL.md` 名称不一致 | 修正 `_meta.json` 的 `slug` | `services/chat-api/app/services/skill_packages/validator.py:216` |
| `version_metadata_mismatch` | `chat-api` | 提示（不阻断） | `_meta.json` 与 `SKILL.md` 的 `version` 不一致，使用包版本 | 统一版本字段 | 同上 `:222` |
| `skill_share_token_required` | `chat-api` | 由 handler 决定（常见 `400`/`403`） | Skill 分享缺少 token | 提供分享 token | `services/chat-api/app/services/skill_sharing/service.py:269` |
| `requested_slide_count_mismatch` | `chat-api` | `400` | 演示生成请求的幻灯片数量与素材不符 | 修正幻灯片数量 | `services/chat-api/app/enterprise_capabilities/presentation/service.py:177` |

> `metadata_mismatch` / `skill_share_token_required` / `requested_slide_count_mismatch` 等经业务异常（`SkillPackageError` / `SkillShareError`）抛出，最终 HTTP 状态码由上层 handler 决定，本表按其常见映射登记；如某路由显式改映射，以路由为准并回写本表。

## 4. 稳定性与变更流程（FR-31）

- **值一经发布不可变更含义**（`ApiErrorCode` 枚举注释）。`code` 与其语义（`http_status`）之间的映射变更属**破坏性变更**（`tools/contract/diff.py` 的 `changed_status_semantics`），必须走 major 版本升级（见 `docs/api-versioning.md` §3.2）。
- 新增错误码：**同步登记本字典** + 契约 `error_codes` 注册表 + `tools/contract/validate.py` 校验（契约 `error_codes` 必须都在注册表内）。
- CI 检查：`tools/api_check/error_codes_uniqueness.py` 保证三服务 `code` 字符串跨服务全局唯一、与 `http_status` 映射一致（T046 装配进 CI）。
- 已过观察期的 `deprecated` 错误码可移除（FR-22，见 `tools/contract/deprecation_check.py`）。

## 5. 响应体结构（FR-10 / FR-29）

所有 `api.*` 错误经统一 `ErrorResponse` 返回（三服务 `app/core/errors.py` 定义一致）：

- 媒体类型：`application/problem+json`（RFC 9457 扩展）
- 字段：`code` / `message` / `http_status` / `trace_id` / `fields[]`（`field`/`path`/`message`）/ `detail` / `error_detail` / `docs_url`
- RFC 9457 映射：`type` ← `docs_url`（缺省 `about:blank`），`title` ← `code`，`status` ← `http_status`，`instance` ← `docs_url`
- **兼容层**（US2 收敛前不能移除）：`detail` 与 `message` 同时保留（FastAPI 既有消费方读 `data.detail`，chat-api envelope 消费方读 `message`）

## 6. 待补与已知不一致

- 业务错误码（§3）尚未集中化到 `ApiErrorCode` 枚举，散落在各路由 —— 待后续 US 迁移。
- `api.partial_failure`（`200`）与错误码命名冲突（2xx 携带错误码），语义上属「部分成功」标记，已按 FR-14 明确。
- 契约 gaps 中 G3（admin-api）提到消费方分支依赖非 `api.*` 业务码（如 `DUPLICATE_FILENAME`），已在 §3 登记。
