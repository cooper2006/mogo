"""Canary rollout + rollback endpoints (feature 016).

Minimal production wiring: exposes canary evaluation and manual rollback.
Automatic rollback scheduling and MongoDB persistence tracked as follow-ups.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException

from app.services.skill_market.canary import (
    DEFAULT_CANARY_ROLLBACK_THRESHOLD,
    DEFAULT_MIN_CANARY_SAMPLES,
    Rollout,
    evaluate_canary,
    apply_rollback,
)

router = APIRouter(prefix="/api/skills/canary", tags=["skill-canary"])

# In-memory rollout store. Production uses MongoDB (FR-10).
_rollouts: dict[str, Rollout] = {}


def _require_service(token: str) -> None:
    from app.core.config import settings
    expected = str(settings.backend_service_token or "")
    if not token or not expected or not __import__("hmac").compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="invalid_service_token")


@router.post("")
async def create_rollout(
    payload: dict[str, Any],
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Start a canary rollout for a Skill version (FR-4)."""
    _require_service(service_token)

    skill_id = str(payload.get("skill_id") or "").strip()
    version = int(payload.get("version") or 0)
    stable_version = int(payload.get("stable_version") or 0)
    target_tenants = [str(t) for t in payload.get("target_tenants") or []]

    if not skill_id or version <= 0:
        raise HTTPException(status_code=400, detail="skill_id and version required")

    rollout = Rollout(
        skill_id=skill_id,
        version=version,
        stable_version=stable_version,
        target_tenants=target_tenants,
    )
    _rollouts[skill_id] = rollout
    return {
        "code": 0,
        "message": "rollout_started",
        "data": {
            "skill_id": skill_id,
            "version": version,
            "stable_version": stable_version,
            "target_tenants": target_tenants,
            "state": rollout.state,
        },
    }


@router.post("/{skill_id}/record")
async def record_rollout_calls(
    skill_id: str,
    payload: dict[str, Any],
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Record call/error counts for a canary rollout (FR-4 / FR-5)."""
    _require_service(service_token)

    rollout = _rollouts.get(skill_id)
    if rollout is None:
        raise HTTPException(status_code=404, detail="rollout_not_found")

    calls = int(payload.get("calls") or 0)
    errors = int(payload.get("errors") or 0)
    rollout.record_calls(calls=calls, errors=errors)
    return {
        "code": 0,
        "message": " recorded",
        "data": {
            "skill_id": skill_id,
            "call_count": rollout.call_count,
            "error_count": rollout.error_count,
            "error_rate": round(rollout.error_rate(), 4),
            "state": rollout.state,
        },
    }


@router.get("/{skill_id}")
async def evaluate_rollout(
    skill_id: str,
    threshold: Optional[float] = None,
    min_samples: Optional[int] = None,
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Evaluate canary health and decide rollback (FR-5)."""
    _require_service(service_token)

    rollout = _rollouts.get(skill_id)
    if rollout is None:
        raise HTTPException(status_code=404, detail="rollout_not_found")

    decision = evaluate_canary(
        rollout,
        threshold=float(threshold or DEFAULT_CANARY_ROLLBACK_THRESHOLD),
        min_samples=int(min_samples or DEFAULT_MIN_CANARY_SAMPLES),
    )
    return {
        "code": 0,
        "message": "evaluated",
        "data": {
            "skill_id": skill_id,
            "state": decision.state,
            "error_rate": round(decision.error_rate, 4),
            "should_rollback": decision.should_rollback,
            "reason": decision.reason,
            "sample_sufficient": decision.sample_sufficient,
        },
    }


@router.post("/{skill_id}/rollback")
async def do_rollback(
    skill_id: str,
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Manually trigger rollback for a canary rollout (FR-11)."""
    _require_service(service_token)

    rollout = _rollouts.get(skill_id)
    if rollout is None:
        raise HTTPException(status_code=404, detail="rollout_not_found")

    decision = evaluate_canary(rollout)
    result = apply_rollback(rollout, decision)
    if not result:
        return {"code": 0, "message": "no_rollback_needed", "data": {
            "skill_id": skill_id,
            "state": rollout.state,
            "error_rate": round(rollout.error_rate(), 4),
        }}
    return {
        "code": 0,
        "message": "rollback_applied",
        "data": result,
    }


__all__ = ["router"]
