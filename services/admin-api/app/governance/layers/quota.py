"""Layer 5 — quota enforcement (US5 / T026 / T027).

**Wiring note (2026-10-03)**: this repo has no ``quota_limits`` collection and no
consumer for "call-count limits" (the original spec's three dimensions). What does
exist is feature 020's real token-quota system (``org_quota_policies`` /
``user_quota_policies``), already enforced on the chat path. Rather than build a
second, parallel quota model, this layer delegates to that system: when a tenant's
(or user's) token budget is exhausted the tool/Skill call is denied (429).

The legacy call-count path (``limits_resolver`` + ``quota_counters``) is kept
intact for backward compatibility and is still what the unit tests exercise.

When neither a credit checker nor any limits are configured the layer passes
through — but ``build_layers`` now always installs the 020-backed checker, so the
pass-through is no longer the production default.
"""

from __future__ import annotations

import datetime
from typing import Any, Optional

from ..gatekeeper import GateContext, GateDecision, GateVerdict

QUOTA_COUNTERS_COLLECTION = "quota_counters"

# Quota windows in minutes.
WINDOWS: dict[str, int] = {"min": 1, "day": 24 * 60, "month": 30 * 24 * 60}


async def default_credit_checker(tenant_id: str, user_id: str) -> Optional[str]:
    """020-backed budget check: return a denial reason when the budget is gone.

    Uses the tenant's real quota policy (``org_quota_policies`` /
    ``user_quota_policies``). ``unlimited`` tenants are never denied.
    """
    try:
        from app.core.db import get_db
        from app.core.quota_policy import get_quota_summary

        db = get_db()
        if db is None:
            return None
        user = await db["end_users"].find_one({"_id": user_id}) if user_id else None
        summary = await get_quota_summary(tenant_id, user or {})
    except Exception:
        # Fail-open **only** for the budget probe itself: an unreadable quota row
        # must not block tool calls. (The gate's own denial path stays fail-closed.)
        return None
    if summary.get("unlimited"):
        return None
    if int(summary.get("remainingPoints") or 0) <= 0:
        return "token 额度已用尽（001 配额层复用 020 配额体系）"
    return None



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
    """Layer 5: enforce the real token budget (020), then any call-count limits."""

    name = "quota"

    def __init__(
        self,
        store: Optional[QuotaStore] = None,
        limits_resolver=None,
        credit_checker=None,
    ) -> None:
        # ``limits_resolver(tenant_id) -> dict`` returns legacy call-count limits;
        # ``credit_checker(tenant_id, user_id) -> str|None`` is the 020-backed budget
        # probe (returns a denial reason when the tenant/user budget is exhausted).
        self._store = store
        self._limits_resolver = limits_resolver
        self._credit_checker = credit_checker

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
        # 1) Real budget (020): token quota exhausted -> deny.
        if self._credit_checker is not None:
            reason = self._credit_checker(ctx.tenant_id, ctx.user_id)
            if hasattr(reason, "__await__"):
                reason = await reason
            if reason:
                ctx.annotations["quota_exceeded"] = {"scope": "budget", "reason": str(reason)}
                return GateVerdict(
                    decision=GateDecision.DENY,
                    layer=self.name,
                    reason=str(reason),
                    detail={"scope": "budget", "tool": ctx.tool},
                )

        # 2) Legacy call-count limits (when configured).
        limits = await self._limits_for(ctx.tenant_id)
        if not limits:
            return GateVerdict(decision=GateDecision.ALLOW, layer=self.name, reason="within budget")

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


__all__ = ["QuotaLayer", "QuotaStore", "WINDOWS", "default_credit_checker"]
