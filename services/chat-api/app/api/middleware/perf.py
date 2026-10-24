"""026 T004 — 性能埋点中间件骨架。

占位模块，Phase 2（US1）填充实现。
目标：请求延迟埋点 → `RuntimeKPIStore`，与 025 追踪中间件并存。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class PerfMiddleware(BaseHTTPMiddleware):
    """性能埋点中间件占位。

    Phase 2 实现时：
    - 记录请求开始/结束时间，计算延迟
    - 按端点聚合延迟分位数，写入 `RuntimeKPIStore`
    - 与 025 trace_id 中间件并存（独立埋点，不替换）
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """占位：直接放行，不记录性能数据。"""
        return await call_next(request)
