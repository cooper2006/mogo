"""026 T042/T043 — 限流与背压中间件（FR-28）。

* ``RateLimitMiddleware``：令牌桶限流（默认 1000 rps/实例，可配），超限返回
  ``429`` + ``Retry-After`` 头。守卫复用 vendored ``app.common.dependency_guard``
  的 ``RateLimiter``（与 T042 要求一致，避免重复实现）。
* ``BackpressureMiddleware``：在途请求守卫（有界队列思想），队列满返回
  ``503`` + ``Retry-After``，不阻塞新请求，也不排进无界队列。

守卫实现来自 vendored ``dependency_guard``，本模块仅做 ASGI 接入层。
"""

from __future__ import annotations

import logging
import math
from typing import Any, Callable, Optional

try:
    from app.common.dependency_guard import BackpressureGuard, RateLimiter
except ImportError:  # 权威源直接运行（单测 / 非镜像路径）
    from dependency_guard import BackpressureGuard, RateLimiter  # type: ignore

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

DEFAULT_RATE_LIMIT_RPS = 1000.0
DEFAULT_BURST = 2000
DEFAULT_MAX_CONCURRENT = 500
DEFAULT_MAX_DEPTH = 1000  # 队列深度上限（Clarify 定值 1000）


def _problem_json(status: int, title: str, detail: str, extra: Optional[dict] = None) -> dict:
    body = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
    }
    if extra:
        body.update(extra)
    return body


class RateLimitMiddleware(BaseHTTPMiddleware):
    """令牌桶限流：超限 429 + Retry-After。

    按 ``key_func`` 识别的维度（默认按租户/客户端 IP）限流；每副本独立计数，
    多副本总量 = 副本数 × 单副本限额（与 dependency_guard 口径一致）。
    """

    def __init__(
        self,
        app: Any,
        *,
        limiter: Optional[Any] = None,
        key_func: Optional[Callable[[Request], str]] = None,
        rps: float = DEFAULT_RATE_LIMIT_RPS,
        burst: int = DEFAULT_BURST,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
    ) -> None:
        super().__init__(app)
        self._limiter = limiter or RateLimiter(
            qps=rps, burst=burst, max_concurrent=max_concurrent
        )
        self._key_func = key_func or _default_key

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        key = self._key_func(request) or "anon"
        decision = self._limiter.acquire(key)
        if not decision.allowed:
            retry = max(1, math.ceil(float(getattr(decision, "retry_after_seconds", 0.0) or 0.0)))
            logger.warning(
                "rate limit exceeded",
                extra={"event": "perf.rate_limited", "key": key, "retry_after": retry},
            )
            return JSONResponse(
                _problem_json(
                    429,
                    "Rate limit exceeded",
                    f"rate limit for {key} exceeded; retry after {retry}s",
                    {"limit": float(getattr(decision, "limit", self._limiter.qps))},
                ),
                status_code=429,
                headers={"Retry-After": str(retry), "X-RateLimit-Limit": str(int(self._limiter.qps))},
            )
        try:
            return await call_next(request)
        finally:
            self._limiter.release(key)

    @property
    def inflight(self) -> int:
        return self._limiter.inflight("*") + sum(
            self._limiter.inflight(k) for k in getattr(self._limiter, "_inflight", {})
        )


class BackpressureMiddleware(BaseHTTPMiddleware):
    """在途请求守卫：队列满 503 + Retry-After，不阻塞新请求。"""

    def __init__(
        self,
        app: Any,
        *,
        guard: Optional[Any] = None,
        max_depth: int = DEFAULT_MAX_DEPTH,
        name: str = "api",
    ) -> None:
        super().__init__(app)
        self._guard = guard or BackpressureGuard(name=name, max_depth=max_depth)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._guard.try_enter():
            logger.warning(
                "backpressure: queue full, rejecting",
                extra={
                    "event": "perf.backpressure_rejected",
                    "guard": self._guard.name,
                    "depth": self._guard.depth,
                    "max_depth": self._guard.max_depth,
                },
            )
            return JSONResponse(
                _problem_json(
                    503,
                    "Service temporarily unavailable",
                    f"in-flight queue full ({self._guard.depth}/{self._guard.max_depth}); retry later",
                    {"depth": self._guard.depth, "max_depth": self._guard.max_depth},
                ),
                status_code=503,
                headers={"Retry-After": "1", "X-Backpressure-Depth": str(self._guard.depth)},
            )
        try:
            return await call_next(request)
        finally:
            self._guard.leave()

    @property
    def depth(self) -> int:
        return self._guard.depth


def _default_key(request: Request) -> str:
    """默认限流维度：租户 → 客户端 IP。"""
    tenant = request.headers.get("x-tenant-id") or request.headers.get("x-tenant-id-header")
    if tenant:
        return f"tenant:{tenant}"
    client = request.client.host if request.client else "unknown"
    return f"ip:{client}"


__all__ = [
    "RateLimitMiddleware",
    "BackpressureMiddleware",
    "DEFAULT_RATE_LIMIT_RPS",
    "DEFAULT_BURST",
    "DEFAULT_MAX_CONCURRENT",
    "DEFAULT_MAX_DEPTH",
]