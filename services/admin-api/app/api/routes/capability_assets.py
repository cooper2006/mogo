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


__all__ = ["router"]
