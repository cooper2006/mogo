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


# --- cost dimension (008 US2 / T010-T012) ------------------------------------

# Float tolerance for the cost reconciliation (FR-6).
COST_TOLERANCE = 0.01

# Cost forecast uses the most recent N periods (clarify OQ-5).
DEFAULT_FORECAST_PERIODS = 4


def build_cost_section(
    rows: Iterable[dict[str, Any]],
    *,
    cost_fn: Any = None,
) -> dict[str, Any]:
    """Assemble the cost dimension: token totals, model share, reconciliation (FR-2/FR-6).

    ``rows`` are per-model aggregates ``[{model, calls, prompt_tokens,
    completion_tokens, cost}]``. The model shares are returned alongside the
    total so the caller can assert ``sum(shares) == total`` within tolerance.
    """
    models: list[dict[str, Any]] = []
    total_tokens = 0
    total_prompt = 0
    total_completion = 0
    total_cost = 0.0

    for row in rows:
        prompt = int(row.get("prompt_tokens") or 0)
        completion = int(row.get("completion_tokens") or 0)
        tokens = int(row.get("total_tokens") or (prompt + completion))
        cost = float(row.get("cost") or 0.0)
        model_name = str(row.get("model") or row.get("_id") or "")
        models.append(
            {
                "model": model_name,
                "calls": int(row.get("calls") or 0),
                "promptTokens": prompt,
                "completionTokens": completion,
                "tokens": tokens,
                "cost": round(cost, 6),
            }
        )
        total_tokens += tokens
        total_prompt += prompt
        total_completion += completion
        total_cost += cost

    models.sort(key=lambda item: item["cost"], reverse=True)
    for item in models:
        item["costShare"] = round(item["cost"] / total_cost, 6) if total_cost else 0.0

    return {
        "totalTokens": total_tokens,
        "promptTokens": total_prompt,
        "completionTokens": total_completion,
        "totalCost": round(total_cost, 6),
        "models": models,
    }


def reconciles(section: dict[str, Any], *, tolerance: float = COST_TOLERANCE) -> bool:
    """Whether a cost section's model costs reconcile to the total (FR-6, 0 diff)."""
    models = section.get("models") or []
    summed = sum(float(item.get("cost") or 0.0) for item in models)
    total = float(section.get("totalCost") or 0.0)
    return abs(summed - total) <= tolerance


def attribute_cost(
    rows: Iterable[dict[str, Any]],
    *,
    dimension: str,
    dimension_of: Any,
) -> list[dict[str, Any]]:
    """Attribute cost by an arbitrary dimension (department / agent, FR-2).

    ``dimension_of`` maps a row to its dimension value; rows with no value fall
    into ``未分配``.
    """
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(dimension_of(row) or "").strip() or "未分配"
        bucket = buckets.setdefault(
            key, {"key": key, "dimension": dimension, "calls": 0, "tokens": 0, "cost": 0.0}
        )
        bucket["calls"] += int(row.get("calls") or 0)
        bucket["tokens"] += int(row.get("total_tokens") or 0)
        bucket["cost"] += float(row.get("cost") or 0.0)
    items = sorted(buckets.values(), key=lambda item: item["cost"], reverse=True)
    for item in items:
        item["cost"] = round(item["cost"], 6)
    return items


def forecast_cost(
    history: Iterable[float],
    *,
    periods: int = DEFAULT_FORECAST_PERIODS,
) -> Optional[float]:
    """Forecast the next period's cost from the most recent ``periods`` values.

    Uses a simple moving average over the trailing window (clarify OQ-5); returns
    ``None`` when there is no history to forecast from.
    """
    values = [float(item) for item in history]
    if not values:
        return None
    window = values[-max(1, int(periods)) :]
    if not window:
        return None
    return round(sum(window) / len(window), 6)
