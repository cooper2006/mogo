# 错误码字典 — admin-api（025 FR-30）

> 本文件是 admin-api 错误码的**唯一权威登记处**（FR-29：集中定义于 `app/core/errors.py`，字典含
> `code` / `http_status` / `trigger` / `remedy` 四字段）。新增错误码必须同时改
> `app/core/errors.py` 与本表，否则 `tools/api_check/error_codes_uniqueness.py` 在 CI 中失败。

## 通用错误码（三服务共享拼写）

| code | http_status | trigger | remedy |
|---|---|---|---|
| `api.internal_error` | 500 | 未处理异常兜底（`Exception` handler） | 携 `trace_id` 查日志与 023 排障看板；勿在响应体回显内部信息（FR-12） |
| `api.validation_error` | 422 | 请求体/查询参数 Pydantic 校验失败（`RequestValidationError`） | 按 `fields[].path` 修正字段；客户端应显示字段级错误 |
| `api.bad_request` | 400 | 请求语义错误（JSON 格式、必填缺失等非 schema 类） | 检查请求体格式与必填字段 |
| `api.unauthorized` | 401 | 未认证 / 令牌无效或过期 | 重新登录换取令牌；检查 `Authorization` 头 |
| `api.forbidden` | 403 | 已认证但权限不足（FR-12：不泄漏资源存在性） | 向管理员申请权限码；勿据 403 推断资源是否存在 |
| `api.not_found` | 404 | 资源不存在 | 核对资源 ID 与租户作用域 |
| `api.method_not_allowed` | 405 | HTTP 方法不匹配 | 查阅 OpenAPI 契约 |
| `api.conflict` | 409 | 幂等键冲突（FR-7）/ 资源状态冲突（ETag 之外） | 更换幂等键或读取最新状态后重试 |
| `api.precondition_failed` | 412 | `If-Match` 与当前 ETag 不符（FR-8 并发保护） | 重新 GET 获取新 ETag 后再 PUT |
| `api.rate_limited` | 429 | 超配额 / 限流（FR-13） | 按 `Retry-After` 头退避；详情见 `detail.limit/remaining/window/reset_at` |
| `api.payload_too_large` | 413 | 载荷超过 `payload_limits.yaml`（FR-5） | 拆分请求或压缩附件 |
| `api.not_acceptable` | 406 | `Accept` 协商失败（FR-9） | 请求 `application/json` 或 `application/problem+json` |
| `api.unsupported_media_type` | 415 | 请求 `Content-Type` 不支持 | 使用契约声明的媒体类型 |
| `api.service_unavailable` | 503 | 依赖不可用 / 熔断打开（023 FR-21 联动） | 稍后重试；运维检查依赖健康 |
| `api.partial_failure` | 200 | 批量接口部分失败（FR-14，200 + `partial=true`） | 检查逐项结果，重试失败项 |

## admin-api 专属错误码（待 US2 波次登记）

路由内显式 `HTTPException` 目前仍以 `detail` 字符串返回（022/032 既有契约）。T011/T023
状态码语义整改波次会把其中稳定对外承诺的码逐个登记到这里，命名空间 `api.admin.<domain>.<error>`。
首期不新增，避免与既有 `permission: portal:approve` 之类的 detail 文案破坏兼容。

## 跨服务唯一性

`api.*` 通用码在 chat-api / document-parser 的 `app/core/errors.py` 中以**相同拼写**存在（同义同码），
这是 FR-29「跨服务全局唯一」的反向保证：任何服务新增专属码都不得占用 `api.*` 顶层命名空间。
检查脚本：`python3 tools/api_check/error_codes_uniqueness.py`（CI 执行，见 quality-gate）。
