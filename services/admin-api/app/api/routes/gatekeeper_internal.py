"""Internal gatekeeper endpoint (001 US1 — employee-side enforcement).

001's six-layer chain lives in admin-api, but the tool/Skill calls that need it are
executed by chat-api on behalf of *employees*. This endpoint lets chat-api run the
real chain (implemented once here, not duplicated) over HTTP with the shared
service token.

The response carries the (possibly **redacted**) request back to the caller: the
redaction layer rewrites ``ctx.request`` in place, and chat-api must forward the
redacted body to the tool backend — otherwise PII would still reach the backend
(FR-7).
"""

from __future__ import annotations

import hmac
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.governance import GateContext, gatekeeper

router = APIRouter()


def _require_service(token: str) -> None:
    expected = str(settings.backend_service_token or "")
    if not token or not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="invalid_service_token")


class GateEvaluatePayload(BaseModel):
    tool: str = Field(..., description="Tool / Skill identifier being invoked")
    tenantId: str = Field(default="", description="Tenant (main_id) the caller belongs to")
    userId: str = Field(default="", description="Employee user id")
    roles: list[str] = Field(default_factory=list, description="Bound position-role ids")
    request: dict[str, Any] = Field(default_factory=dict, description="Tool request body (may be redacted)")
    sessionId: str = Field(default="", description="Kernel session id")
    scope: str = Field(default="tool")
    # Resume path (FR-2): a requester re-enters with the approval ticket it was
    # handed when the call was suspended. Only an already-approved ticket passes.
    approvalToken: str = Field(default="", description="One-time approval ticket")
    approvalActionId: str = Field(default="", description="Action id the ticket belongs to")


async def _resolve_roles(tenant_id: str, user_id: str, provided: list[str]) -> list[str]:
    """Resolve the employee's real position-role ids (006) when the caller omits them.

    006 binds roles to *employees* in ``end_user_position_roles`` (``user_id`` keyed).
    Without this the RBAC layer would see an empty role set and fail closed on every
    call — the original breakage (001 audit, 2026-10-03).
    """
    if provided:
        return [str(r) for r in provided]
    if not tenant_id or not user_id:
        return []
    try:
        from app.core.db import get_db

        db = get_db()
        if db is None:
            return []
        rows = await db["end_user_position_roles"].find(
            {"main_id": tenant_id, "user_id": user_id}, {"role_id": 1}
        ).to_list(length=100)
        return [str(row.get("role_id") or "") for row in rows if row.get("role_id")]
    except Exception:
        return []


@router.post("/evaluate")
async def evaluate_gate(
    payload: GateEvaluatePayload,
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Run the six-layer chain and return the verdict (+ redacted request)."""
    _require_service(service_token)

    roles = await _resolve_roles(
        str(payload.tenantId or ""), str(payload.userId or ""), list(payload.roles or [])
    )
    annotations: dict[str, Any] = {}
    if payload.approvalToken:
        annotations["approval_token"] = str(payload.approvalToken)
        annotations["approval_action_id"] = str(
            payload.approvalActionId or payload.sessionId or payload.tool or ""
        )
    ctx = GateContext(
        tool=str(payload.tool or ""),
        tenant_id=str(payload.tenantId or ""),
        user_id=str(payload.userId or ""),
        roles=roles,
        request=dict(payload.request or {}),
        session_id=str(payload.sessionId or ""),
        scope=str(payload.scope or "tool"),
        annotations=annotations,
    )
    verdict = await gatekeeper.evaluate(ctx.tool, ctx)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "decision": verdict.decision.value,
            "layer": verdict.layer,
            "reason": verdict.reason,
            "statusCode": verdict.status_code,
            "detail": verdict.detail,
            "roles": roles,
            # The redaction layer rewrites ctx.request in place; hand the (possibly)
            # redacted body back so the caller never forwards plaintext PII.
            "request": ctx.request,
        },
    }


__all__ = ["router"]


class GateApprovalDecision(BaseModel):
    actionId: str = Field(..., description="Action id the suspended call was issued for")
    token: str = Field(..., description="One-time approval ticket to decide")
    approved: bool = Field(..., description="True approves, False denies")
    actor: str = Field(default="", description="Approver identity (audited)")


@router.post("/decide")
async def decide_gate_approval(
    payload: GateApprovalDecision,
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Human-approver decision on a suspended call (FR-2 / FR-11).

    Moves the ticket ``pending -> approved|denied``. The requester then re-enters
    ``/evaluate`` with the token; only an ``approved`` ticket is consumable.
    """
    _require_service(service_token)

    from app.governance.layers.approval import ApprovalRegistry

    ok = await ApprovalRegistry().decide(
        action_id=str(payload.actionId or ""),
        token=str(payload.token or ""),
        approved=bool(payload.approved),
        actor=str(payload.actor or ""),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="approval_ticket_not_pending_or_expired")
    return {
        "code": 0,
        "message": "success",
        "data": {"actionId": str(payload.actionId), "status": "approved" if payload.approved else "denied"},
    }


@router.get("/approvals")
async def list_gate_approvals(
    tenantId: str = "",
    status: str = "pending",
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Approver inbox: list tickets awaiting a decision (FR-2).

    Without this the suspended calls were invisible to any approver — the ticket
    existed in ``gate_approvals`` with nobody able to see it (001 audit, 2026-10-03).
    """
    _require_service(service_token)

    from app.core.db import get_db
    from app.governance.layers.approval import GATE_APPROVALS_COLLECTION

    db = get_db()
    query: dict[str, Any] = {}
    if tenantId:
        query["tenant_id"] = tenantId
    if status:
        query["status"] = status
    rows = (
        await db[GATE_APPROVALS_COLLECTION]
        .find(query, {"token_hash": 0})
        .sort("created_at", -1)
        .limit(200)
        .to_list(length=200)
    )
    for row in rows:
        row["_id"] = str(row.get("_id") or "")
    return {"code": 0, "message": "success", "data": {"items": rows, "count": len(rows)}}


@router.get("/events")
async def list_gate_events(
    tenantId: str = "",
    decision: str = "",
    tool: str = "",
    limit: int = 100,
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Read the 001 audit trail (``gate_events``).

    The audit layer has always *written* every pass/reject here, but nothing could
    read it — so "audit coverage 100%" was unverifiable (001 audit, 2026-10-03).
    This is the missing consumer.
    """
    _require_service(service_token)

    from app.core.db import get_db
    from app.governance.layers.audit import GATE_EVENTS_COLLECTION

    db = get_db()
    query: dict[str, Any] = {}
    if tenantId:
        query["tenant_id"] = tenantId
    if decision:
        query["decision"] = decision
    if tool:
        query["tool"] = tool
    size = max(1, min(int(limit or 100), 500))
    rows = (
        await db[GATE_EVENTS_COLLECTION]
        .find(query, {"_id": 0})
        .sort("occurred_at", -1)
        .limit(size)
        .to_list(length=size)
    )
    for row in rows:
        occurred = row.get("occurred_at")
        if hasattr(occurred, "isoformat"):
            row["occurred_at"] = occurred.isoformat()
    return {"code": 0, "message": "success", "data": {"items": rows, "count": len(rows)}}
