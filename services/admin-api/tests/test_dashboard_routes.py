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
    assert first_match["main_id"] == "tenant-scope"
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
