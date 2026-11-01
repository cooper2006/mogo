"""FR-006: resolve a Session's project_id from the authoritative kernel binding.

The model plugin carries the DSH session id in ``request.sessionId``. That id is
the same value the runtime stores as ``kernel_session_id`` in
``agent_kernel_bindings`` (see ``DshAgentKernelGateway.create_session`` and
``RuntimeCoordinator.create_binding``), so a single lookup answers which project
a session belongs to.

The client is NOT the authority on its own binding: the request body's
workspace id is never used, only the binding's ``source_workspace_id`` (the
DSH-side project id after 046). A miss falls back to ``"default"`` and is
counted so the migration gap stays observable.

Results are cached with a short TTL (a whole turn reuses one session id).
When ``DSH_KERNEL_REDIS_URL`` is set the cache is shared across replicas the
same way ``SessionAffinityCache`` is; otherwise it degrades to a process-local
dict, which is safe for single-instance deployments.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_KEY_PREFIX = "mogo:dsh:project_id:"
_DEFAULT_PROJECT = "default"


class ProjectIdResolver:
    """Best-effort ``session_id -> project_id`` lookup with a short TTL."""

    def __init__(
        self,
        bindings: Any,
        *,
        redis_url: str | None = None,
        ttl_seconds: float = 300.0,
        key_prefix: str = _KEY_PREFIX,
    ) -> None:
        self._bindings = bindings
        self._ttl = float(ttl_seconds)
        self._prefix = key_prefix
        self._misses = 0
        # memory fallback: session_id -> (project_id, monotonic timestamp)
        self._fallback: dict[str, tuple[str, float]] = {}
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
                logger.info("project id resolver connected to Redis")
            except Exception:
                logger.warning(
                    "project id resolver: Redis unavailable, falling back to "
                    "in-process memory (single-instance semantics)"
                )
                self._redis = None

    @property
    def backend(self) -> str:
        return "redis" if self._redis is not None else "memory"

    @property
    def miss_count(self) -> int:
        return self._misses

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    def _cache_get(self, session_id: str) -> str | None:
        if self._redis is not None:
            try:
                value = self._redis.get(self._key(session_id))
            except Exception:
                logger.warning("project id resolver read failed; treating as miss")
                return None
            return str(value) if value else None
        entry = self._fallback.get(session_id)
        if entry is None:
            return None
        project_id, stamped_at = entry
        if time.monotonic() - stamped_at >= self._ttl:
            self._fallback.pop(session_id, None)
            return None
        return project_id

    def _cache_set(self, session_id: str, project_id: str) -> None:
        if not session_id:
            return
        if self._redis is not None:
            try:
                self._redis.set(self._key(session_id), project_id, ex=int(self._ttl))
                return
            except Exception:
                logger.warning("project id resolver write failed; using in-process memory")
        self._fallback[session_id] = (project_id, time.monotonic())

    async def resolve(self, session_id: str, *, tenant_id: str, user_id: str) -> str:
        """Return the project this session belongs to, or "default" when unbound."""
        if not session_id:
            return _DEFAULT_PROJECT
        cached = self._cache_get(session_id)
        if cached is not None:
            return cached
        binding = await self._bindings.by_kernel_session(
            session_id, tenant_id=tenant_id, user_id=user_id
        )
        project_id = str(binding.get("source_workspace_id") or "").strip() if binding else ""
        if not project_id:
            self._misses += 1
            project_id = _DEFAULT_PROJECT
        self._cache_set(session_id, project_id)
        return project_id


__all__ = ["ProjectIdResolver"]
