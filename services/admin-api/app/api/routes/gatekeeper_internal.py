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
    ctx = GateContext(
        tool=str(payload.tool or ""),
        tenant_id=str(payload.tenantId or ""),
        user_id=str(payload.userId or ""),
        roles=roles,
        request=dict(payload.request or {}),
        session_id=str(payload.sessionId or ""),
        scope=str(payload.scope or "tool"),
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
