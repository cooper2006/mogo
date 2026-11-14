"""023 T087 — 限流 + 背压 ASGI 中间件（三服务共用，vendored 副本）。

设计约束（为什么是纯 ASGI 而不是 `BaseHTTPMiddleware`）：

* `BaseHTTPMiddleware` 会为每个请求额外开一个 anyio task + 队列，p95 直接涨
  几十毫秒；本特性的性能预算要求入口中间件开销 **< 5ms**，故直接实现
  `__call__(scope, receive, send)`。
* 本模块**不 import** 兄弟 vendored 模块（`dependency_guard` 等）：vendored
  副本只在 `app/common/` 下同包，权威源 `services/common/` 没有包结构，
  跨模块 import 会在字节一致性校验/直接引用两种布局下表现不一致。因此
  `rate_limiter` 与 `backpressure` 由调用方注入，靠协议（鸭子类型）协作。

拒绝语义（FR-25）：超限返回 **429 Too Many Requests** 且带 `Retry-After`，
不是无声排队 —— 排队会把内存堆到 OOM，比直接拒绝更糟。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

#: 默认豁免路径：探针与管理端点不能受限流影响，否则过载时连"我过载了"都报不出去。
DEFAULT_EXEMPT_PATHS: tuple[str, ...] = (
    "/health",
    "/healthz",
    "/ready",
    "/live",
    "/metrics",
)

#: 限流键的候选请求头（第一个非空者生效）。
TENANT_HEADERS: tuple[bytes, ...] = (b"x-tenant-id", b"x-mogo-tenant", b"x-org-id")

RATE_LIMITED_CODE = "rate_limited"
BACKPRESSURE_CODE = "backpressure_exceeded"


class ResilienceMiddleware:
    """按租户限流（速率 + 并发）并按在途量背压的纯 ASGI 中间件。

    参数任一为 ``None`` 时对应能力关闭，便于按服务选择性启用。
    """

    def __init__(
        self,
        app: Any,
        *,
        service_name: str = "service",
        rate_limiter: Any | None = None,
        backpressure: Any | None = None,
        exempt_paths: Iterable[str] = DEFAULT_EXEMPT_PATHS,
        enabled: bool = True,
        on_reject: Callable[[str], None] | None = None,
    ) -> None:
        self.app = app
        self.service_name = service_name
        self.rate_limiter = rate_limiter
        self.backpressure = backpressure
        self.exempt_paths = tuple(exempt_paths)
        self.enabled = enabled
        self.on_reject = on_reject

    # ── 内部工具 ────────────────────────────────────────────────
    def _is_exempt(self, path: str) -> bool:
        if path in self.exempt_paths:
            return True
        return any(
            p.endswith("/") is False and path.startswith(p + "/") for p in self.exempt_paths
        )

    @staticmethod
    def _scope_headers(scope: dict[str, Any]) -> dict[bytes, bytes]:
        return {k.lower(): v for k, v in scope.get("headers") or []}

    def _limit_key(self, scope: dict[str, Any], headers: dict[bytes, bytes]) -> str:
        for name in TENANT_HEADERS:
            value = headers.get(name)
            if value:
                return value.decode("latin-1").strip()[:128]
        client = scope.get("client")
        if client:
            return f"ip:{client[0]}"
        return "anonymous"

    @staticmethod
    def _trace_id(scope: dict[str, Any]) -> str:
        state = scope.get("state") or {}
        return str(state.get("trace_id") or "")

    def _record_reject(self, reason: str) -> None:
        if self.on_reject is None:
            return
        try:
            self.on_reject(reason)
        except Exception:  # noqa: BLE001 - 指标失败不能影响拒绝路径
            logger.debug("resilience on_reject hook failed", exc_info=True)

    async def _reject(
        self,
        send: Callable[..., Any],
        *,
        code: str,
        message: str,
        retry_after: float,
        scope: dict[str, Any],
    ) -> None:
        retry_after_int = max(1, int(round(retry_after or 1.0)))
        payload = {
            "error": {
                "code": code,
                "message": message,
                "service": self.service_name,
                "retry_after_seconds": retry_after_int,
                "trace_id": self._trace_id(scope),
            }
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
            (b"retry-after", str(retry_after_int).encode()),
        ]
        await send(
            {"type": "http.response.start", "status": 429, "headers": headers}
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})

    # ── ASGI 入口 ───────────────────────────────────────────────
    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if (
            not self.enabled
            or scope.get("type") != "http"
            or self._is_exempt(scope.get("path", ""))
            or (self.rate_limiter is None and self.backpressure is None)
        ):
            await self.app(scope, receive, send)
            return

        # 背压先于限流：在途量已经打满时，连"要不要给令牌"都不必算。
        entered = False
        if self.backpressure is not None:
            if not self.backpressure.try_enter():
                self._record_reject(BACKPRESSURE_CODE)
                await self._reject(
                    send,
                    code=BACKPRESSURE_CODE,
                    message="service is saturated, please retry later",
                    retry_after=1.0,
                    scope=scope,
                )
                return
            entered = True

        key = ""
        try:
            if self.rate_limiter is not None:
                headers = self._scope_headers(scope)
                key = self._limit_key(scope, headers)
                decision = self.rate_limiter.acquire(key)
                if not decision.allowed:
                    self._record_reject(RATE_LIMITED_CODE)
                    await self._reject(
                        send,
                        code=RATE_LIMITED_CODE,
                        message=f"rate limit exceeded ({decision.reason})",
                        retry_after=getattr(decision, "retry_after_seconds", 1.0),
                        scope=scope,
                    )
                    return
            await self.app(scope, receive, send)
        finally:
            if self.rate_limiter is not None and key:
                self.rate_limiter.release(key)
            if entered:
                self.backpressure.leave()


def build_resilience_middleware(
    *,
    service_name: str,
    rate_limit_qps: float = 20.0,
    max_concurrent: int = 100,
    max_queue_depth: int = 1000,
    enabled: bool = True,
    on_reject: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """构造 ``add_middleware()`` 所需的 kwargs。

    延迟导入 :mod:`dependency_guard` —— 见模块 docstring 的 vendoring 约束，
    这里用**绝对包路径** ``app.common.dependency_guard``，因为该函数只会在
    服务进程内被调用（权威源不执行）。
    """
    from app.common.dependency_guard import BackpressureGuard, RateLimiter

    return {
        "service_name": service_name,
        "rate_limiter": RateLimiter(qps=rate_limit_qps, burst=int(max(1, rate_limit_qps * 2)),
                                    max_concurrent=max_concurrent),
        "backpressure": BackpressureGuard(f"{service_name}:inbound", max_depth=max_queue_depth),
        "enabled": enabled,
        "on_reject": on_reject,
    }


__all__ = [
    "BACKPRESSURE_CODE",
    "DEFAULT_EXEMPT_PATHS",
    "RATE_LIMITED_CODE",
    "ResilienceMiddleware",
    "TENANT_HEADERS",
    "build_resilience_middleware",
]
