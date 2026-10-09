"""Session -> Runtime Host affinity cache (§12.4 option B).

A Runtime Host keeps kernel session state in process memory, so a session lives
on exactly one replica. The sticky LB normally routes by isolation key, but a
session can still land on the wrong replica: the hash ring reshuffles when a
replica is added or removed, and a replica restart drops its in-memory sessions
without any change to the ring. When that happens ``resume`` fails with
"session is not live" and nothing recovers it.

This cache records which replica answered "yes" to an ownership probe, so the
common path is a direct lookup instead of probing every replica per turn.

Storage is Redis with a TTL (an affinity record is an optimisation, not a
source of truth -- losing it costs a probe, never correctness). When Redis is
unreachable the cache degrades to a process-local dict, which is exactly the
pre-existing behaviour and therefore safe for single-instance deployments.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_KEY_PREFIX = "mogo:dsh:session_host:"


class SessionAffinityCache:
    """Best-effort ``kernel_session_id -> instance_id`` cache with TTL."""

    def __init__(
        self,
        redis_url: str | None = None,
        *,
        ttl_seconds: float = 7200.0,
        key_prefix: str = _KEY_PREFIX,
    ) -> None:
        self._ttl = float(ttl_seconds)
        self._prefix = key_prefix
        self._redis: Any = None
        self._fallback: dict[str, str] = {}
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
                    "session affinity cache connected to Redis",
                    extra={"event": "dsh.session_affinity.redis_ready"},
                )
            except Exception:
                logger.warning(
                    "session affinity cache: Redis unavailable, falling back to "
                    "in-process memory (single-instance semantics)",
                    extra={"event": "dsh.session_affinity.redis_unavailable"},
                )
                self._redis = None

    @property
    def backend(self) -> str:
        return "redis" if self._redis is not None else "memory"

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    def get(self, session_id: str) -> str | None:
        """Return the cached instance id for ``session_id``, if fresh."""
        if not session_id:
            return None
        key = self._key(session_id)
        if self._redis is not None:
            try:
                value = self._redis.get(key)
            except Exception:
                logger.warning(
                    "session affinity cache read failed; treating as miss",
                    extra={"event": "dsh.session_affinity.read_failed"},
                )
                return None
            return str(value) if value else None
        return self._fallback.get(session_id)

    def set(self, session_id: str, instance_id: str) -> None:
        """Record that ``instance_id`` holds ``session_id``."""
        if not session_id or not instance_id:
            return
        if self._redis is not None:
            try:
                self._redis.set(self._key(session_id), instance_id, ex=int(self._ttl))
                return
            except Exception:
                logger.warning(
                    "session affinity cache write failed; using in-process memory",
                    extra={"event": "dsh.session_affinity.write_failed"},
                )
        self._fallback[session_id] = instance_id

    def forget(self, session_id: str) -> None:
        """Drop a stale record (for example after the owning replica restarted)."""
        if not session_id:
            return
        if self._redis is not None:
            try:
                self._redis.delete(self._key(session_id))
            except Exception:
                logger.warning(
                    "session affinity cache delete failed",
                    extra={"event": "dsh.session_affinity.delete_failed"},
                )
        self._fallback.pop(session_id, None)


__all__ = ["SessionAffinityCache"]
