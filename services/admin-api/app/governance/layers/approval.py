"""Layer 4 — approval (pass-through placeholder for US1).

The real layer consults the 25-cell autonomy matrix and delegates to the existing
``approval_runtime`` EnterpriseApproval state machine (US2). Until then this layer
passes through.
"""

from __future__ import annotations

from ..gatekeeper import GateContext, GateDecision, GateVerdict


class ApprovalLayer:
    name = "approval"

    async def evaluate(self, ctx: GateContext) -> GateVerdict:
        # TODO(US2): consult AUTONOMY_MATRIX[L][R]; on require_approval, suspend
        # via approval_runtime and return a 409 verdict carrying the approval token.
        return GateVerdict(decision=GateDecision.ALLOW, layer=self.name, reason="approval placeholder")
