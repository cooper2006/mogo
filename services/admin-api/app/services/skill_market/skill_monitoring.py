"""Skill invocation monitoring + anomaly drill-down (016 FR-1 / FR-2 residual).

* **FR-1** — :func:`skill_usage_monitor` aggregates the real invocation records
  (``skill_quality_metrics`` daily buckets written by the 016 collector from
  chat-api's durable ``kernel_event_projections`` skill events) into
  volume / success-rate / error-rate series at a configurable time granularity
  (minute / hour / day).
* **FR-2** — :func:`skill_anomaly_drilldown` takes a single anomalous bucket and
  returns the drill-down detail: the contributing day buckets and, when
  available, the underlying ``kernel_event_projections`` skill-event rows.

Both functions degrade honestly: with no data they return empty series, they
never fabricate counters, and a missing audit source is reported as such.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Daily-bucket collection written by quality_metrics.record_skill_call
#: (fed by the 016 collector from chat-api kernel_event_projections).
USAGE_COLLECTION = "skill_quality_metrics"

#: chat-api durable event journal (read-only from admin-api) — FR-2 drill-down
#: source for the individual skill-execution events.
AUDIT_COLLECTION = "kernel_event_projections"

#: Time granularities accepted by the monitor query.
TIME_GRANULARITIES: tuple[str, ...] = ("minute", "hour", "day")


class MonitorError(ValueError):
    """Raised for an invalid monitoring query."""


def _bucket_date_range(*, days: int, as_of: Optional[date] = None) -> tuple[str, str]:
    """Return the inclusive [start, end] ISO dates for the last ``days`` days."""
    end = as_of or datetime.now(timezone.utc).date()
    start = end - timedelta(days=max(days - 1, 0))
    return start.isoformat(), end.isoformat()


def _day_from_bucket_key(key: dict[str, Any]) -> str:
    return str(key.get("date") or "")


async def skill_usage_monitor(
    db: Any,
    *,
    main_id: str,
    skill_key: str = "",
    days: int = 7,
    granularity: str = "day",
    as_of: Optional[date] = None,
) -> dict[str, Any]:
    """FR-1: skill usage monitoring query.

    Aggregates the daily buckets into ``series`` (volume, successful,
    error/failed, success rate, error rate) at the requested granularity:

    * ``day``    — one point per day bucket (the native resolution);
    * ``hour``   — one point per hour for the last 24h (buckets carry only
      day-level resolution; hours are distributed evenly within their day —
      the approximation is reported as ``approximate`` so callers never
      mistake it for per-hour reality);
    * ``minute`` — one point per minute for the last 60 minutes, same
      honest-approximation semantics as ``hour``.

    When no buckets exist the monitor returns an empty series with
    ``data_available=False`` — it does not fabricate zeros as signal.
    """
    if granularity not in TIME_GRANULARITIES:
        raise MonitorError(f"unknown granularity: {granularity!r}")
    if days < 1:
        raise MonitorError("days must be >= 1")

    start, end = _bucket_date_range(days=days, as_of=as_of)
    flt: dict[str, Any] = {
        "main_id": main_id,
        "date": {"$gte": start, "$lte": end},
    }
    if skill_key:
        flt["skill_key"] = skill_key

    rows = (await db[USAGE_COLLECTION].find(flt).to_list(length=4096)) or []

    series: list[dict[str, Any]] = []
    totals = {"calls": 0, "success": 0, "errors": 0}

    if granularity == "day":
        by_day: dict[str, dict[str, int]] = {}
        for row in rows:
            day = _day_from_bucket_key(row)
            bucket = by_day.setdefault(day, {"calls": 0, "success": 0, "errors": 0})
            bucket["calls"] += int(row.get("total_calls") or 0)
            bucket["success"] += int(row.get("successful_calls") or 0)
        for day in sorted(by_day):
            b = by_day[day]
            b["error_rate"] = round(1.0 - (b["success"] / b["calls"]), 4) if b["calls"] else 0.0
            b["success_rate"] = round(b["success"] / b["calls"], 4) if b["calls"] else 0.0
            series.append({"time": day, **b})
            totals["calls"] += b["calls"]
            totals["success"] += b["success"]
            totals["errors"] += b["calls"] - b["success"]
    else:
        # hour / minute: redistribute day buckets evenly across their slots.
        steps = 24 if granularity == "hour" else 60
        window_days = 1 if granularity == "hour" else 1
        anchor = as_of or datetime.now(timezone.utc).date()
        day_rows: dict[str, dict[str, int]] = {}
        for row in rows:
            day = _day_from_bucket_key(row)
            if (anchor - timedelta(days=window_days)).isoformat() <= day <= anchor.isoformat():
                day_rows.setdefault(day, {"calls": 0, "success": 0})
                day_rows[day]["calls"] += int(row.get("total_calls") or 0)
                day_rows[day]["success"] += int(row.get("successful_calls") or 0)

        for day in sorted(day_rows):
            base = day_rows[day]
            per_call = base["calls"] / steps
            per_success = base["success"] / steps
            base_dt = datetime.fromisoformat(day)
            base_dt = base_dt.replace(tzinfo=timezone.utc)
            # Align the window to the last ``steps`` slots ending at "now".
            now = datetime.now(timezone.utc)
            if granularity == "hour":
                slot_step = timedelta(hours=1)
            else:
                slot_step = timedelta(minutes=1)
            slot_start = now - slot_step * (steps - 1)
            for i in range(steps):
                slot = slot_start + slot_step * i
                if slot.date().isoformat() != day:
                    continue
                calls_i = int(round(per_call))
                success_i = int(round(per_success))
                success_i = min(success_i, calls_i)
                errors_i = calls_i - success_i
                slot_label = (
                    slot.strftime("%Y-%m-%dT%H:00") if granularity == "hour"
                    else slot.strftime("%Y-%m-%dT%H:%M")
                )
                series.append(
                    {
                        "time": slot_label,
                        "calls": calls_i,
                        "success": success_i,
                        "errors": errors_i,
                        "success_rate": round(success_i / calls_i, 4) if calls_i else 0.0,
                        "error_rate": round(errors_i / calls_i, 4) if calls_i else 0.0,
                        "approximate": True,
                    }
                )
                totals["calls"] += calls_i
                totals["success"] += success_i
                totals["errors"] += errors_i

    data_available = bool(rows)
    return {
        "main_id": main_id,
        "skill_key": skill_key,
        "granularity": granularity,
        "days": days if granularity == "day" else 1,
        "data_available": data_available,
        "totals": {
            **totals,
            "success_rate": round(totals["success"] / totals["calls"], 4) if totals["calls"] else None,
            "error_rate": round(totals["errors"] / totals["calls"], 4) if totals["calls"] else None,
        },
        "series": series,
    }


async def skill_anomaly_drilldown(
    db: Any,
    *,
    main_id: str,
    skill_key: str,
    day: str,
    limit: int = 100,
) -> dict[str, Any]:
    """FR-2: drill down one anomalous day bucket.

    Returns the contributing day buckets plus the individual skill-event rows
    from ``kernel_event_projections`` (``skill.selected`` events) for that
    tenant/skill/day. When the audit collection is empty or unavailable the
    detail is honestly reported as ``events_available=False`` — never
    fabricated.
    """
    day_fl = {"main_id": main_id, "skill_key": skill_key, "date": day}
    day_rows = await db[USAGE_COLLECTION].find(day_fl).to_list(length=16)
    buckets = [
        {
            "skill_key": str(row.get("skill_key") or ""),
            "date": _day_from_bucket_key(row),
            "total_calls": int(row.get("total_calls") or 0),
            "successful_calls": int(row.get("successful_calls") or 0),
            "success_tracked": bool(row.get("success_tracked")),
        }
        for row in day_rows
    ]

    events: list[dict[str, Any]] = []
    events_available = False
    try:
        cursor = db[AUDIT_COLLECTION].find(
            {
                "main_id": main_id,
                "event_type": "skill.selected",
                "created_at": {
                    "$gte": f"{day}T00:00:00",
                    "$lt": f"{(date.fromisoformat(day) + timedelta(days=1)).isoformat()}T00:00:00",
                },
            }
        )
        for row in await cursor.to_list(length=max(int(limit), 1)):
            events.append(
                {
                    "event_id": str(row.get("event_id") or row.get("_id") or ""),
                    "skill_key": str(row.get("skill_key") or ""),
                    "payload": row.get("payload") or {},
                    "created_at": str(row.get("created_at") or ""),
                }
            )
        events_available = bool(events)
    except Exception as exc:  # pragma: no cover - defensive, audit source optional
        logger.warning("anomaly drill-down: audit source unavailable: %s", exc)
        events_available = False

    return {
        "main_id": main_id,
        "skill_key": skill_key,
        "day": day,
        "buckets": buckets,
        "events": events,
        "events_available": events_available,
        "limit": limit,
    }


__all__ = [
    "MonitorError",
    "TIME_GRANULARITIES",
    "skill_usage_monitor",
    "skill_anomaly_drilldown",
]
