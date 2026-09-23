"""Tests for the four-dimension dashboard aggregation helpers (feature 008).

Pure-logic helpers (rates, trend deltas, bottleneck ranking, percentile
extraction, UTC windows) are exercised without MongoDB.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.api.dashboard_metrics import (
    ANOMALY_STATUSES,
    DEFAULT_BOTTLENECK_TOP_N,
    bottleneck_top_n,
    build_quality_section,
    build_trend_section,
    extract_percentiles,
    percentile_stage,
    previous_window,
    rate,
    tenant_match,
    window_start,
)


# --- sharing helpers (T002) --------------------------------------------------

def test_tenant_match_scopes_by_main_id() -> None:
    assert tenant_match("tenant-a") == {"main_id": "tenant-a"}


def test_tenant_match_defaults_to_default_tenant() -> None:
    assert tenant_match("") == {"main_id": "default"}


def test_tenant_match_applies_time_window() -> None:
    since = datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert tenant_match("t1", since=since)["created_at"] == {"$gte": since}


def test_window_start_is_utc() -> None:
    now = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
    start = window_start(1, now=now)
    assert start == datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
    assert start.tzinfo is not None


def test_previous_window_is_immediately_before_current() -> None:
    now = datetime(2026, 7, 8, 0, 0, tzinfo=timezone.utc)
    prev_start, prev_end = previous_window(1, now=now)
    assert prev_end == datetime(2026, 7, 7, 0, 0, tzinfo=timezone.utc)
    assert prev_start == datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc)


# --- quality dimension (T004 / US4) -----------------------------------------

def test_rate_is_none_on_empty_tenant() -> None:
    assert rate(0, 0) is None


def test_rate_computes_percentage() -> None:
    assert rate(90, 100) == 90.0


def test_quality_section_full() -> None:
    section = build_quality_section(
        total_calls=100,
        failed_calls=10,
        anomaly_calls=15,
        approval_pending=5,
        p50_ms=120,
        p95_ms=890,
        avg_ms=200,
    )
    assert section["successRate"] == 90.0
    assert section["anomalyRate"] == 15.0
    assert section["manualInterventionRate"] == 5.0
    assert section["p50Ms"] == 120
    assert section["p95Ms"] == 890


def test_quality_section_empty_tenant_returns_none_rates() -> None:
    section = build_quality_section(
        total_calls=0,
        failed_calls=0,
        anomaly_calls=0,
        approval_pending=0,
        p50_ms=None,
        p95_ms=None,
    )
    assert section["successRate"] is None
    assert section["anomalyRate"] is None
    assert section["manualInterventionRate"] is None
    assert section["totalCalls"] == 0


def test_anomaly_statuses_merged() -> None:
    assert set(ANOMALY_STATUSES) == {"failed", "timeout", "error"}


# --- percentiles (T004) ------------------------------------------------------

def test_percentile_stage_shape() -> None:
    stage = percentile_stage("duration_ms")
    projected = stage["$project"]["duration_ms_percentiles"]["$percentile"]
    # duration is computed inline from start_time/end_time (epoch millis)
    assert "$max" in projected["input"]
    assert projected["p"] == [0.5, 0.95]


def test_extract_percentiles_rounds() -> None:
    p50, p95 = extract_percentiles({"duration_ms_percentiles": [120.4, 890.6]})
    assert p50 == 120
    assert p95 == 891


def test_extract_percentiles_handles_missing() -> None:
    assert extract_percentiles(None) == (None, None)
    assert extract_percentiles({}) == (None, None)
    assert extract_percentiles({"duration_ms_percentiles": [1]}) == (None, None)


# --- trend dimension (T006 / US5) -------------------------------------------

def test_trend_section_deltas() -> None:
    section = build_trend_section(
        current_cost=120.0,
        previous_cost=100.0,
        current_calls=220,
        previous_calls=200,
        yoy_cost=80.0,
    )
    assert section["costMomPct"] == 20.0
    assert section["callsMomPct"] == 10.0
    assert section["costYoyPct"] == 50.0


def test_trend_section_none_when_no_baseline() -> None:
    section = build_trend_section(
        current_cost=10.0, previous_cost=0.0, current_calls=5, previous_calls=0
    )
    assert section["costMomPct"] is None
    assert section["callsMomPct"] is None
    assert section["costYoyPct"] is None


def test_bottleneck_top_n_sorted_by_cost() -> None:
    rows = [
        {"model": "a", "calls": 10, "cost": 1.0, "duration_sum": 100, "timed_calls": 10},
        {"model": "b", "calls": 5, "cost": 9.0, "duration_sum": 500, "timed_calls": 5},
        {"model": "c", "calls": 20, "cost": 3.0, "duration_sum": 200, "timed_calls": 10},
    ]
    top = bottleneck_top_n(rows, n=2, dimension="model")
    assert [item["key"] for item in top] == ["b", "c"]
    assert top[0]["cost"] == 9.0
    assert top[0]["avgDurationMs"] == 100


def test_bottleneck_top_n_default_limit() -> None:
    rows = [{"model": f"m{i}", "calls": i, "cost": float(i)} for i in range(10)]
    assert len(bottleneck_top_n(rows)) == DEFAULT_BOTTLENECK_TOP_N


def test_bottleneck_top_n_empty_rows() -> None:
    assert bottleneck_top_n([]) == []
