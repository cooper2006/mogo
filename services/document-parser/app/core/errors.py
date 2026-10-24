"""025 API 契约与语义加固 — 错误码注册表 + 统一 `ErrorResponse`（FR-10 / FR-11 / FR-29）。

设计口径（spec.md「Clarify 记录」OQ-1，2026-10-11 已消解）：
- 结构以 **RFC 9457 Problem Details** 为基础，扩展 `code` / `trace_id` / `field` / `path`；
  `docs_url` 映射 RFC 9457 的 `instance`。
- 媒体类型对外声明 `application/problem+json`，但**响应体同时保留 `detail` 与 `message`
  两个兼容字段**：`detail` 是既有 FastAPI 契约（大量路由与前端 `err.response.data.detail`
  依赖），`message` 是 chat-api 既有 envelope（`{"code": -1, "message": ...}`）依赖。
  两者在 025 的整改波次（Phase 3+ / US2）之前不能移除。

⚠️ 本模块首期**只接管未处理异常**（`Exception` / `RequestValidationError`），不改任何
路由内显式 `raise HTTPException` 的响应形状——那属于 T011「状态码语义修复」的范围，
需逐路由评审，不在 Phase 1 一次性铺开。

错误码命名空间约定（FR-11 / FR-29，跨服务全局唯一由
`tools/api_check/error_codes_uniqueness.py` 在 CI 校验）：
    api.<domain>.<error>        例：api.internal_error / api.not_found
    服务前缀不写在 code 里（避免与 022 的既有码冲突），写在错误码字典的
    `http_status`/`trigger`/`remedy` 四列里并按服务分文档（见 errors_codes.md）。
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiErrorCode(str, Enum):
    """稳定错误码枚举（FR-11）。

    值一经发布即不可变更含义；新增错误码必须同步登记到 `errors_codes.md` 的字典表。
    """

    # ── 通用（三服务共享语义，定义在各服务 app/core/errors.py 中保持同一拼写）──
    INTERNAL_ERROR = "api.internal_error"          # 500 未处理异常兜底
    NOT_FOUND = "api.not_found"                    # 404
    METHOD_NOT_ALLOWED = "api.method_not_allowed"  # 405
    VALIDATION_ERROR = "api.validation_error"      # 422 请求体/查询参数校验失败
    BAD_REQUEST = "api.bad_request"                # 400
    UNAUTHORIZED = "api.unauthorized"              # 401（FR-12：不泄漏资源存在性）
    FORBIDDEN = "api.forbidden"                    # 403（FR-12：与 401 同形，不区分存在性）
    CONFLICT = "api.conflict"                      # 409 幂等键冲突 / 资源状态冲突
    RATE_LIMITED = "api.rate_limited"              # 429 超配额（FR-13）
    PAYLOAD_TOO_LARGE = "api.payload_too_large"    # 413 载荷超限（FR-5）
    UNSUPPORTED_MEDIA_TYPE = "api.unsupported_media_type"  # 415
    NOT_ACCEPTABLE = "api.not_acceptable"          # 406 内容协商失败（FR-9）
    PRECONDITION_FAILED = "api.precondition_failed"  # 412 ETag/If-Match 不匹配（FR-8）
    SERVICE_UNAVAILABLE = "api.service_unavailable"   # 503 依赖不可用 / 熔断打开
    PARTIAL_FAILURE = "api.partial_failure"           # 200 + partial=true（FR-14）


# code → 建议 HTTP 状态码。用于错误码字典的机器校验与 handler 兜底。
DEFAULT_HTTP_STATUS: dict[str, int] = {
    "api.internal_error": 500,
    "api.not_found": 404,
    "api.method_not_allowed": 405,
    "api.validation_error": 422,
    "api.bad_request": 400,
    "api.unauthorized": 401,
    "api.forbidden": 403,
    "api.conflict": 409,
    "api.rate_limited": 429,
    "api.payload_too_large": 413,
    "api.unsupported_media_type": 415,
    "api.not_acceptable": 406,
    "api.precondition_failed": 412,
    "api.service_unavailable": 503,
    "api.partial_failure": 200,
}


class ErrorFieldDetail(BaseModel):
    """字段级定位信息（FR-11：`field` + `path`）。"""

    model_config = ConfigDict(extra="ignore")

    field: str | None = None
    path: str | None = None       # JSONPath，例：body.session_id
    message: str


class ErrorResponse(BaseModel):
    """统一错误响应结构（FR-10）。

    与 RFC 9457 的映射：`type` ← 固定 `about:blank`（或 docs_url），`title` ← `code`，
    `status` ← `http_status`，`detail` ← `message`，`instance` ← `docs_url`。
    兼容层：`detail` 同时以 FastAPI 既有形态存在（见 handler 的 payload 组装）。
    """

    model_config = ConfigDict(extra="ignore")

    code: str = Field(..., description="稳定错误码（FR-11）", examples=["api.not_found"])
    message: str = Field(..., description="人类可读错误说明，不含内部组件名/版本/路径（FR-12）")
    http_status: int = Field(..., description="HTTP 状态码")
    trace_id: str = Field(..., description="链路追踪 ID（FR-11，供 008 消费）")
    detail: dict[str, Any] | None = Field(default=None, description="结构化附加信息")
    fields: list[ErrorFieldDetail] | None = Field(default=None, description="字段级错误列表")
    field: str | None = Field(default=None, description="单个出错字段名（便捷字段）")
    path: str | None = Field(default=None, description="出错 JSONPath（便捷字段）")
    docs_url: str | None = Field(default=None, description="该错误码的文档链接（RFC 9457 instance）")


def build_error_payload(
    *,
    code: str | ApiErrorCode,
    message: str,
    http_status: int,
    trace_id: str,
    detail: dict[str, Any] | None = None,
    fields: list[ErrorFieldDetail] | list[dict[str, Any]] | None = None,
    field: str | None = None,
    path: str | None = None,
    docs_url: str | None = None,
) -> dict[str, Any]:
    """组装对外错误体（同时携带 RFC 9457 字段与既有兼容字段）。

    返回体的键序稳定，便于契约测试断言。
    """
    code_value = code.value if isinstance(code, ApiErrorCode) else str(code)
    normalized_fields: list[dict[str, Any]] | None = None
    if fields is not None:
        normalized_fields = [
            item.model_dump(exclude_none=True) if isinstance(item, ErrorFieldDetail)
            else dict(item)
            for item in fields
        ]
    model = ErrorResponse(
        code=code_value,
        message=message,
        http_status=http_status,
        trace_id=trace_id,
        detail=detail,
        fields=normalized_fields,  # type: ignore[arg-type]
        field=field,
        path=path,
        docs_url=docs_url,
    )
    payload = model.model_dump(exclude_none=True)
    # RFC 9457 标准键（不替换兼容键，二者并存直到 US2 收敛）
    payload["type"] = docs_url or "about:blank"
    payload["title"] = code_value
    payload["status"] = http_status
    payload["instance"] = docs_url
    # 兼容层：FastAPI 既有消费方（前端 `data.detail`）读 `detail` 字符串。
    # RFC 9457 里 detail 是"人读文本"，故与 message 同值；结构化附加信息在 `error_detail`。
    if isinstance(payload.get("detail"), dict) or "detail" not in payload:
        payload["error_detail"] = payload.get("detail")
    payload["detail"] = message
    # 兼容层：chat-api envelope 消费方读 `message`（已存在）。
    return {k: v for k, v in payload.items() if v is not None or k in ("detail", "message")}
