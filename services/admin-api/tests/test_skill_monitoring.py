"""Tests for 016 FR-1 / FR-2: skill usage monitoring + anomaly drill-down.

Covers the service layer (``skill_monitoring``) with an in-memory fake DB,
and the route wiring (router registration + 401/400 paths) without a live
MongoDB.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from app.services.skill_market import skill_monitoring


MAIN = "acme-0000000000000000000000"
SKILL = "pdf-report"


def _utc_today() -> date:
    """The day the monitor buckets by.

    ``skill_monitoring`` anchors every window on
    ``datetime.now(timezone.utc).date()``, so seeded rows must use the same
    anchor. Using ``date.today()`` here made these tests fail for the eight
    hours after local midnight in any zone east of UTC (local date had rolled
    over while the UTC date had not), i.e. a wall-clock-dependent red CI.
    """
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# Fake DB (motor-compatible subset)
# ---------------------------------------------------------------------------


class _Cursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def sort(self, key, direction=1):
        self._rows = sorted(self._rows, key=lambda d: str(d.get(key) or ""))
        return self

    async def to_list(self, length=None):
        # Motor's `AsyncIOMotorCursor.to_list` is a coroutine; the fake must
        # match that contract so `await ...to_list(...)` works in production code.
        data = self._rows
        if length is not None:
            data = data[:length]
        return data


def _matches(doc: dict, flt: dict) -> bool:
    for key, value in flt.items():
        if isinstance(value, dict):
            for op, operand in value.items():
                actual = doc.get(key)
                if op == "$gte":
                    if not (actual is not None and actual >= operand):
                        return False
                elif op == "$lt":
                    if not (actual is not None and actual < operand):
                        return False
                elif op == "$lte":
                    if not (actual is not None and actual <= operand):
                        return False
                elif op == "$in":
                    if actual not in operand:
                        return False
                elif op == "$ne":
                    if actual == operand:
                        return False
                else:
                    raise AssertionError(f"unsupported op {op}")
        elif doc.get(key) != value:
            return False
    return True


class _Col:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = docs

    def find(self, flt, projection=None):
        rows = [dict(d) for d in self.docs if _matches(d, flt)]
        return _Cursor(rows)

    async def find_one(self, flt, projection=None):
        for d in self.docs:
            if _matches(d, flt):
                return dict(d)
        return None


class _DB:
    def __init__(self, collections: dict[str, list[dict]]) -> None:
        self._colls = {name: _Col(docs) for name, docs in collections.items()}

    def __getitem__(self, name: str) -> _Col:
        return self._colls.setdefault(name, _Col([]))


def _seed_metrics(days: int = 3, calls_per_day: int = 40, success_frac: float = 0.85) -> _DB:
    today = _utc_today()
    docs = []
    for offset in range(days):
        day = (today - timedelta(days=days - 1 - offset)).isoformat()
        total = calls_per_day
        success = int(round(total * success_frac))
        docs.append(
            {
                "tenant_id": MAIN,
                "skill_key": SKILL,
                "date": day,
                "total_calls": total,
                "successful_calls": success,
                "adopted_calls": 0,
                "corrected_calls": 0,
                "success_tracked": True,
            }
        )
    return _DB({"skill_quality_metrics": docs})


# ---------------------------------------------------------------------------
# FR-1: skill_usage_monitor
# ---------------------------------------------------------------------------


def test_monitor_day_granularity_series() -> None:
    db = _seed_metrics(days=3)
    result = asyncio.run(
        skill_monitoring.skill_usage_monitor(db, tenant_id=MAIN, skill_key=SKILL, days=3, granularity="day")
    )
    assert result["data_available"] is True
    assert len(result["series"]) == 3
    for point in result["series"]:
        assert point["calls"] == 40
        assert point["success"] == 34
        assert point["errors"] == 6
        assert point["success_rate"] == pytest.approx(0.85, abs=0.001)
    assert result["totals"]["calls"] == 120
    assert result["totals"]["success"] == 102
    assert result["totals"]["errors"] == 18
    # success + error rates are complementary (spec FR-1).
    assert result["totals"]["success_rate"] + result["totals"]["error_rate"] == pytest.approx(1.0, abs=0.001)


def test_monitor_empty_when_no_data() -> None:
    db = _DB({})
    result = asyncio.run(
        skill_monitoring.skill_usage_monitor(db, tenant_id="nope", skill_key="x", days=1)
    )
    assert result["data_available"] is False
    assert result["series"] == []
    assert result["totals"]["calls"] == 0
    # Honest: rates are None (no denominator), not fabricated 0.0-as-signal.
    assert result["totals"]["success_rate"] is None
    assert result["totals"]["error_rate"] is None


def test_monitor_unknown_granularity_raises() -> None:
    db = _DB({})
    with pytest.raises(skill_monitoring.MonitorError):
        asyncio.run(
            skill_monitoring.skill_usage_monitor(db, tenant_id=MAIN, granularity="week")
        )


def test_monitor_invalid_days_raises() -> None:
    db = _DB({})
    with pytest.raises(skill_monitoring.MonitorError):
        asyncio.run(skill_monitoring.skill_usage_monitor(db, tenant_id=MAIN, days=0))


def test_monitor_hour_granularity_approximate() -> None:
    """Hour granularity redistributes day buckets evenly; the approximation
    is flagged so callers do not mistake it for real per-hour data."""
    db = _seed_metrics(days=1, calls_per_day=24, success_frac=1.0)
    result = asyncio.run(
        skill_monitoring.skill_usage_monitor(db, tenant_id=MAIN, skill_key=SKILL, days=1, granularity="hour")
    )
    assert result["data_available"] is True
    # Only slots inside the seeded day are emitted.
    emitted = [p for p in result["series"] if not p.get("approximate")]
    approx = [p for p in result["series"] if p.get("approximate")]
    assert len(approx) > 0
    # The hour window is aligned to the last 24 slots ending "now", so only the
    # slots that fall inside the seeded day are emitted. That count depends on
    # the wall clock, so assert the per-slot distribution (24 calls / 24 slots
    # = 1 each) and that the emitted total matches the emitted slot count.
    assert all(p["calls"] == 1 for p in approx)
    today_iso = _utc_today().isoformat()
    total_calls = sum(p["calls"] for p in result["series"] if p["time"].startswith(today_iso))
    assert total_calls == len([p for p in result["series"] if p["time"].startswith(today_iso)])


def test_monitor_skill_key_filter() -> None:
    db = _seed_metrics(days=2)
    db["skill_quality_metrics"].docs.append(
        {"tenant_id": MAIN, "skill_key": "other", "date": _utc_today().isoformat(),
         "total_calls": 99, "successful_calls": 0}
    )
    result = asyncio.run(
        skill_monitoring.skill_usage_monitor(db, tenant_id=MAIN, skill_key=SKILL, days=2, granularity="day")
    )
    assert result["totals"]["calls"] == 80  # only the SKILL buckets
    all_result = asyncio.run(
        skill_monitoring.skill_usage_monitor(db, tenant_id=MAIN, days=2, granularity="day")
    )
    assert all_result["totals"]["calls"] == 179  # SKILL + other


# ---------------------------------------------------------------------------
# FR-2: skill_anomaly_drilldown
# ---------------------------------------------------------------------------


def _seed_audit_events(n: int = 5) -> list[dict]:
    day = date.today().isoformat()
    return [
        {
            "event_id": f"ev-{i}",
            "tenant_id": MAIN,
            "event_type": "skill.selected",
            "skill_key": SKILL,
            "payload": {"version": 3, "ok": i % 2 == 0},
            "created_at": f"{day}T08:00:{i:02d}",
        }
        for i in range(n)
    ]


def test_drilldown_returns_buckets_and_events() -> None:
    day = date.today().isoformat()
    db = _DB({
        "skill_quality_metrics": [
            {"tenant_id": MAIN, "skill_key": SKILL, "date": day,
             "total_calls": 10, "successful_calls": 4}
        ],
        "kernel_event_projections": _seed_audit_events(5),
    })
    result = asyncio.run(
        skill_monitoring.skill_anomaly_drilldown(db, tenant_id=MAIN, skill_key=SKILL, day=day)
    )
    assert len(result["buckets"]) == 1
    assert result["buckets"][0]["total_calls"] == 10
    assert result["buckets"][0]["successful_calls"] == 4
    assert result["events_available"] is True
    assert len(result["events"]) == 5
    assert result["events"][0]["event_id"] == "ev-0"


def test_drilldown_no_events_honest() -> None:
    day = date.today().isoformat()
    db = _DB({
        "skill_quality_metrics": [
            {"tenant_id": MAIN, "skill_key": SKILL, "date": day,
             "total_calls": 10, "successful_calls": 4}
        ],
        "kernel_event_projections": [],
    })
    result = asyncio.run(
        skill_monitoring.skill_anomaly_drilldown(db, tenant_id=MAIN, skill_key=SKILL, day=day)
    )
    assert result["events_available"] is False
    assert result["events"] == []
    # Buckets still present — the anomaly data itself is real.
    assert len(result["buckets"]) == 1


def test_drilldown_no_day_buckets() -> None:
    day = "2000-01-01"
    db = _DB({"skill_quality_metrics": []})
    result = asyncio.run(
        skill_monitoring.skill_anomaly_drilldown(db, tenant_id=MAIN, skill_key=SKILL, day=day)
    )
    assert result["buckets"] == []
    assert result["events_available"] is False


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


def test_monitoring_router_is_registered() -> None:
    """The two FR-1/FR-2 routes exist on the API router (wired into main)."""
    from app.api.router import api_router

    def _collect(router) -> set[str]:
        # Newer FastAPI versions wrap each include_router() call in an
        # `_IncludedRouter`, which has neither `.path` nor `.routes` — the real
        # sub-router is on `.original_router`. Walk both shapes.
        found: set[str] = set()
        for route in getattr(router, "routes", []):
            path = getattr(route, "path", None)
            if path is not None:
                found.add(path)
            nested = getattr(route, "original_router", None)
            if nested is None and hasattr(route, "routes"):
                nested = route
            if nested is not None:
                found |= _collect(nested)
        return found

    paths = _collect(api_router)
    assert "/api/skills/monitor/usage" in paths
    assert "/api/skills/monitor/anomaly/{day}" in paths


def test_monitor_route_rejects_invalid_token() -> None:
    """401 without a valid service token (same gate as the canary routes)."""
    from app.api.routes import skill_monitoring as ep

    with pytest.raises(Exception) as exc_info:
        ep._require_service("wrong-token")
    # The HTTPException carries 401.
    from fastapi import HTTPException

    assert isinstance(exc_info.value, HTTPException)
    assert exc_info.value.status_code == 401
