"""025 T045 — 旧路径 → `/v1` 重定向中间件（FR-27 / QF-264）。

背景：路由主版本迁移到 `/api/v1/...` 后，旧路径 `/api/...` 已不再挂业务路由。
为了让存量消费方（前端 base url 仍为 `/api`、跨服务回调、探针）在迁移窗口内无感工作，
本中间件把旧路径永久重定向到新路径（口径见 `docs/api-versioning.md` §2.1）。

重定向语义：`GET`/`HEAD` → **301**（浏览器默认跟随并保留方法）；其他方法（`POST`/`PUT`/
`PATCH`/`DELETE`）→ **308**（301 对非 GET 语义未定义，多数客户端会转成 GET 重发导致写操作丢失；
308 明确保留方法与请求体）。排除 `/api/v1/...` 与不带 `/api` 前缀的路由。

反代前缀（2026-10-27 修）：服务被挂在 `/admin-api`、`/askai-api` 这类前缀下时，
网关会剥掉前缀再转发，中间件看到的 path 只有 `/api/...`。若 Location 直接写
`/api/v1/...`，浏览器跟随后会落到网关的 `location /api/`（chat-api），
`/askai-api` 与 `/admin-api` 的请求因此串到错误服务。网关通过
`X-Forwarded-Prefix` 告知原始前缀，Location 必须带回去。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

API_PREFIX = "/api"
V1_PREFIX = "/api/v1"
FORWARDED_PREFIX_HEADER = "x-forwarded-prefix"


def _safe_forwarded_prefix(request: Request) -> str:
    """取网关声明的反代前缀，只接受单段相对路径，避免被伪造成开放重定向。"""
    raw = (request.headers.get(FORWARDED_PREFIX_HEADER) or "").strip()
    if not raw or not raw.startswith("/"):
        return ""
    if any(token in raw for token in ("//", "..", "?", "#", "\\")):
        return ""
    return raw.rstrip("/")


class LegacyApiRedirectMiddleware(BaseHTTPMiddleware):
    """把旧 `/api/*` 请求永久重定向到新路径，并保留网关反代前缀。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        is_legacy = path == API_PREFIX or (
            path.startswith(API_PREFIX + "/") and not path.startswith(V1_PREFIX)
        )
        if not is_legacy:
            return await call_next(request)

        tail = path[len(API_PREFIX):] if path != API_PREFIX else ""
        target = V1_PREFIX + tail
        prefix = _safe_forwarded_prefix(request)
        if prefix:
            target = prefix + target
        if request.url.query:
            target += "?" + request.url.query
        status_code = 301 if request.method in ("GET", "HEAD") else 308
        return RedirectResponse(url=target, status_code=status_code)
