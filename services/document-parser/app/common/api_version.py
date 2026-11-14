"""API-Version 响应头中间件（025 T044 / 059 T018-T019 跨服务复用）。

行为（对齐 docs/api-versioning.md §2.2）：
1. 每个响应注入 ``API-Version: <version>``，让客户端随时知道当前响应对应的
   API 契约版本，避免把「新版字段」当「旧版不存在」或反之。
2. 请求可带 ``X-API-Version`` 声明期望的 minor 版本；服务端**不因此拒绝请求**
   （避免脆性），只保证响应头反映服务端实际契约版本，供客户端自行比对。

``version`` 由构造参数传入，是各服务的**契约版本**（对外 API 语义），与
服务 ``pyproject.toml`` 的发布版本是两套独立版本号，不要混用。改动契约版本时
须同步更新各服务的 ``contracts/*.yaml`` 顶层 ``version`` 字段与本项目发布流程。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

API_VERSION_HEADER = "API-Version"
REQUEST_VERSION_HEADER = "X-API-Version"


class ApiVersionMiddleware(BaseHTTPMiddleware):
    """给所有响应注入 ``API-Version`` 响应头（version 由构造参数指定）。"""

    def __init__(self, app, version: str = "1.0.0", dispatch=None) -> None:
        super().__init__(app, dispatch=dispatch)
        self._version = version

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers[API_VERSION_HEADER] = self._version
        return response
