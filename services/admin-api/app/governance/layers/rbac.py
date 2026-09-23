"""Layer 2 — RBAC: decide whether the subject holds the required permission code.

Resolution order (FR-5): the caller's effective codes are the union of the codes
granted by each of its position roles. If the caller holds no code that satisfies
the required code, the request is denied (fail-closed). Unknown codes never match.
"""

from __future__ import annotations

from typing import Any

from ..gatekeeper import GateContext, GateDecision, GateVerdict
from ..rbac_model import expand_role_to_codes, has_permission, required_code_for_tool

# Feature 006's position-role collection (aligned with
# ``app.position_roles.constants.POSITION_ROLE_COLLECTION``).
POSITION_ROLE_COLLECTION = "position_roles"


class RbacLayer:
    name = "rbac"

    async def _role_documents(self, tenant_id: str, role_ids: list[str]) -> list[dict[str, Any]]:
        if not role_ids:
            return []
        try:
            from app.core.db import get_db

            db = get_db()
        except Exception:
            return []
        # 006 stores role documents keyed by ``_id`` (e.g. ``system:<main>:full_access_admin``)
        # under ``position_roles``, scoped by ``main_id``.
        cursor = db[POSITION_ROLE_COLLECTION].find(
            {"main_id": tenant_id, "_id": {"$in": list(role_ids)}}
        )
        return [doc async for doc in cursor]

    async def _effective_codes(self, ctx: GateContext) -> set[str]:
        cached = ctx.annotations.get("effective_codes")
        if isinstance(cached, set):
            return cached
        codes: set[str] = set()
        roles = await self._role_documents(ctx.tenant_id, ctx.roles)
        for role in roles:
            codes.update(expand_role_to_codes(role))
        ctx.annotations["effective_codes"] = codes
        return codes

    async def evaluate(self, ctx: GateContext) -> GateVerdict:
        required = ctx.annotations.get("required_code") or required_code_for_tool(ctx.tool)
        ctx.annotations["required_code"] = required

        granted = await self._effective_codes(ctx)
        if not granted:
            # No resolvable grants: fail-closed (unknown/absent code never matches).
            return GateVerdict(
                decision=GateDecision.DENY,
                layer=self.name,
                reason=f"缺少权限码 {required}",
                detail={"required": required, "granted": sorted(granted)},
            )
        if not has_permission(granted, required):
            return GateVerdict(
                decision=GateDecision.DENY,
                layer=self.name,
                reason=f"权限码不满足：需要 {required}",
                detail={"required": required, "granted": sorted(granted)},
            )
        return GateVerdict(
            decision=GateDecision.ALLOW,
            layer=self.name,
            reason="permission granted",
            detail={"required": required},
        )
