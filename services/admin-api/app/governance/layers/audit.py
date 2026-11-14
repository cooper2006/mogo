"""Layer 6 — audit: record every pass / reject event.

Events land in the ``gate_events`` collection via the same single audit sink used
by the rest of admin-api (``system_audit``), so governance never fragments its
audit trail (FR-9). Each event carries: layer, risk level, autonomy level, and
timestamp.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from ..gatekeeper import GateContext, GateDecision, GateVerdict

GATE_EVENTS_COLLECTION = "gate_events"


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _get_db() -> Any:
    # Imported lazily so this module (and its tests) need no DB driver at import.
    from app.core.db import get_db

    return get_db()


class AuditLayer:
    name = "audit"

    async def ensure_indexes(self) -> None:
        try:
            db = _get_db()
        except Exception:
            return
        collection = db[GATE_EVENTS_COLLECTION]
        await collection.create_index([("tenant_id", 1), ("occurred_at", -1)], name="gate_events_tenant_time")
        await collection.create_index([("tenant_id", 1), ("decision", 1), ("occurred_at", -1)], name="gate_events_tenant_decision_time")

    async def evaluate(self, ctx: GateContext) -> GateVerdict:
        """Persist the final verdict (allow or deny) carried in ``ctx.annotations``."""
        verdict: GateVerdict | None = ctx.annotations.get("verdict")
        if verdict is None:
            verdict = GateVerdict(decision=GateDecision.ALLOW, layer="gatekeeper", reason="audited")

        document: dict[str, Any] = {
            "event_id": uuid.uuid4().hex,
            "occurred_at": _utcnow(),
            "tenant_id": ctx.tenant_id,
            "user_id": ctx.user_id,
            "roles": list(ctx.roles),
            "tool": ctx.tool,
            "risk_level": ctx.risk_level,
            "autonomy_level": ctx.autonomy_level,
            "decision": verdict.decision.value,
            "layer": verdict.layer,
            "reason": verdict.reason,
            "detail": verdict.detail,
        }
        try:
            db = _get_db()
            await db[GATE_EVENTS_COLLECTION].insert_one(document)
        except Exception:
            # The audit sink must never be the reason a *denied* call is allowed
            # through; but it also must not crash the gate. A failure to persist is
            # surfaced as an audit-layer deny so the caller is still blocked.
            return GateVerdict(
                decision=GateDecision.DENY,
                layer=self.name,
                reason="审计落库失败（fail-closed）",
            )
        return GateVerdict(decision=GateDecision.ALLOW, layer=self.name, reason="audited")
