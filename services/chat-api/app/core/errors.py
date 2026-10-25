"""025 API 契约与语义加固 — 错误码注册表 + 统一 `ErrorResponse`（FR-10 / FR-11 / FR-29）。

chat-api 版本：与 admin-api / document-parser 的 `app/core/errors.py` 保持通用码同义同码
（跨服务一致性由 `tools/api_check/error_codes_uniqueness.py` 在 CI 校验）。
chat-api 专属命名空间：`api.chat.*`。

兼容层说明同 admin-api：响应体在 US2 收敛前同时携带 `detail`（字符串）与 `message`
（chat-api 既有 envelope 消费方依赖）。
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiErrorCode(str, Enum):
    """稳定错误码枚举（FR-11）。通用码与其他服务逐字一致。"""

    INTERNAL_ERROR = "api.internal_error"
    NOT_FOUND = "api.not_found"
    METHOD_NOT_ALLOWED = "api.method_not_allowed"
    VALIDATION_ERROR = "api.validation_error"
    BAD_REQUEST = "api.bad_request"
    UNAUTHORIZED = "api.unauthorized"
    FORBIDDEN = "api.forbidden"
    CONFLICT = "api.conflict"
    RATE_LIMITED = "api.rate_limited"
    PAYLOAD_TOO_LARGE = "api.payload_too_large"
    UNSUPPORTED_MEDIA_TYPE = "api.unsupported_media_type"
    NOT_ACCEPTABLE = "api.not_acceptable"
    PRECONDITION_FAILED = "api.precondition_failed"
    SERVICE_UNAVAILABLE = "api.service_unavailable"
    PARTIAL_FAILURE = "api.partial_failure"


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
    model_config = ConfigDict(extra="ignore")

    field: str | None = None
    path: str | None = None
    message: str


class ErrorResponse(BaseModel):
    """统一错误响应结构（FR-10），映射 RFC 9457（OQ-1 决策）。

    RFC 9457 键（type/title/status/instance/error_detail）与 MOGO 兼容键
    （code/message/http_status/trace_id/detail/fields/...）**并存**，以兼容
    `/browser/recording/stream` 等旧消费方依赖的 RFC 7807 语义。这些字段全部
    可选，OpenAPI 暴露它们后探针（025 T047）才能确认「实测字段 ⊆ 声明字段」。
    """

    model_config = ConfigDict(extra="ignore")

    code: str = Field(..., examples=["api.not_found"])
    message: str
    http_status: int
    trace_id: str
    detail: dict[str, Any] | None = None
    fields: list[ErrorFieldDetail] | None = None
    field: str | None = None
    path: str | None = None
    docs_url: str | None = None
    # RFC 9457 / RFC 7807 兼容键（由 build_error_payload 填充）
    type: str | None = Field(default=None, description="RFC 9457 problem type（未指定时 about:blank）")
    title: str | None = None
    status: int | None = None
    instance: str | None = None
    error_detail: dict[str, Any] | None = Field(
        default=None, description="RFC 7807 语义的 detail 别名（与 MOGO detail 并存）"
    )


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
    """组装对外错误体（RFC 9457 键 + 既有兼容键并存）。"""
    code_value = code.value if isinstance(code, ApiErrorCode) else str(code)
    normalized_fields: list[dict[str, Any]] | None = None
    if fields is not None:
        normalized_fields = [
            item.model_dump(exclude_none=True) if isinstance(item, ErrorFieldDetail) else dict(item)
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
    payload["type"] = docs_url or "about:blank"
    payload["title"] = code_value
    payload["status"] = http_status
    payload["instance"] = docs_url
    if isinstance(payload.get("detail"), dict) or "detail" not in payload:
        payload["error_detail"] = payload.get("detail")
    payload["detail"] = message
    return {k: v for k, v in payload.items() if v is not None or k in ("detail", "message")}
