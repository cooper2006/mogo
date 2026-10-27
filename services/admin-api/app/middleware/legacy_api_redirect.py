"""025 T045 — 旧路径 → `/v1` 重定向中间件（FR-27 / QF-264）。

背景：路由主版本迁移到 `/api/v1/...` 后（`main.py` 的 `include_router(..., prefix="/api/v1")`），
旧路径 `/api/...` 已不再挂业务路由。为了让存量消费方（前端 base url 仍为 `/api`、
跨服务回调、探针）在迁移窗口内无感工作，本中间件把旧路径永久重定向到新路径。

重定向语义（对齐 `docs/api-versioning.md` §2.1「旧路径保留 301」）：
- `GET` / `HEAD` → **301 Moved Permanently**（符合任务原文；浏览器默认跟随并保留方法）
- 其他方法（`POST` / `PUT` / `PATCH` / `DELETE` 等）→ **308 Permanent Redirect**
  —— 原因是 301 对非 GET 的语义未定义，多数客户端会把它转成 `GET` 重发，
  **导致写操作丢失**（例如 `POST /api/sessions` 变成 `GET /api/v1/sessions`）。
  308 明确要求客户端保留方法与请求体重发，才能保证写操作向后兼容。

排除范围：`/api/v1/...` 本身（已是新路径）与 `/health` 等不带 `/api` 前缀的路由
（不匹配，直接放行）。

反代前缀（2026-10-27 修）：服务被挂在 `/admin-api`、`/askai-api` 这类前缀下时，
网关会剥掉前缀再转发，中间件看到的 path 只有 `/api/...`。若 Location 直接写
`/api/v1/...`，浏览器跟随后会落到网关的 `location /api/`（chat-api），
admin 的 `/api/v1/setup/status` 因此 404 —— 请求串到了另一个服务。
网关通过 `X-Forwarded-Prefix` 告知原始前缀，Location 必须带回去。
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
