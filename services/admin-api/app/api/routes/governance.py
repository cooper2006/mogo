"""Management-plane endpoints for the gatekeeper (T018 / T024 / T030).

Three admin surfaces, all under the governance router:

* risk tiers:   register / list a tool's R0-R4 level (US2, T015/T018)
* matrix:       read / update the 25-cell autonomy matrix (R4 red line can
                never be set to allow / require_approval — the store rejects
                it, FR-4); every edit is audited (FR-9)
* permission
  codes:        grant / revoke fine-grained codes at tenant/org/user level
                (US4, T024); changes take effect on the next gate evaluation
                and are audited

Endpoints require the admin dependency (``get_current_admin_user``) — the management
plane is not reachable by ordinary callers.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..deps import get_current_admin_user
from ...governance import permission_grants, risk
from ...governance.rbac_model import has_permission

router = APIRouter(prefix="/api/governance", tags=["governance"])


class RiskTierIn(BaseModel):
    tool: str = Field(min_length=1)
    risk: str = Field(pattern=r"^R[0-4]$")
    note: str = ""


class MatrixCellIn(BaseModel):
    level: str = Field(pattern=r"^L[1-5]$")
    risk: str = Field(pattern=r"^R[0-4]$")
    decision: str = Field(pattern=r"^(allow|require_approval|deny)$")


class PermissionGrantIn(BaseModel):
    code: str = Field(min_length=1)
    level: str = Field(pattern=r"^(tenant|org|user)$", default="user")
    org_id: str = ""
    user_id: str = ""


class PermissionRevokeIn(BaseModel):
    code: str = Field(min_length=1)
    level: str = Field(pattern=r"^(tenant|org|user)$", default="user")
    org_id: str = ""
    user_id: str = ""


def _tenant(actor: dict[str, Any]) -> str:
    return str(actor.get("main_id") or actor.get("tenant_id") or "")


def _actor_id(actor: dict[str, Any]) -> str:
    return str(actor.get("user_id") or "admin")


# --- Risk tiers ---------------------------------------------------------------


@router.post("/risk-tiers")
async def register_risk_tier(body: RiskTierIn, actor: dict[str, Any] = Depends(get_current_admin_user)) -> dict[str, Any]:
    """Register (upsert) a tool's risk tier for the caller's tenant."""
    document = await risk.register_risk_tier(
        tenant_id=_tenant(actor), tool=body.tool, risk=body.risk, note=body.note
    )
    return document


@router.get("/risk-tiers")
async def list_risk_tiers(
    tool: Optional[str] = Query(default=None),
    actor: dict[str, Any] = Depends(get_current_admin_user),
) -> list[dict[str, Any]]:
    """List the caller's tenant-specific risk tiers, or all when no tenant."""
    tenant_id = _tenant(actor)
    return await risk.list_risk_tiers(tenant_id=tenant_id, tool=tool) if tenant_id else await risk.list_risk_tiers(tool=tool)


# --- Autonomy matrix ----------------------------------------------------------


@router.get("/autonomy-matrix")
async def get_autonomy_matrix(actor: dict[str, Any] = Depends(get_current_admin_user)) -> dict[str, Any]:
    """The stored 25-cell matrix with canonical fallback for missing cells."""
    from ...governance.schema import AUTONOMY_MATRIX

    matrix: dict[str, dict[str, str]] = {}
    for level in risk.AUTONOMY_LEVELS:
        matrix[level] = {}
        for r in risk.RISK_LEVELS:
            matrix[level][r] = await risk.matrix_decision(level=level, risk=r)
    return {"matrix": matrix, "canonical": AUTONOMY_MATRIX}


@router.put("/autonomy-matrix/cells")
async def update_matrix_cell(
    body: MatrixCellIn, actor: dict[str, Any] = Depends(get_current_admin_user)
) -> dict[str, Any]:
    """Update one cell; R4 cells are frozen to ``deny`` (red line, FR-4)."""
    if body.risk == "R4" and body.decision != "deny":
        raise HTTPException(
            status_code=400,
            detail="R4 red line: the cell must stay deny (cannot be overridden)",
        )
    from ...governance.schema import AUTONOMY_MATRIX, AUTONOMY_MATRIX_COLLECTION, ensure_indexes

    previous = await risk.matrix_decision(level=body.level, risk=body.risk)
    db = None
    try:
        from app.core.db import get_db

        db = get_db()
    except Exception:
        db = None
    if db is not None:
        await db[AUTONOMY_MATRIX_COLLECTION].update_one(
            {"cell": f"{body.level}:{body.risk}"},
            {"$set": {"level": body.level, "risk": body.risk, "decision": body.decision}},
            upsert=True,
        )
    await risk.audit_matrix_change(
        actor=_actor_id(actor),
        level=body.level,
        risk=body.risk,
        decision=body.decision,
        previous=previous,
    )
    return {"cell": f"{body.level}:{body.risk}", "decision": body.decision, "previous": previous}


# --- Permission codes (US4) ---------------------------------------------------


@router.post("/permissions/grant")
async def grant_permission(
    body: PermissionGrantIn, actor: dict[str, Any] = Depends(get_current_admin_user)
) -> dict[str, Any]:
    """Grant a fine-grained permission code at one isolation level."""
    tenant_id = _tenant(actor)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="cannot resolve the caller's tenant")
    try:
        document = await permission_grants.grant_code(
            tenant_id=tenant_id,
            code=body.code,
            level=body.level,
            org_id=body.org_id,
            user_id=body.user_id,
            granted_by=_actor_id(actor),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return document


@router.post("/permissions/revoke")
async def revoke_permission(
    body: PermissionRevokeIn, actor: dict[str, Any] = Depends(get_current_admin_user)
) -> dict[str, Any]:
    """Revoke one explicit grant (takes effect on the next evaluation)."""
    tenant_id = _tenant(actor)
    try:
        removed = await permission_grants.revoke_code(
            tenant_id=tenant_id,
            code=body.code,
            level=body.level,
            org_id=body.org_id,
            user_id=body.user_id,
            revoked_by=_actor_id(actor),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"revoked": removed, "code": body.code}


@router.get("/permissions")
async def list_permissions(
    level: str = "", code: str = "", actor: dict[str, Any] = Depends(get_current_admin_user)
) -> list[dict[str, Any]]:
    """List the tenant's explicit grants (three-level union)."""
    tenant_id = _tenant(actor)
    if not tenant_id:
        return []
    return await permission_grants.list_grants(tenant_id=tenant_id, level=level, code=code)


@router.get("/permissions/check")
async def check_permission(
    code: str, actor: dict[str, Any] = Depends(get_current_admin_user)
) -> dict[str, Any]:
    """Whether the caller's *own* effective codes satisfy ``code`` (admin self-check)."""
    granted = {str(actor.get("user_id") or "")}
    return {"code": code, "satisfied": has_permission(granted, code) or "*" in granted}


__all__ = ["router"]
