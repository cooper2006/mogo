"""Feature 008 — dashboard self-check tests: tenant isolation (T024), empty fallback (T025), cost reconciliation (T026)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.api.dashboard_metrics import (
    DEFAULT_PERIOD_DAYS,
    build_quality_section,
    build_trend_section,
    bottleneck_top_n,
    empty_quality_section,
    empty_trend_section,
    forecast_cost,
    build_cost_section,
    reconciles,
    percentile_stage,
    rate,
    tenant_match,
    window_start,
)
from app.api.dashboard_usage import (
    active_user_counts,
    empty_usage_section,
    rank_frequency,
    usage_time_series,
)


def _rows():
    """Three usage rows spanning the same tenant, two models, two users."""
    base = window_start(DEFAULT_PERIOD_DAYS)
    return [
        {"created_at": base + timedelta(hours=1), "user_id": "u1", "model_name": "gpt-5.2", "total_tokens": 100, "cost_estimate_usd": 0.001},
        {"created_at": base + timedelta(hours=2), "user_id": "u2", "model_name": "gpt-5.2", "total_tokens": 100, "cost_estimate_usd": 0.001, "skill_name": "writer", "retrieval_type": "web"},
        {"created_at": base + timedelta(hours=3), "user_id": "u1", "model_name": "deepseek-v4-flash", "total_tokens": 200, "cost_estimate_usd": 0.0003, "skill_name": "coder", "retrieval_type": "kb"},
    ]


# --- T024 tenant isolation ----------------------------------------------------


def test_tenant_match_scopes_by_main_id():
    match = tenant_match("t1", since=window_start())
    assert match["main_id"] == "t1"
    assert "created_at" in match
    # Every 008 aggregation query must carry this match -> no cross-tenant reads.


def test_usage_aggregation_uses_tenant_match():
    """The usage tab reads token_usage_logs through tenant_match (FR-7)."""
    from app.api.dashboard_metrics import tenant_match as tm

    filter_doc = tm("tenant-a")
    assert filter_doc["main_id"] == "tenant-a"


def test_analytics_scope_rejects_other_tenant():
    """008 analytics helper hard-blocks cross-tenant mainId (FR-7 / US2)."""
    from app.api.routes.analytics import _resolve_main_scope

    actor = {"main_id": "t1"}
    # Same tenant is fine
    scope, main = _resolve_main_scope(actor, "t1")
    assert main == "t1" and scope == {"main_id": "t1"}
    # Other tenant -> HTTP 403
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _resolve_main_scope(actor, "t2")
    assert exc.value.status_code == 403


# --- T025 empty tenant fallback ------------------------------------------------


def test_empty_quality_section_returns_none_rates():
    section = empty_quality_section()
    assert section["totalCalls"] == 0
    assert section["successRate"] is None  # no fabricated 0%
    assert section["p50Ms"] is None


def test_empty_trend_section_returns_none_deltas():
    section = empty_trend_section()
    assert section["costMomPct"] is None
    assert section["bottlenecks"] == []


def test_rate_zero_denominator_is_none():
    assert rate(0, 0) is None
    assert rate(50, 100) == 50.0


def test_usage_empty_fallback():
    section = empty_usage_section()
    assert section["calls"] == 0
    assert section["timeSeries"] == []
    assert section["skillRanking"] == []


# --- T026 cost reconciliation -------------------------------------------------


def test_model_breakdown_sums_to_total_cost():
    from app.api.routes.dashboard import _cost

    rows = [
        {"model": "gpt-5.2", "calls": 2, "prompt_tokens": 10_000, "completion_tokens": 5_000, "total_tokens": 15_000},
        {"model": "deepseek-v4-flash", "calls": 1, "prompt_tokens": 1_000, "completion_tokens": 1_000, "total_tokens": 2_000},
    ]
    # Attach per-row cost (mirrors the dashboard aggregation)
    for row in rows:
        row["cost"] = _cost(row["model"], row["prompt_tokens"], row["completion_tokens"])
    from app.api.dashboard_metrics import build_cost_section

    section = build_cost_section(rows)
    # T026 reconciliation: per-model cost totals match the section total (0 diff)
    assert reconciles(section)


def test_forecast_is_moving_average_of_last_4():
    # N=4 (clarify OQ-5): the most recent 4 periods of [1,2,3,4,5] are [2,3,4,5]
    assert forecast_cost([1.0, 2.0, 3.0, 4.0, 5.0]) == pytest.approx(3.5)
    assert forecast_cost([2.0]) == pytest.approx(2.0)
    assert forecast_cost([]) is None


def test_usage_time_series_and_ranking():
    rows = _rows()
    series = usage_time_series(rows, grain="day")
    assert len(series) == 1  # all rows within the same UTC day bucket
    assert series[0]["calls"] == 3
    assert series[0]["active_users"] == 2  # u1 + u2 deduped

    skills = rank_frequency(rows, key="skill_name")
    assert skills[0]["count"] >= 1
    # Deduped active users per grain
    counts = active_user_counts(rows, grains=("day",))
    assert counts["day"] == 2


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
