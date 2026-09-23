"""Layer 4 — approval: autonomy-matrix decision + approval suspension (US2 / T016).

The layer consults the 25-cell autonomy matrix (``risk.matrix_decision``) for the
call's ``[autonomy_level][risk_level]`` cell:

* ``allow``  -> pass;
* ``deny``   -> hard reject (R4 red line can never be overridden, FR-4);
* ``require_approval`` -> the call is *not* executed inline. Instead a
  one-time approval ticket is issued through :class:`ApprovalRegistry` (a
  ``gate_approvals`` collection with the same state machine as
  ``chat-api``'s ``ApprovalRuntime``: pending -> approved/denied/expired,
  ``expires_at`` defaulting to 5 minutes, polling-based resume — clarify OQ-1),
  and the gate returns ``REQUIRE_APPROVAL`` (409 at the API boundary, T006).

The resume path is a later re-entry with the approval token: when
``ctx.annotations["approval_token"]`` is present the layer validates and
consumes the ticket instead of consulting the matrix again (one-time use,
fail-closed on expiry).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..gatekeeper import GateContext, GateDecision, GateVerdict

GATE_APPROVALS_COLLECTION = "gate_approvals"
APPROVAL_TTL_MINUTES = 5


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_db() -> Any:
    from app.core.db import get_db

    return get_db()


class ApprovalRegistry:
    """One-time approval tickets in ``gate_approvals`` (MongoDB, no Redis).

    Mirrors the chat-api ``ApprovalRuntime`` state machine (pending ->
    approved/denied/expired, poll-resume, 5min TTL) but backed by MongoDB so
    the approval survives process restarts (spec FR-2 / clarify OQ-1).
    """

    def __init__(self, db: Optional[Any] = None) -> None:
        self._db = db

    def _collection(self):
        if self._db is None:
            self._db = _get_db()
        return self._db[GATE_APPROVALS_COLLECTION]

    async def issue(
        self,
        *,
        action_id: str,
        tenant_id: str,
        user_id: str,
        tool: str,
        risk_level: str = "",
        autonomy_level: str = "",
        reason: str = "",
        ttl_minutes: int = APPROVAL_TTL_MINUTES,
    ) -> str:
        token = uuid.uuid4().hex
        document = {
            "action_id": action_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "tool": tool,
            "risk_level": risk_level,
            "autonomy_level": autonomy_level,
            "reason": reason,
            "token_hash": _token_hash(token),
            "status": "pending",
            "created_at": _utcnow(),
            "expires_at": _utcnow() + timedelta(minutes=ttl_minutes),
            "resolved_at": None,
        }
        await self._collection().insert_one(document)
        return token

    async def validate_and_consume(
        self, *, action_id: str, token: str, actor: str = ""
    ) -> bool:
        """Consume a pending ticket (one-time). Fails closed on expiry/absence."""
        collection = self._collection()
        document = await collection.find_one(
            {"action_id": action_id, "token_hash": _token_hash(token), "status": "pending"}
        )
        if document is None:
            return False
        if document.get("expires_at") and document["expires_at"] < _utcnow():
            await collection.update_one(
                {"_id": document["_id"]}, {"$set": {"status": "expired", "resolved_at": _utcnow()}}
            )
            return False
        if actor and document.get("user_id") and actor != document["user_id"]:
            return False
        result = await collection.update_one(
            {"_id": document["_id"], "status": "pending"},
            {"$set": {"status": "approved", "resolved_at": _utcnow()}},
        )
        return result.modified_count == 1

    async def deny(self, *, action_id: str, token: str, actor: str = "") -> bool:
        collection = self._collection()
        document = await collection.find_one(
            {"action_id": action_id, "token_hash": _token_hash(token), "status": "pending"}
        )
        if document is None:
            return False
        if actor and document.get("user_id") and actor != document["user_id"]:
            return False
        result = await collection.update_one(
            {"_id": document["_id"], "status": "pending"},
            {"$set": {"status": "denied", "resolved_at": _utcnow()}},
        )
        return result.modified_count == 1


def _token_hash(token: str) -> str:
    import hashlib

    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


class ApprovalLayer:
    name = "approval"

    def __init__(self, registry: Optional[ApprovalRegistry] = None) -> None:
        self._registry = registry

    def _get_registry(self) -> ApprovalRegistry:
        if self._registry is None:
            self._registry = ApprovalRegistry()
        return self._registry

    async def evaluate(self, ctx: GateContext) -> GateVerdict:
        # Resume path: a carried approval token settles the pending decision.
        approval_token = ctx.annotations.get("approval_token")
        if approval_token:
            registry = self._get_registry()
            action_id = ctx.annotations.get("approval_action_id", ctx.session_id or ctx.tool)
            if await registry.validate_and_consume(
                action_id=str(action_id), token=str(approval_token), actor=ctx.actor()
            ):
                ctx.annotations["approval"] = {"action_id": str(action_id), "result": "approved"}
                return GateVerdict(
                    decision=GateDecision.ALLOW, layer=self.name, reason="approval token consumed"
                )
            return GateVerdict(
                decision=GateDecision.DENY,
                layer=self.name,
                reason="审批 token 无效、已过期或已使用",
                detail={"action_id": str(action_id)},
            )

        # Fresh path: consult the autonomy matrix.
        from ..risk import matrix_decision

        risk = ctx.risk_level or "R0"
        level = ctx.autonomy_level or "L1"
        decision = await matrix_decision(level=level, risk=risk)
        if decision == "allow":
            return GateVerdict(decision=GateDecision.ALLOW, layer=self.name, reason=f"matrix {level}x{risk}=allow")
        if decision == "deny":
            return GateVerdict(
                decision=GateDecision.DENY,
                layer=self.name,
                reason=f"矩阵 {level}x{risk}=deny（红线不可覆盖）",
                detail={"cell": f"{level}:{risk}"},
            )

        # require_approval: suspend with a one-time ticket (409 at the boundary).
        registry = self._get_registry()
        action_id = ctx.session_id or f"gate-{uuid.uuid4().hex[:12]}"
        token = await registry.issue(
            action_id=action_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            tool=ctx.tool,
            risk_level=risk,
            autonomy_level=level,
            reason=f"matrix {level}x{risk}=require_approval",
        )
        ctx.annotations["approval"] = {"action_id": action_id, "result": "pending", "token": token}
        return GateVerdict(
            decision=GateDecision.REQUIRE_APPROVAL,
            layer=self.name,
            reason=f"矩阵 {level}x{risk}=require_approval，已挂起等待审批",
            detail={"action_id": action_id, "token": token, "cell": f"{level}:{risk}"},
        )


__all__ = ["ApprovalLayer", "ApprovalRegistry", "GATE_APPROVALS_COLLECTION", "APPROVAL_TTL_MINUTES"]
