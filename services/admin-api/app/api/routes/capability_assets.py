"""Capability asset registry endpoints (feature 018).

Production wiring with MongoDB persistence (FR-10): capabilities are stored
in the ``capability_assets`` collection so they survive process restarts
and are shareable across replicas.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException

from app.services.capability_assets.registry import (
    ASSET_STATES,
    AssetError,
    PersistedCapabilityRegistry,
)

router = APIRouter(prefix="/api/capabilities", tags=["capability-assets"])

# Module-level singleton registry backed by MongoDB (FR-10).
_registry = PersistedCapabilityRegistry()


def _get_registry() -> PersistedCapabilityRegistry:
    return _registry


@router.post("/discover")
async def discover_capabilities(
    payload: dict[str, Any],
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Discover capabilities from candidate definitions and register them (FR-2 / FR-10)."""
    from app.core.config import settings

    expected = str(settings.backend_service_token or "")
    if not service_token or not expected or not __import__("hmac").compare_digest(service_token, expected):
        raise HTTPException(status_code=401, detail="invalid_service_token")

    candidates = list(payload.get("candidates") or [])
    report = await _get_registry().discover_and_register(candidates)
    return {
        "code": 0,
        "message": "discovered",
        "data": {
            "discovered": [a.as_dict() for a in report.discovered],
            "needs_manual": report.needs_manual,
            "total_discovered": len(report.discovered),
            "total_needs_manual": len(report.needs_manual),
        },
    }


@router.get("")
async def list_capabilities(
    state: Optional[str] = None,
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """List registered capabilities, optionally filtered by state (FR-1)."""
    from app.core.config import settings

    expected = str(settings.backend_service_token or "")
    if not service_token or not expected or not __import__("hmac").compare_digest(service_token, expected):
        raise HTTPException(status_code=401, detail="invalid_service_token")

    if state is not None and state not in ASSET_STATES:
        raise HTTPException(status_code=400, detail=f"invalid state: {state!r}")

    assets = await _get_registry().list_all(state=state)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "capabilities": [a.as_dict() for a in assets],
            "total": len(assets),
        },
    }


@router.get("/{asset_id}")
async def get_capability(
    asset_id: str,
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Get a single capability asset (FR-1)."""
    from app.core.config import settings

    expected = str(settings.backend_service_token or "")
    if not service_token or not expected or not __import__("hmac").compare_digest(service_token, expected):
        raise HTTPException(status_code=401, detail="invalid_service_token")

    asset = await _get_registry().get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="capability_not_found")
    return {
        "code": 0,
        "message": "ok",
        "data": asset.as_dict(),
    }


# --- Change endpoints (018 FR-5 / FR-6 / FR-11 / FR-12) -------------------


def _require_service(service_token: str) -> None:
    from app.core.config import settings
    expected = str(settings.backend_service_token or "")
    if not service_token or not expected or not __import__("hmac").compare_digest(service_token, expected):
        raise HTTPException(status_code=401, detail="invalid_service_token")


@router.post("/{asset_id}/contract")
async def update_asset_contract(
    asset_id: str,
    payload: dict[str, Any],
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Replace the asset contract, bumping the version (FR-5, audited FR-11)."""
    _require_service(service_token)
    try:
        diff = await _get_registry().update_contract(asset_id, payload)
    except AssetError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await _get_registry().audit(asset_id, "contract.updated", {"diff": diff})
    return {"code": 0, "message": "updated", "data": {"diff": diff}}


@router.post("/{asset_id}/state")
async def set_asset_state(
    asset_id: str,
    payload: dict[str, Any],
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Change the asset state; ``offline`` requires an authorized approver (FR-6)."""
    _require_service(service_token)
    state = str(payload.get("state") or "")
    role = str(payload.get("role") or "")
    try:
        await _get_registry().set_state(asset_id, state, role=role)
    except AssetError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail)
    await _get_registry().audit(asset_id, "state.changed", {"state": state, "role": role})
    return {"code": 0, "message": "state_changed", "data": {"state": state}}


@router.post("/{asset_id}/owner")
async def transfer_asset_owner(
    asset_id: str,
    payload: dict[str, Any],
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Transfer the asset owner role (FR-11; audited inside transfer_owner)."""
    _require_service(service_token)
    role = str(payload.get("role") or "")
    try:
        await _get_registry().transfer_owner(asset_id, role)
    except AssetError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "message": "owner_transferred", "data": {"owner_role": role}}


@router.post("/{asset_id}/a2a-exposed")
async def set_asset_a2a_exposed(
    asset_id: str,
    payload: dict[str, Any],
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Explicitly mark/unmark A2A exposure (FR-12; gates 012 AgentCard)."""
    _require_service(service_token)
    exposed = bool(payload.get("a2a_exposed"))
    try:
        asset = await _get_registry().set_a2a_exposed(asset_id, exposed)
    except AssetError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"code": 0, "message": "ok", "data": asset.as_dict()}


__all__ = ["router"]
