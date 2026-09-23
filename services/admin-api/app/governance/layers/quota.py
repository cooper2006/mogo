"""Layer 5 — quota (pass-through placeholder for US1).

The real layer enforces the three-dimensional quota (tenant / user / tool) using
MongoDB atomic counters in the ``quota_counters`` collection (US5). Until then
this layer passes through.
"""

from __future__ import annotations

from ..gatekeeper import GateContext, GateDecision, GateVerdict


class QuotaLayer:
    name = "quota"

    async def evaluate(self, ctx: GateContext) -> GateVerdict:
        # TODO(US5): three-dimension quota via quota_counters (atomic findOneAndUpdate).
        return GateVerdict(decision=GateDecision.ALLOW, layer=self.name, reason="quota placeholder")
