"""025 T003 — 统一异常处理器（FR-10 / FR-11 / FR-12）。

接管范围（首期刻意收敛）：
- `RequestValidationError`（422）→ 统一结构 + 字段级定位（`fields`/`field`/`path`）。
- 未处理 `Exception`（500）→ 统一结构 + `trace_id`；生产环境不回显异常详情（FR-12，
  与 QF-447/449 既有口径一致）。

**不接管**路由内显式 `raise HTTPException` 的响应形状——那属于 T011 状态码语义整改，
需逐路由评审。旧 handler 的兼容键（`detail` 字符串）仍由 `build_error_payload` 提供。
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import ApiErrorCode, build_error_payload
from app.middleware.trace_id import TRACE_ID_HEADER, get_trace_id

logger = logging.getLogger(__name__)

# FR-12：422 的 loc 首两项通常是 ("body", field)，拼成 JSONPath 便于前端定位
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


def register_error_handlers(app: FastAPI, *, is_prod: bool) -> None:
    """把统一错误结构挂到 FastAPI app 上。

    ``is_prod=False``（dev/本地）时 500 的 message 保留异常文本便于调试——与既有
    QF-447/449 行为一致；生产环境固定通用文案（FR-12 不泄漏内部信息）。
    """

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
