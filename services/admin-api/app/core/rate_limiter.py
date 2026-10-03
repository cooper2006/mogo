"""QF-356: Redis-backed login rate limiter — supports multi-instance deployment.

Uses a Redis sorted set per rate-limit key to track failed login attempts
within a sliding window.  Falls back to an in-memory dict if Redis is
unreachable (development / single-instance mode).

API::

    limiter = RateLimiter(redis_url="redis://127.0.0.1:6379/0")
    if not limiter.check_and_record(key):
        raise HTTPException(429, "Too many requests")
"""

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window rate limiter backed by Redis (or in-memory fallback).

    Parameters
    ----------
    redis_url:
        Redis connection string.  If ``None`` or Redis is unreachable the
        limiter falls back to an in-process dict (single-instance only).
    window_seconds:
        Sliding window size in seconds.
    max_attempts:
        Maximum allowed attempts within the window before blocking.
    key_prefix:
        Redis key prefix for namespacing.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        window_seconds: int = 300,
        max_attempts: int = 5,
        key_prefix: str = "mogo:login_rl:",
    ) -> None:
        self._window = window_seconds
        self._max = max_attempts
        self._prefix = key_prefix
        self._redis = None
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
                # Verify connectivity.
                self._redis.ping()
                logger.info("RateLimiter connected to Redis")
            except Exception:
                logger.warning(
                    "RateLimiter: Redis unavailable at %s, falling back to in-memory "
                    "(single-instance only — multi-instance deployment requires Redis)",
                    redis_url[:40],
                )
                self._redis = None

    @property
    def backend(self) -> str:
        return "redis" if self._redis else "memory"

    def check(self, key: str) -> bool:
        """Return ``True`` if the key is within the rate limit.

        Does **not** record the attempt — call :meth:`record_failure` after
        a failed login.
        """
        now = time.time()
        window_start = now - self._window

        if self._redis:
            count = self._redis.zcount(self._full_key(key), window_start, now)
            return int(count) < self._max

        # In-memory fallback.
        attempts = self._fallback.get(key, [])
        recent = [t for t in attempts if t >= window_start]
        self._fallback[key] = recent
        return len(recent) < self._max

    def record_failure(self, key: str) -> None:
        """Record a failed login attempt for *key*."""
        now = time.time()

        if self._redis:
            self._redis.zadd(self._full_key(key), {str(now): now})
            # Expire the key after the window elapses.
            self._redis.expire(self._full_key(key), self._window + 10)
            return

        # In-memory fallback.
        attempts = self._fallback.get(key, [])
        attempts.append(now)
        self._fallback[key] = attempts

    def record_success(self, key: str) -> None:
        """Clear the rate-limit state after a successful login."""
        if self._redis:
            self._redis.delete(self._full_key(key))
            return

        self._fallback.pop(key, None)

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def close(self) -> None:
        """Release the Redis connection."""
        if self._redis:
            try:
                self._redis.close()
            except Exception:
                pass
            self._redis = None


# ── Module-level convenience ─────────────────────────────────────────────

_default_limiter: Optional[RateLimiter] = None


def get_default_limiter() -> RateLimiter:
    """Return the module-level default limiter (lazy singleton)."""
    global _default_limiter
    if _default_limiter is None:
        from app.core.config import settings

        _default_limiter = RateLimiter(
            redis_url=settings.redis_url or None,
            window_seconds=300,
            max_attempts=5,
        )
    return _default_limiter
