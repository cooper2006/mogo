"""036 trust-rating endpoints (FR-4 / FR-6 / FR-10 / FR-11 / FR-14 / FR-16).

Contract:

* ``GET    /api/trust-ratings``                     list (FR-14 L1 visibility)
* ``GET    /api/trust-ratings/distribution``        FR-16 (008 dashboard)
* ``GET    /api/trust-ratings/settings``            downgrade switch (FR-10)
* ``PUT    /api/trust-ratings/settings``            update the switch (FR-10)
* ``GET    /api/trust-ratings/{asset_type}/{asset_key}``  single rating
* ``POST   /api/trust-ratings/{asset_type}/{asset_key}/changes``   change level (FR-6)
* ``POST   /api/trust-ratings/{asset_type}/{asset_key}/recompute`` manual recalc

Every endpoint is behind a 001 permission-code check (FR-4, fail-closed): an
actor whose codes do not satisfy ``trust:read`` / ``trust:manage`` gets a 403.

Admin accounts carry no fine-grained permission-code list yet, so codes are derived
from the account's role name — platform-wide roles expand to ``*``, anything else
starts read-only. See ``_admin_codes``.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.core.db import get_db
from app.governance.rbac_model import has_permission
from app.services.trust_rating.ratings import (
    TRUST_LEVELS,
    TRUST_MANAGE,
    TRUST_READ,
    get_rating,
    list_ratings,
    rating_distribution,
    recompute_rating,
    record_change,
    get_downgrade_settings,
    update_downgrade_settings,
    ensure_rating,
    ensure_indexes,
)

# Mounted under the api_router prefix (``/api``), so the public path is
# ``/api/trust-ratings``.
router = APIRouter(prefix="/trust-ratings", tags=["trust-rating"])


# --- FR-4 RBAC (fail-closed) -------------------------------------------------

#: Platform-wide roles expand to every permission code (001 "*").
#: Note that `platform_bootstrap.py` writes `role_name` = "平台超级管理员" (not the
#: 022 setup wizard's default `displayName` "平台管理员"); both must be covered.
_ALL_CODES_ROLES = frozenset({"平台管理员", "平台超级管理员", "超级管理员", "full_access_admin"})

#: Read is the baseline for every authenticated admin account.
_BASELINE_CODES = frozenset({TRUST_READ})


def _admin_codes(user: dict[str, Any]) -> set[str]:
    role = str(user.get("role_name") or "")
    if role in _ALL_CODES_ROLES:
        return {"*"}
    return set(_BASELINE_CODES)


def _require_trust(user: dict[str, Any], code: str) -> None:
    granted = _admin_codes(user)
    if not has_permission(granted, code):
        raise HTTPException(status_code=403, detail=f"missing permission: {code}")


# --- request models ---------------------------------------------------------

class RatingChangePayload(BaseModel):
    target_level: str = Field(..., max_length=2)
    reason: str = Field(..., min_length=1, max_length=64)
    owner_id: str = Field(default="", max_length=128)
    evidence: Optional[dict[str, Any]] = None


class SettingsPayload(BaseModel):
    enabled: Optional[bool] = None
    window_days: Optional[int] = Field(default=None, ge=1, le=365)


# --- helpers ----------------------------------------------------------------

def _tenant_id(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or "default")


def _parse_asset(asset_type: str, asset_key: str) -> tuple[str, str]:
    from app.services.trust_rating.ratings import validate_asset

    try:
        return validate_asset(asset_type, asset_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- routes -----------------------------------------------------------------

@router.get("")
async def list_all(
    asset_type: str = Query(default=""),
    visible_to: str = Query(default=""),
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    _require_trust(current_user, TRUST_READ)
    db = get_db()
    items = await list_ratings(
        db,
        tenant_id=_tenant_id(current_user),
        asset_type=asset_type or None,
        visible_to=visible_to or str(current_user.get("user_id") or ""),
    )
    return {"code": 0, "message": "ok", "data": {"items": items}}


@router.get("/distribution")
async def distribution(
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    _require_trust(current_user, TRUST_READ)
    counts = await rating_distribution(get_db(), tenant_id=_tenant_id(current_user))
    return {"code": 0, "message": "ok", "data": counts}


@router.get("/settings")
async def read_settings(
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    _require_trust(current_user, TRUST_READ)
    data = await get_downgrade_settings(get_db(), _tenant_id(current_user))
    return {"code": 0, "message": "ok", "data": data}


@router.put("/settings")
async def write_settings(
    payload: SettingsPayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    _require_trust(current_user, TRUST_MANAGE)
    try:
        data = await update_downgrade_settings(
            get_db(),
            _tenant_id(current_user),
            enabled=payload.enabled,
            window_days=payload.window_days,
            actor=str(current_user.get("user_id") or current_user.get("username") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": data}


@router.get("/{asset_type}/{asset_key}")
async def read_one(
    asset_type: str,
    asset_key: str,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    _require_trust(current_user, TRUST_READ)
    asset_type, asset_key = _parse_asset(asset_type, asset_key)
    doc = await get_rating(get_db(), tenant_id=_tenant_id(current_user), asset_type=asset_type, asset_key=asset_key)
    if doc is None:
        raise HTTPException(status_code=404, detail="评级不存在")
    return {"code": 0, "message": "ok", "data": doc}


@router.post("/{asset_type}/{asset_key}/changes")
async def change_level(
    asset_type: str,
    asset_key: str,
    payload: RatingChangePayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    _require_trust(current_user, TRUST_MANAGE)
    asset_type, asset_key = _parse_asset(asset_type, asset_key)
    if payload.target_level not in TRUST_LEVELS:
        raise HTTPException(status_code=400, detail=f"target_level must be one of {TRUST_LEVELS}")
    actor = str(current_user.get("user_id") or current_user.get("username") or "")
    tenant_id = _tenant_id(current_user)
    await ensure_rating(
        get_db(),
        tenant_id=tenant_id,
        asset_type=asset_type,
        asset_key=asset_key,
        owner_id=payload.owner_id,
        created_by=actor,
    )
    try:
        updated = await record_change(
            get_db(),
            tenant_id=tenant_id,
            asset_type=asset_type,
            asset_key=asset_key,
            target_level=payload.target_level,
            reason=payload.reason,
            evidence=payload.evidence,
            actor=actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": updated}


@router.post("/{asset_type}/{asset_key}/recompute")
async def recompute(
    asset_type: str,
    asset_key: str,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    _require_trust(current_user, TRUST_MANAGE)
    asset_type, asset_key = _parse_asset(asset_type, asset_key)
    result = await recompute_rating(
        get_db(),
        tenant_id=_tenant_id(current_user),
        asset_type=asset_type,
        asset_key=asset_key,
        actor=str(current_user.get("user_id") or current_user.get("username") or ""),
    )
    return {"code": 0, "message": "ok", "data": result}


async def ensure_trust_indexes() -> None:
    await ensure_indexes(get_db())


__all__ = ["router", "ensure_trust_indexes"]