# 错误码字典 — chat-api（025 FR-30）

> chat-api 错误码的唯一权威登记处（FR-29：集中定义于 `app/core/errors.py`；字典四字段
> `code` / `http_status` / `trigger` / `remedy`）。新增码须同步本表，否则
> `tools/api_check/error_codes_uniqueness.py` CI 失败。通用码与其他服务同义同码。

## 通用错误码

| code | http_status | trigger | remedy |
|---|---|---|---|
| `api.internal_error` | 500 | 未处理异常兜底 | 携 `trace_id` 查日志/023 看板 |
| `api.validation_error` | 422 | 请求体/参数校验失败 | 按 `fields[].path` 修正 |
| `api.bad_request` | 400 | 请求语义错误 | 检查格式与必填 |
| `api.unauthorized` | 401 | 未认证/令牌无效 | 重新登录 |
| `api.forbidden` | 403 | 权限不足（不泄漏存在性） | 申请权限 |
| `api.not_found` | 404 | 资源不存在 | 核对 ID/租户作用域 |
| `api.method_not_allowed` | 405 | 方法不匹配 | 查 OpenAPI 契约 |
| `api.conflict` | 409 | 幂等键冲突/状态冲突 | 换幂等键或读最新状态 |
| `api.precondition_failed` | 412 | ETag 不符 | 重新 GET 再 PUT |
| `api.rate_limited` | 429 | 限流/超配额 | 按 `Retry-After` 退避 |
| `api.payload_too_large` | 413 | 载荷超限 | 拆分请求 |
| `api.not_acceptable` | 406 | Accept 协商失败 | 用契约媒体类型 |
| `api.unsupported_media_type` | 415 | Content-Type 不支持 | 用契约媒体类型 |
| `api.service_unavailable` | 503 | 依赖不可用/熔断 | 稍后重试 |
| `api.partial_failure` | 200 | 批量部分失败（200+partial） | 重试失败项 |

## chat-api 专属（`api.chat.*`，US2 波次登记）

既有 SSE/流式端点的错误语义（如 `stream.interrupted`、`quota.exceeded`）在 T023 波次
评审后逐个登记，命名空间 `api.chat.<domain>.<error>`。首期不新增。

## 变更记录（破坏性）

- 2026-10-24（025 T005）：500 兜底响应体从 `{"code": -1, "message": ...}` 改为统一
  `ErrorResponse` 结构；数值 `code` 废弃（FR-11 要求稳定字符串码），`message`/`detail`
  兼容键保留。消费方迁移：SSE 协议帧内 `code: 0/-1`  envelope **不受影响**（那是流内帧，
  非 HTTP 错误体，`useChatStream` 的 `payload?.code === 0` 判定不变）。
