"""025 T044 — `API-Version` 响应头中间件（FR-27 / QF-264）。

行为（对齐 `docs/api-versioning.md` §2.2）：
1. 每个响应注入 `API-Version: <契约版本>`，让客户端随时知道当前响应对应的 API 版本，
   避免把「新版字段」当「旧版不存在」或反之。
2. 请求可带 `X-API-Version` 声明期望的 minor 版本；服务端**不因此拒绝请求**
   （避免脆性，见文档 §2.2），只保证响应头反映服务端实际契约版本，供客户端自行比对。

版本号口径：`API_VERSION` 是本服务的**契约版本**（对外 API 语义），**唯一主副本**是
`specs/025-api-contract-hardening/contracts/admin-api.yaml` 的顶层 `version` 字段。
改动契约版本时必须同步修改本常量（见 `docs/api-versioning.md` §5 升级流程）。
注意：本常量与服务 `pyproject.toml` 的发布版本是两套独立版本号，不要混用。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

API_VERSION_HEADER = "API-Version"
REQUEST_VERSION_HEADER = "X-API-Version"

# 契约版本（与 contracts/admin-api.yaml 顶层 version 保持一致）。
API_VERSION = "1.0.0"


class ApiVersionMiddleware(BaseHTTPMiddleware):
    """给所有响应注入 `API-Version` 响应头。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers[API_VERSION_HEADER] = API_VERSION
        return response
