"""Layer 3 — PII redaction (pass-through placeholder for US1).

US1 only requires the chain to be complete; the real policy engine
(mask/remove/hash/abstract over the 5 PII classes) is delivered by US3. Until
then this layer passes text through untouched.
"""

from __future__ import annotations

from ..gatekeeper import GateContext, GateDecision, GateVerdict


class RedactionLayer:
    name = "redaction"

    async def evaluate(self, ctx: GateContext) -> GateVerdict:
        # TODO(US3): apply the global default policy + tenant overrides.
        return GateVerdict(decision=GateDecision.ALLOW, layer=self.name, reason="redaction placeholder")
