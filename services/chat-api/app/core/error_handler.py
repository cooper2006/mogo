"""025 T005 — chat-api 统一异常处理器（FR-10 / FR-11 / FR-12）。

接管 422（RequestValidationError）与 500（未处理 Exception）；路由内显式
`HTTPException` 形状不变（属 T011 范围）。与既有行为的兼容点：
- 旧响应是 `{"code": -1, "message": ...}`；新结构 `code` 为**稳定字符串错误码**（FR-11
  明确废弃数值 code），`message` 保留同键同义。数值 `code` 的移除即本特性要修的契约缺陷，
  属预期变更；`message`/`detail` 双键保证纯文本消费方不破。
- 生产环境不回显异常详情（FR-12），与 QF-447/449 口径一致。
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import ApiErrorCode, build_error_payload
from app.middleware.trace_id import TRACE_ID_HEADER, get_trace_id

logger = logging.getLogger(__name__)

_MAX_FIELD_ERRORS = 50


def _validation_fields(exc: RequestValidationError) -> list[dict]:
    items: list[dict] = []
    for err in exc.errors()[:_MAX_FIELD_ERRORS]:
        loc = err.get("loc") or ()
        field_name = str(loc[-1]) if loc else None
        path = ".".join(str(part) for part in loc) or None
        items.append(
            {
                "field": field_name,
                "path": path,
                "message": str(err.get("msg", "")),
                "type": str(err.get("type", "")),
            }
        )
    return items


def _tenant_id_required_exc() -> type:
    """惰性导入 ``TenantIdRequiredError``，避免与 billing 初始化顺序耦合。"""
    from app.core.billing import TenantIdRequiredError

    return TenantIdRequiredError


def register_error_handlers(app: FastAPI, *, is_prod: bool) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = _validation_fields(exc)
        first = fields[0] if fields else None
        trace_id = get_trace_id(request)
        logger.info(
            "request validation failed path=%s code=api.validation_error trace_id=%s",
            request.url.path,
            trace_id,
        )
        return JSONResponse(
            status_code=422,
            content=build_error_payload(
                code=ApiErrorCode.VALIDATION_ERROR,
                message="Request validation failed",
                http_status=422,
                trace_id=trace_id,
                detail={"errors": fields},
                fields=fields,
                field=first["field"] if first else None,
                path=first["path"] if first else None,
            ),
        )

    # 058 T021/T022：tenant_id 缺省必须映射为 400，而非落入通用 Exception handler
    # 返回 500（或更早的 200 兜底）。此处用惰性导入避免与 billing 模块的初始化顺序耦合。
    @app.exception_handler(_tenant_id_required_exc())
    async def _tenant_id_required_handler(request: Request, exc: Exception) -> JSONResponse:
        trace_id = get_trace_id(request)
        logger.warning(
            "tenant_id required path=%s code=tenant_id_required trace_id=%s",
            request.url.path,
            trace_id,
        )
        return JSONResponse(
            status_code=400,
            content=build_error_payload(
                code=getattr(exc, "code", "tenant_id_required"),
                message=str(exc) or "tenant_id is required",
                http_status=400,
                trace_id=trace_id,
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception: %s", exc)
        trace_id = get_trace_id(request)
        message = "Internal server error" if is_prod else str(exc)
        return JSONResponse(
            status_code=500,
            content=build_error_payload(
                code=ApiErrorCode.INTERNAL_ERROR,
                message=message,
                http_status=500,
                trace_id=trace_id,
            ),
            # 500 响应由 ServerErrorMiddleware（最外层）产出，中间件链的
            # X-Trace-ID 回写不经过它——必须在此显式携带。
            headers={TRACE_ID_HEADER: trace_id},
        )
