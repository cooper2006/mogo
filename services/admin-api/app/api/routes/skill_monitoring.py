"""Skill usage monitoring + anomaly drill-down endpoints (016 FR-1 / FR-2).

* **FR-1** — ``GET /api/skills/monitor/usage`` aggregates the real
  invocation counters (``skill_quality_metrics`` daily buckets, fed by the
  016 collector from chat-api's durable event journal) into volume /
  success-rate / error-rate series at day / hour / minute granularity.
* **FR-2** — ``GET /api/skills/monitor/anomaly/{day}`` drills into one
  anomalous day: the contributing buckets plus the individual
  ``skill.selected`` events from the audit journal when available.

Both degrade honestly: no data → ``data_available=False`` /
``events_available=False``, never fabricated counters.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from app.core.db import get_db
from app.services.skill_market.skill_monitoring import (
    MonitorError,
    skill_anomaly_drilldown,
    skill_usage_monitor,
)

router = APIRouter(prefix="/api/skills/monitor", tags=["skill-monitoring"])


def _require_service(token: str) -> None:
    from app.core.config import settings

    expected = str(settings.backend_service_token or "")
    if not token or not expected or not __import__("hmac").compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="invalid_service_token")


def _main_id(payload_key: str, query_main_id: str) -> str:
    return str(query_main_id or payload_key or "").strip()


@router.get("/usage")
async def monitor_usage(
    main_id: str = Query(default=""),
    skill_key: str = Query(default=""),
    days: int = Query(default=7, ge=1, le=366),
    granularity: str = Query(default="day"),
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """FR-1: skill usage monitoring (volume / success-rate / error-rate series)."""
    _require_service(service_token)
    if not main_id:
        raise HTTPException(status_code=400, detail="main_id is required")
    try:
        db = get_db()
        result = await skill_usage_monitor(
            db,
            main_id=main_id,
            skill_key=skill_key,
            days=days,
            granularity=granularity,
        )
    except MonitorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "message": "ok", "data": result}


@router.get("/anomaly/{day}")
async def monitor_anomaly_drilldown(
    day: str,
    main_id: str = Query(default=""),
    skill_key: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=500),
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """FR-2: drill down one anomalous day (buckets + underlying skill events)."""
    _require_service(service_token)
    if not main_id or not skill_key:
        raise HTTPException(status_code=400, detail="main_id and skill_key are required")
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="day must be ISO format YYYY-MM-DD")
    db = get_db()
    result = await skill_anomaly_drilldown(
        db,
        main_id=main_id,
        skill_key=skill_key,
        day=day,
        limit=limit,
    )
    return {"code": 0, "message": "ok", "data": result}


__all__ = ["router"]
