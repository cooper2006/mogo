"""Layer 5 — three-dimension quota enforcement (US5 / T026 / T027).

Quota limits are resolved in this order (most specific wins):

1. tool-level limit (``quota_scope="tool"``),
2. user-level limit (``quota_scope="user"``),
3. tenant-level limit (``quota_scope="tenant"``),

each over a time window (``min`` / ``day`` / ``month``). Counters live in the
``quota_counters`` collection and are incremented atomically via
``update_one($inc, upsert=True)`` — the single-write concurrency guarantee
needs no Redis (clarify OQ-2 / T026).

When the post-increment count exceeds the limit the layer returns a **deny**
verdict (429 at the API boundary) naming the exact dimension + window that
was exceeded (US5 acceptance: "the 1001st call of a 1000/day tenant quota is
rejected with a tenant-quota notice; a 10/h tool quota blocks only that tool").
"""

from __future__ import annotations

import datetime
from typing import Any, Optional

from ..gatekeeper import GateContext, GateDecision, GateVerdict

QUOTA_COUNTERS_COLLECTION = "quota_counters"

# Quota windows in minutes.
WINDOWS: dict[str, int] = {"min": 1, "day": 24 * 60, "month": 30 * 24 * 60}


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _window_start(window: str) -> datetime.datetime:
    now = _utcnow()
    return now - datetime.timedelta(minutes=WINDOWS.get(window, 0))


class QuotaStore:
    """Atomic counter operations over ``quota_counters`` (DB-injected for tests)."""

    def __init__(self, db: Any) -> None:
        self.db = db

    async def check_and_consume(
        self,
        *,
        tenant_id: str,
        user_id: str,
        tool: str,
        limits: dict[str, dict[str, int]],
    ) -> Optional[tuple[str, str, int]]:
        """Consume one unit for every configured limit dimension.

        Returns ``(scope, window, limit)`` for the first *exceeded* dimension,
        or ``None`` when within quota. ``limits`` maps
        ``tool|user|tenant`` -> ``{window: limit}`` (already tenant-scoped).
        """
        base_filters = {"tenant_id": tenant_id}
        checks: list[tuple[str, str, dict, int]] = []
        for scope in ("tool", "user", "tenant"):
            limits_by_window = limits.get(scope, {})
            if not limits_by_window:
                continue
            subject = {"tool": tool, "user": user_id, "tenant": tenant_id}[scope]
            for window, limit in limits_by_window.items():
                checks.append((scope, window, dict(base_filters, dimension=scope, subject=subject, window=window), int(limit)))

        for scope, window, filter_doc, limit in checks:
            from pymongo import ReturnDocument

            result = await self.db[QUOTA_COUNTERS_COLLECTION].find_one_and_update(
                filter_doc,
                {"$inc": {"count": 1}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            count = int(result.get("count", 0)) if result else 0
            if count > limit:
                return scope, window, limit
        return None


class QuotaLayer:
    """Layer 5: enforce the configured quota limits (pass-through when unconfigured)."""

    name = "quota"

    def __init__(self, store: Optional[QuotaStore] = None, limits_resolver=None) -> None:
        # ``limits_resolver(tenant_id) -> dict`` returns the effective limits;
        # default: no tenant has limits configured -> pass-through (T002 floor).
        self._store = store
        self._limits_resolver = limits_resolver

    def _get_store(self) -> QuotaStore:
        if self._store is None:
            from app.core.db import get_db

            self._store = QuotaStore(get_db())
        return self._store

    async def _limits_for(self, tenant_id: str) -> dict[str, dict[str, int]]:
        resolver = self._limits_resolver
        if resolver is None:
            return {}
        limits = await resolver(tenant_id) if hasattr(resolver, "__await__") else resolver(tenant_id)
        return limits or {}

    async def evaluate(self, ctx: GateContext) -> GateVerdict:
        limits = await self._limits_for(ctx.tenant_id)
        if not limits:
            return GateVerdict(decision=GateDecision.ALLOW, layer=self.name, reason="no quota limits configured")

        store = self._get_store()
        exceeded = await store.check_and_consume(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            tool=ctx.tool,
            limits=limits,
        )
        if exceeded is None:
            return GateVerdict(decision=GateDecision.ALLOW, layer=self.name, reason="within quota")
        scope, window, limit = exceeded
        ctx.annotations["quota_exceeded"] = {"scope": scope, "window": window, "limit": limit}
        return GateVerdict(
            decision=GateDecision.DENY,
            layer=self.name,
            reason=f"{scope} 配额超限（{window} 窗口 > {limit}）",
            detail={"scope": scope, "window": window, "limit": limit, "tool": ctx.tool},
        )


__all__ = ["QuotaLayer", "QuotaStore", "WINDOWS"]
