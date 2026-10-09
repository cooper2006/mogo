"""Distributed lock guarding Runtime Host creation across replicas (§ M2).

Every Runtime Host keeps its kernel state in process memory, so without a
coordination point each replica will happily create its own runtime for the
same isolation key, and tenant state silently forks across the pool. This
lock serialises the *creation* of a runtime for one isolation key across all
chat-api instances and Runtime Host replicas behind the LB.

Design:

- The lock is a plain Redis ``SET key value NX EX ttl`` with a random value
  per acquisition, released by a Lua script that compares the value before
  deleting. That means an expiring lock can never be stolen by a late
  ``release`` from an instance whose own lock has already timed out.
- The lock only serialises *creation*. A holder that cannot create (because a
  concurrent holder already did) must ``discover`` the existing runtime
  instead of waiting, which is what the coordinator already does on
  ``DshRuntimeError``.
- When Redis is unavailable the lock degrades to a no-op: creation falls
  back to the pre-lock behaviour (create, then discover on conflict), which
  is exactly what the pool did before M2. The degradation is logged so it is
  observable.

The lock is intentionally short (default 30s, well below the 5s chat-api
health probe interval is not required -- creation is a fast HTTP call). A
holder that crashes mid-creation simply leaks the lock until it expires,
which is safe because ``create_runtime`` is idempotent per isolation key on
the host side (the host rejects a second create with the same key) and the
discovery fallback recovers the winner's runtime.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_KEY_PREFIX = "mogo:dsh:runtime:"
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class RuntimeLock:
    """Best-effort Redis-backed creation lock for Runtime Host runtimes."""

    def __init__(
        self,
        redis_url: str | None = None,
        *,
        key_prefix: str = _KEY_PREFIX,
        ttl_seconds: float = 30.0,
    ) -> None:
        self._prefix = key_prefix
        self._ttl = int(ttl_seconds)
        self._redis: Any = None
        if redis_url:
            try:
                import redis as _redis_mod

                self._redis = _redis_mod.Redis.from_url(
                    redis_url,
                    socket_timeout=2,
                    socket_connect_timeout=2,
                    health_check_interval=30,
                    decode_responses=True,
                )
                self._redis.ping()
                logger.info(
                    "runtime creation lock connected to Redis",
                    extra={"event": "dsh.runtime_lock.redis_ready"},
                )
            except Exception:
                logger.warning(
                    "runtime creation lock: Redis unavailable, creation is "
                    "uncoordinated across replicas (pre-M2 behaviour)",
                    extra={"event": "dsh.runtime_lock.redis_unavailable"},
                )
                self._redis = None

    @property
    def enabled(self) -> bool:
        return self._redis is not None

    def _key(self, isolation_key: str) -> str:
        return f"{self._prefix}{isolation_key}"

    def acquire(self, isolation_key: str) -> str | None:
        """Try to take the creation lock.

        Returns the token to pass to :meth:`release`, or ``None`` when the
        lock is held by someone else or the lock backend is unavailable. A
        ``None`` here must be treated by the caller as "proceed without
        coordination" (discover after a failed create), never as a failure.
        """
        if self._redis is None or not isolation_key:
            return None
        token = uuid.uuid4().hex
        try:
            acquired = self._redis.set(
                self._key(isolation_key),
                token,
                nx=True,
                ex=self._ttl,
            )
            return token if acquired else None
        except Exception:
            logger.warning(
                "runtime creation lock acquire failed; proceeding uncoordinated",
                extra={
                    "event": "dsh.runtime_lock.acquire_failed",
                    "isolation_key": isolation_key,
                },
            )
            return None

    def release(self, isolation_key: str, token: str) -> None:
        """Release the lock we acquired.

        Only deletes the key when its value still equals our token (Lua
        script), so a late release after a TTL expiry can never clear a lock
        a concurrent holder took in the meantime.
        """
        if self._redis is None or not token:
            return
        try:
            self._redis.eval(_RELEASE_SCRIPT, 1, self._key(isolation_key), token)
        except Exception:
            logger.warning(
                "runtime creation lock release failed; the lock will expire "
                "by its TTL",
                extra={
                    "event": "dsh.runtime_lock.release_failed",
                    "isolation_key": isolation_key,
                },
            )
