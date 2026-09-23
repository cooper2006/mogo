"""Shared aggregation helpers for the four-dimension operations dashboard (008).

These helpers are deliberately *pure-ish* (they take a db handle and return data)
so they can be unit-tested with a fake collection. They implement the shared
concerns of every dimension:

* tenant isolation filter (FR-7) — every query is scoped by ``main_id``;
* time-window computation in **UTC** (FR-3): cross-midnight data belongs to the
  UTC day;
* empty-tenant fallback (FR-9): metrics return 0 / ``None`` rather than raising.

Dimension-specific metrics:

* quality (US4): success rate, P50/P95 latency, anomaly rate, manual-intervention
  rate (FR-4);
* trend (US5): period-over-period (环比) and year-over-year (同比), bottleneck
  top-5 by cost/latency (FR-5).

Clarify decisions honored here:
* manual-intervention rate = ``approval_pending`` count / total calls;
* P50/P95 from ``token_usage_logs.duration_ms`` via Mongo ``$percentile``;
* bottleneck = top-5 by cost/latency (no statistical significance).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

TOKEN_USAGE_COLLECTION = "token_usage_logs"
APPROVAL_EVENTS_COLLECTION = "approval_events"

# Anomaly = failed + timeout (merged, per FR-4 clarify).
ANOMALY_STATUSES = ("failed", "timeout", "error")

# Trend compare windows (日环比 + 周同比), configurable.
DEFAULT_PERIOD_DAYS = 1
DEFAULT_YOY_DAYS = 7

# Bottleneck: top-N by cost / latency.
DEFAULT_BOTTLENECK_TOP_N = 5


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def window_start(days: int = DEFAULT_PERIOD_DAYS, *, now: datetime | None = None) -> datetime:
    """Start of a UTC window ending now (cross-midnight -> UTC day boundary)."""
    reference = now or utcnow()
    return reference - timedelta(days=max(1, int(days)))


def previous_window(
    days: int = DEFAULT_PERIOD_DAYS, *, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """The window immediately before the current one (for period-over-period)."""
    reference = now or utcnow()
    current_start = reference - timedelta(days=max(1, int(days)))
    previous_start = current_start - timedelta(days=max(1, int(days)))
    return previous_start, current_start


def tenant_match(main_id: str, *, since: datetime | None = None) -> dict[str, Any]:
    """Build the tenant-isolation match filter (FR-7)."""
    match: dict[str, Any] = {"main_id": str(main_id or "default")}
    if since is not None:
        match["created_at"] = {"$gte": since}
    return match


def _is_anomaly(status: Any) -> bool:
    return str(status or "").strip().lower() in ANOMALY_STATUSES


def rate(numerator: int, denominator: int) -> Optional[float]:
    """Percentage rate, or ``None`` when the denominator is 0 (empty tenant)."""
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 2)


def build_quality_section(
    *,
    total_calls: int,
    failed_calls: int,
    anomaly_calls: int,
    approval_pending: int,
    p50_ms: Optional[int],
    p95_ms: Optional[int],
    avg_ms: Optional[int] = None,
) -> dict[str, Any]:
    """Assemble the quality dimension (US4 / FR-4).

    Empty tenant (no calls) yields ``None`` rates — never a division error.
    """
    return {
        "totalCalls": int(total_calls),
        "successRate": rate(max(0, total_calls - failed_calls), total_calls),
        "anomalyRate": rate(anomaly_calls, total_calls),
        "manualInterventionRate": rate(approval_pending, total_calls),
        "p50Ms": p50_ms,
        "p95Ms": p95_ms,
        "avgMs": avg_ms,
        "approvalPending": int(approval_pending),
    }


def build_trend_section(
    *,
    current_cost: float,
    previous_cost: float,
    current_calls: int,
    previous_calls: int,
    yoy_cost: float | None = None,
) -> dict[str, Any]:
    """Period-over-period (环比) + year-over-year (同比) deltas (US5 / FR-5)."""
    return {
        "costMomPct": _pct_delta(current_cost, previous_cost),
        "callsMomPct": _pct_delta(current_calls, previous_calls),
        "costYoyPct": _pct_delta(current_cost, yoy_cost) if yoy_cost is not None else None,
    }


def _pct_delta(current: float, baseline: float | None) -> Optional[float]:
    if baseline is None or baseline == 0:
        return None
    return round(((current - baseline) / baseline) * 100, 2)


def bottleneck_top_n(
    rows: Iterable[dict[str, Any]],
    *,
    n: int = DEFAULT_BOTTLENECK_TOP_N,
    dimension: str = "model",
) -> list[dict[str, Any]]:
    """Top-N bottleneck entries by cost, labelling the dimension.

    ``rows`` are pre-aggregated ``[{dimension, calls, cost, duration_sum, timed_calls}]``.
    Sorted by cost desc, then by average latency desc for ties.
    """
    entries: list[dict[str, Any]] = []
    for row in rows:
        timed = int(row.get("timed_calls") or 0)
        duration_sum = int(row.get("duration_sum") or 0)
        avg_ms = int(duration_sum / timed) if timed else 0
        entries.append(
            {
                "dimension": dimension,
                "key": str(row.get(dimension) or row.get("_id") or ""),
                "calls": int(row.get("calls") or 0),
                "cost": round(float(row.get("cost") or 0.0), 4),
                "avgDurationMs": avg_ms,
            }
        )
    entries.sort(key=lambda item: (item["cost"], item["avgDurationMs"]), reverse=True)
    return entries[: max(1, int(n))]


def percentile_stage(field: str = "duration_ms") -> dict[str, Any]:
    """Mongo ``$percentile`` aggregation stage for P50/P95.

    ``token_usage_logs`` stores ``start_time`` / ``end_time`` (epoch millis) rather
    than a materialized ``duration_ms``, so the duration is computed inline before
    the percentile is taken (T004).
    """
    return {
        "$project": {
            f"{field}_percentiles": {
                "$percentile": {
                    "input": {
                        "$max": [
                            0,
                            {
                                "$subtract": [
                                    {"$ifNull": ["$end_time", 0]},
                                    {"$ifNull": ["$start_time", 0]},
                                ]
                            },
                        ]
                    },
                    "p": [0.5, 0.95],
                    "method": "approximate",
                }
            }
        }
    }


def extract_percentiles(document: dict[str, Any] | None, field: str = "duration_ms") -> tuple[Optional[int], Optional[int]]:
    """Pull (p50, p95) out of a ``$percentile`` result document."""
    if not document:
        return None, None
    values = document.get(f"{field}_percentiles")
    if not isinstance(values, list) or len(values) < 2:
        return None, None
    try:
        p50 = int(round(float(values[0])))
        p95 = int(round(float(values[1])))
    except (TypeError, ValueError):
        return None, None
    return p50, p95
