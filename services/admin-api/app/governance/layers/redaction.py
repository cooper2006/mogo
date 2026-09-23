"""Layer 3 — PII redaction (US3 / T021).

Applies the global default PII policy (``pii_policies`` ``tenant_id=""``) plus
any tenant override rows to the request/response text carried in the gate
context. Redaction rewrites the text (``ctx.request`` / ``ctx.response``) in
place so downstream layers, the tool invocation, and the audit event all see
only the redacted value; the *tool execution semantics* are untouched (the
text fields are metadata, not the tool's arguments beyond those fields).

Audit traceability (FR-7): for each redacted value the layer records a
:class:`RedactionTrace` (PII class + count + hash fingerprint, no plaintext)
in ``ctx.annotations["redaction"]`` so the audit layer can persist the
fingerprint while the plaintext never reaches ``gate_events``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..gatekeeper import GateContext, GateDecision, GateVerdict
from ..pii import PII_TYPES, fingerprint, redact_text

PII_POLICIES_COLLECTION = "pii_policies"


@dataclass
class RedactionTrace:
    """Per-request redaction record kept for the audit sink (0 plaintext)."""

    types: dict[str, int] = field(default_factory=dict)
    fingerprints: list[str] = field(default_factory=list)

    def as_document(self) -> dict[str, Any]:
        return {
            "types": dict(self.types),
            "fingerprints": list(self.fingerprints),
            "count": sum(self.types.values()),
        }


class RedactionLayer:
    name = "redaction"

    async def _policies_for(self, ctx: GateContext, db: Any) -> dict[str, str]:
        """Effective policy = global defaults overridden by the tenant row."""
        from ..pii import DEFAULT_STRATEGY

        policies = dict(DEFAULT_STRATEGY)
        try:
            cursor = db[PII_POLICIES_COLLECTION].find({"tenant_id": {"$in": ["", ctx.tenant_id]}})
            rows = [row async for row in cursor]
            for row in rows:
                pii_type = row.get("pii_type")
                strategy = row.get("strategy")
                if pii_type in PII_TYPES and strategy:
                    if row.get("tenant_id"):
                        policies[str(pii_type)] = str(strategy)  # tenant override wins
                    elif pii_type not in policies:
                        policies[str(pii_type)] = str(strategy)
        except Exception:
            pass
        return policies

    async def evaluate(self, ctx: GateContext) -> GateVerdict:
        from app.core.db import get_db

        db = get_db()
        policies = await self._policies_for(ctx, db)
        trace = RedactionTrace()

        for key in ("request", "response"):
            payload: Any = getattr(ctx, key)
            if not isinstance(payload, dict):
                continue
            self._redact_fields(payload, policies, trace)

        if trace.count:
            ctx.annotations["redaction"] = trace.as_document()
            return GateVerdict(
                decision=GateDecision.ALLOW,
                layer=self.name,
                reason=f"redacted {trace.count} PII value(s)",
                detail=trace.as_document(),
            )
        return GateVerdict(decision=GateDecision.ALLOW, layer=self.name, reason="no PII found")

    def _redact_fields(self, payload: dict, policies: dict[str, str], trace: RedactionTrace) -> None:
        for key, value in list(payload.items()):
            if not isinstance(value, str) or not value:
                continue
            from ..pii import find_pii

            hits = find_pii(value, list(policies.keys()))
            if not hits:
                continue
            redacted = redact_text(value, policies)
            payload[key] = redacted
            for pii_type, _start, _end, hit in hits:
                trace.types[pii_type] = trace.types.get(pii_type, 0) + 1
                trace.fingerprints.append(fingerprint(hit))


__all__ = ["RedactionLayer", "RedactionTrace"]
