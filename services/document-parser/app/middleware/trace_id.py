"""025 T004 — `trace_id` 注入中间件（FR-11 / FR-29）。

行为：
1. 请求进入时取 `X-Trace-ID`（沿用上游已生成的 ID）；缺失则生成 UUID4 hex[:32]。
2. 写入 `request.state.trace_id`，供异常处理器 / 业务代码 / 日志上下文读取。
3. 响应头回写 `X-Trace-ID`，让网关与前端可关联；仅当上游未提供 `X-Request-ID` 时
   镜像写入该头（保留上游自己的请求关联 ID）。

命名口径：本特性统一使用 `trace_id`（025 OQ-1 决策）；007/023 复用同一字段。
注意：500 响应由 ServerErrorMiddleware（最外层）产出，不经过本中间件的回写——
统一异常处理器已在响应头显式携带 X-Trace-ID（见 app/core/error_handler.py）。
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

TRACE_ID_HEADER = "X-Trace-ID"
REQUEST_ID_HEADER = "X-Request-ID"


def _generate_trace_id() -> str:
    return uuid.uuid4().hex


def get_trace_id(request: Request) -> str:
    """读取当前请求的 trace_id；未经过中间件时回退请求头/占位符（绝不抛错）。

    异常处理器在中间件链之外被调用时也需要一个值，占位符保证响应结构完整
    （FR-10：`trace_id` 是必填字段）。
    """
    value = getattr(request.state, "trace_id", None)
    if isinstance(value, str) and value:
        return value
    header = request.headers.get(TRACE_ID_HEADER)
    if header:
        return header.strip()[:64]
    return "unknown"


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(TRACE_ID_HEADER)
        trace_id = incoming.strip()[:64] if incoming and incoming.strip() else _generate_trace_id()
        request.state.trace_id = trace_id

        response = await call_next(request)
        response.headers[TRACE_ID_HEADER] = trace_id
        if REQUEST_ID_HEADER not in request.headers:
            response.headers[REQUEST_ID_HEADER] = trace_id
        return response
