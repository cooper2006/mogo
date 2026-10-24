"""025 T005 — chat-api trace_id 中间件（FR-11）。

chat-api 已有 `request_logging_middleware` 生成 `http_request_id`；本中间件把
**跨服务统一的 `trace_id`** 与之打通：
- 上游带 `X-Trace-ID` 则沿用（服务间链路一致，023 追踪同样消费该值）；
- 否则新生成，并同时写入 `request_context`（observability context 的 `trace_id` 字段，
  与 `http_request_id` 并存，不替换）；
- 响应头回写 `X-Trace-ID`。
"""
from __future__ import annotations

import uuid

from app.infrastructure.request_context import merge_request_context
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

TRACE_ID_HEADER = "X-Trace-ID"
REQUEST_ID_HEADER = "X-Request-ID"


def _generate_trace_id() -> str:
    return uuid.uuid4().hex


def resolve_trace_id(request: Request) -> str:
    """从 `X-Trace-ID` 头沿用上游 ID，或新生成；写入 request.state 与请求上下文。"""
    incoming = request.headers.get(TRACE_ID_HEADER)
    trace_id = incoming.strip()[:64] if incoming and incoming.strip() else _generate_trace_id()
    request.state.trace_id = trace_id

    # 与既有 observability 请求上下文打通：日志（current_log_context）自动带上 trace_id。
    merge_request_context({"trace_id": trace_id})
    return trace_id


def get_trace_id(request: Request) -> str:
    value = getattr(request.state, "trace_id", None)
    if isinstance(value, str) and value:
        return value
    header = request.headers.get(TRACE_ID_HEADER)
    if header:
        return header.strip()[:64]
    return "unknown"


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        trace_id = resolve_trace_id(request)
        response = await call_next(request)
        response.headers[TRACE_ID_HEADER] = trace_id
        return response
