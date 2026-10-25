"""025 FR-13 (T024)：通用限流中间件（QF-237, QF-238, QF-239）。

Redis 滑动窗口（ZSET 按时间戳），多维度并发判定：
- 维度：``ip`` / ``tenant`` / ``user`` / ``endpoint``（可配置，见 T025 yaml）。
- 超配额返回 **429** + ``Retry-After`` 头（秒）；响应体 ``detail`` 含
  ``limit`` / ``remaining`` / ``window`` / ``reset_at`` / ``dimension``
  （可解析的重试提示 + 配额余额说明），code 用 T001 注册表风格 ``RATE_LIMITED``。
- Redis 不可用降级进程内存（单实例）；熔断器打开按「不限流」降级（不误杀业务）。
- 实现为纯 ASGI 中间件（不用 ``BaseHTTPMiddleware``），本轮**未挂载**到
  admin-api app，留待 T048 统一装配。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Optional

from app.config.rate_limit import RateLimitConfig, RateLimitRule, load_rate_limit_config

logger = logging.getLogger(__name__)

_RATE_LIMIT_CODE = "RATE_LIMITED"


# ── 计数存储：Redis ZSET 滑动窗口（内存后备） ────────────────────────────────


class RateLimitStore:
    """滑动窗口计数器。

    - Redis：ZSET，score 为时间戳；``hit()`` 先清理窗口外元素再统计。
    - 内存后备：``{key: [timestamps]}``（单实例）。
    """

    def __init__(
        self,
        redis_url: str | None = None,
        key_prefix: str = "mogo:rate_limit:",
    ) -> None:
        self._prefix = key_prefix
        self._redis: Any = None
        self._fallback: dict[str, list[float]] = {}

        if redis_url:
            try:
                import redis as _redis_mod

                self._redis = _redis_mod.Redis.from_url(
                    redis_url,
                    socket_timeout=2,
                    socket_connect_timeout=2,
                    health_check_interval=30,
                )
                self._redis.ping()
                from app.core import resilience

                resilience.register_redis_pool(self._redis)
                logger.info("RateLimitStore connected to Redis")
            except Exception:
                logger.warning(
                    "RateLimitStore: Redis unavailable at %s, falling back to in-memory "
                    "(single-instance only — multi-instance deployment requires Redis)",
                    redis_url[:40],
                )
                self._redis = None

    @property
    def backend(self) -> str:
        return "redis" if self._redis else "memory"

    def hit(self, key: str, rule: RateLimitRule) -> dict[str, Any]:
        """记录一次请求并返回判定结果。

        返回 ``{"allowed", "remaining", "reset_at", "limit", "window"}``。
        """
        now = time.time()
        window_start = now - rule.window
        full_key = f"{self._prefix}{key}"

        if self._redis:
            from app.core import resilience

            resilience.redis_call(self._redis.zremrangebyscore, full_key, 0, window_start)
            count = int(resilience.redis_call(self._redis.zcount, full_key, window_start, now))
            if count < rule.limit:
                resilience.redis_call(self._redis.zadd, full_key, {str(now): now})
                resilience.redis_call(self._redis.expire, full_key, rule.window + 10)
                return {
                    "allowed": True,
                    "remaining": rule.limit - count - 1,
                    "reset_at": window_start + rule.window,
                    "limit": rule.limit,
                    "window": rule.window,
                }
            # 超配额：窗口内最早一次的时间戳 + window 即恢复时刻。
            oldest = resilience.redis_call(
                self._redis.zrange, full_key, 0, 0, withscores=True
            )
            reset_at = window_start + rule.window
            if oldest:
                reset_at = float(oldest[0][1]) + rule.window
            return {
                "allowed": False,
                "remaining": 0,
                "reset_at": reset_at,
                "limit": rule.limit,
                "window": rule.window,
            }

        # 内存后备
        stamps = self._fallback.get(key, [])
        recent = [t for t in stamps if t >= window_start]
        if len(recent) < rule.limit:
            recent.append(now)
            self._fallback[key] = recent
            return {
                "allowed": True,
                "remaining": rule.limit - len(recent),
                "reset_at": window_start + rule.window,
                "limit": rule.limit,
                "window": rule.window,
            }
        self._fallback[key] = recent
        return {
            "allowed": False,
            "remaining": 0,
            "reset_at": min(recent) + rule.window if recent else window_start + rule.window,
            "limit": rule.limit,
            "window": rule.window,
        }

    def close(self) -> None:
        if self._redis:
            try:
                self._redis.close()
            except Exception:
                pass
            self._redis = None


# ── ASGI 中间件 ──────────────────────────────────────────────────────────────


class RateLimitMiddleware:
    """限流 ASGI 中间件。

    参数
    ----
    config:
        限流配置；未提供时在实例化时加载一次（``load_rate_limit_config``）。
    store:
        计数存储；未提供时内建（读 ``settings.redis_url``）。
    dimensions:
        生效维度子集；未提供时用配置里的全部维度。
    """

    def __init__(
        self,
        app: Callable[[dict[str, Any], Any, Any], Awaitable[None]],
        config: RateLimitConfig | None = None,
        store: RateLimitStore | None = None,
        dimensions: tuple[str, ...] | None = None,
    ) -> None:
        self.app = app
        self.config = config if config is not None else load_rate_limit_config()
        self.store = store if store is not None else _default_store()
        self._dimensions = tuple(dimensions) if dimensions else self.config.dimensions_sorted()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")
        identities = _identities(scope)

        for dimension in self._dimensions:
            rule = self.config.rule_for(dimension, path)
            if rule is None:
                continue
            ident = identities.get(dimension)
            if not ident:
                continue
            key = f"{dimension}:{ident}"
            try:
                result = self.store.hit(key, rule)
            except Exception:
                # 熔断器打开 / Redis 异常：按「不限流」降级，放行下游。
                logger.warning("RateLimitMiddleware: store unavailable, skipping limit for %s", key)
                continue
            if not result["allowed"]:
                await _respond_429(send, result, dimension)
                return

        await self.app(scope, receive, send)


# ── 模块级默认 store（懒加载） ──────────────────────────────────────────────

_default_store_instance: Optional[RateLimitStore] = None


def _default_store() -> RateLimitStore:
    global _default_store_instance
    if _default_store_instance is None:
        from app.core.config import settings

        _default_store_instance = RateLimitStore(redis_url=settings.redis_url or None)
    return _default_store_instance


def reset_default_store() -> None:
    """测试用：清空模块级默认 store。"""
    global _default_store_instance
    _default_store_instance = None


def _identities(scope: dict[str, Any]) -> dict[str, str]:
    """从 scope 提取各维度标识。"""
    state = scope.get("state") or {}
    client = scope.get("client") or (None, None)
    return {
        "ip": str(client[0] or "unknown"),
        "tenant": str(state.get("tenant_id") or "anon"),
        "user": str(state.get("user_id") or "anon"),
        "endpoint": str(scope.get("path", "/")),
    }


async def _respond_429(send: Any, result: dict[str, Any], dimension: str) -> None:
    import json

    retry_after = max(1, int(result["reset_at"] - time.time()) + 1)
    reset_iso = datetime.fromtimestamp(result["reset_at"], tz=timezone.utc).isoformat()
    payload = json.dumps(
        {
            "detail": {
                "code": _RATE_LIMIT_CODE,
                "message": "请求频率超限，请稍后重试",
                "limit": result["limit"],
                "remaining": result["remaining"],
                "window": result["window"],
                "reset_at": reset_iso,
                "dimension": dimension,
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(payload)).encode("ascii")),
                (b"retry-after", str(retry_after).encode("ascii")),
                (b"x-ratelimit-limit", str(result["limit"]).encode("ascii")),
                (b"x-ratelimit-remaining", str(result["remaining"]).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})