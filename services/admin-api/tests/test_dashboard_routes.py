"""Integration tests for the dashboard aggregation functions (feature 008, T009).

Uses a fake Mongo-like collection so no database is required. Covers the two
Acceptance groups: overview completeness and empty-tenant zero metrics.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.api.routes import dashboard


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        return list(self._rows)


class _FakeCollection:
    def __init__(self, aggregate_rows: list[dict[str, Any]] | None = None, count: int = 0) -> None:
        self._aggregate_rows = aggregate_rows or []
        self._count = count
        self.pipelines: list[list[dict[str, Any]]] = []

    def aggregate(self, pipeline: list[dict[str, Any]]) -> _FakeCursor:
        self.pipelines.append(pipeline)
        return _FakeCursor(self._aggregate_rows)

    async def count_documents(self, *args: Any, **kwargs: Any) -> int:
        return self._count


class _FakeDB:
    def __init__(self, collections: dict[str, _FakeCollection]) -> None:
        self._collections = collections

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._collections.get(name, _FakeCollection())


@pytest.mark.asyncio
async def test_quality_metrics_empty_tenant_returns_zero_and_none() -> None:
    db = _FakeDB({"token_usage_logs": _FakeCollection(aggregate_rows=[])})

    quality = await dashboard._quality_metrics(db, "tenant-empty")

    assert quality["totalCalls"] == 0
    assert quality["successRate"] is None
    assert quality["anomalyRate"] is None
    assert quality["p50Ms"] is None
    assert quality["p95Ms"] is None


@pytest.mark.asyncio
async def test_quality_metrics_computes_rates_from_aggregate() -> None:
    db = _FakeDB(
        {
            "token_usage_logs": _FakeCollection(
                aggregate_rows=[
                    {
                        "calls": 100,
                        "failed": 10,
                        "anomalies": 15,
                        "duration_sum": 20000,
                        "timed_calls": 100,
                    }
                ]
            )
        }
    )

    quality = await dashboard._quality_metrics(db, "tenant-a")

    assert quality["totalCalls"] == 100
    assert quality["successRate"] == 90.0
    assert quality["anomalyRate"] == 15.0
    assert quality["avgMs"] == 200


@pytest.mark.asyncio
async def test_quality_metrics_scopes_by_tenant() -> None:
    collection = _FakeCollection(aggregate_rows=[])
    db = _FakeDB({"token_usage_logs": collection})

    await dashboard._quality_metrics(db, "tenant-scope")

    first_match = collection.pipelines[0][0]["$match"]
    assert first_match["tenant_id"] == "tenant-scope"
    assert "created_at" in first_match  # time window applied


@pytest.mark.asyncio
async def test_trend_metrics_empty_returns_none_deltas() -> None:
    db = _FakeDB({"token_usage_logs": _FakeCollection(aggregate_rows=[])})

    trend = await dashboard._trend_metrics(db, "tenant-empty", current_cost=0.0)

    assert trend["costMomPct"] is None
    assert trend["callsMomPct"] is None
    assert trend["bottlenecks"] == []


@pytest.mark.asyncio
async def test_trend_metrics_bottleneck_ranked_by_cost() -> None:
    db = _FakeDB(
        {
            "token_usage_logs": _FakeCollection(
                aggregate_rows=[
                    {
                        "_id": "gpt-5.4",
                        "calls": 10,
                        "prompt_tokens": 1_000_000,
                        "completion_tokens": 0,
                        "duration_sum": 1000,
                        "timed_calls": 10,
                    },
                    {
                        "_id": "deepseek-v4-flash",
                        "calls": 10,
                        "prompt_tokens": 1000,
                        "completion_tokens": 0,
                        "duration_sum": 500,
                        "timed_calls": 10,
                    },
                ]
            )
        }
    )

    trend = await dashboard._trend_metrics(db, "tenant-a", current_cost=10.0)

    keys = [item["key"] for item in trend["bottlenecks"]]
    assert keys[0] == "gpt-5.4"  # most expensive first
    assert len(trend["bottlenecks"]) <= 5


@pytest.mark.asyncio
async def test_approval_pending_degrades_to_zero_without_store() -> None:
    db = _FakeDB({})
    assert await dashboard._approval_pending_count(db, "tenant-a") == 0


@pytest.mark.asyncio
async def test_cost_section_is_wired_and_reconciles() -> None:
    """008 US2 (audit 2026-10-03): build_cost_section had zero production callers.

    /overview now returns a cost section; the section must reconcile model costs
    to the total (FR-6) and carry an honest department-attribution note.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    usage = _FakeCollection(aggregate_rows=[
        {"_id": "gpt-5.2", "calls": 10, "prompt_tokens": 1000, "completion_tokens": 500},
        {"_id": "deepseek-v4-flash", "calls": 5, "prompt_tokens": 100, "completion_tokens": 50},
    ])
    # _daily_costs uses .find(...) -> a cursor with sort/limit/to_list; emulate a
    # few raw usage rows so the forecast has trailing daily cost to average over.
    usage.raw_rows = [
        {"created_at": now - timedelta(days=1), "model_name": "gpt-5.2", "prompt_tokens": 1000, "completion_tokens": 500},
        {"created_at": now - timedelta(hours=2), "model_name": "gpt-5.2", "prompt_tokens": 1000, "completion_tokens": 500},
    ]
    orig_aggregate = usage.aggregate
    def _find(query, *args, **kwargs):
        class _Cur:
            async def to_list(self, length=None):
                return [dict(r) for r in usage.raw_rows]

            def sort(self, *a, **k):
                return self

            def limit(self, *a, **k):
                return self

        return _Cur()
    usage.find = _find
    usage.aggregate = orig_aggregate

    db = _FakeDB({"token_usage_logs": usage, "user_org_relations": _FakeCollection()})
    section = await dashboard._cost_section(db, "m-1")

    # FR-6: model costs reconcile to the total within tolerance.
    assert section["reconciles"] is True
    assert section["totalCost"] == pytest.approx(sum(m["cost"] for m in section["models"]), abs=0.01)
    # FR-2 honesty: department attribution is not fabricated (agent_id has no source).
    assert section["departmentAttribution"]["available"] is False
    # OQ-5: the 4-period moving average is computed from the trailing daily history.
    assert section["forecast"] is not None
