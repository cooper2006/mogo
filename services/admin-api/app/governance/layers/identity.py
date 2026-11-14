"""Layer 1 — identity: resolve the calling subject (tenant / user / roles).

The gate must always know *who* is calling before any authorization decision.
A request with no resolvable tenant is denied (fail-closed).
"""

from __future__ import annotations

from ..gatekeeper import GateContext, GateDecision, GateVerdict


class IdentityLayer:
    name = "identity"

    async def evaluate(self, ctx: GateContext) -> GateVerdict:
        if not ctx.tenant_id:
            return GateVerdict(
                decision=GateDecision.DENY,
                layer=self.name,
                reason="无法解析调用主体（缺失租户）",
            )
        if not ctx.user_id and not ctx.roles:
            # A tenant-level actor without a user is allowed only when it carries
            # an explicit role set (e.g. system/service principal).
            return GateVerdict(
                decision=GateDecision.DENY,
                layer=self.name,
                reason="无法解析调用主体（缺失用户与角色）",
            )
        ctx.annotations["subject"] = {
            "tenant_id": ctx.tenant_id,
            "user_id": ctx.user_id,
            "roles": list(ctx.roles),
        }
        return GateVerdict(decision=GateDecision.ALLOW, layer=self.name, reason="subject resolved")
