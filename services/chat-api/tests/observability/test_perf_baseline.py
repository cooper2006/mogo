"""026 T006/T007/T008 — 性能基线采集与耗时拆分测试。"""
from __future__ import annotations

import pytest

from app.infrastructure.observability.execution_trace import (
    PerfBreakdown,
    dependency_breakdown,
    infer_span_kind,
)
from app.infrastructure.observability.perf_baseline import (
    PerfBaselineCollector,
    PerfBaselineRecord,
    _percentile,
)
from app.infrastructure.observability.spans import (
    SpanState,
    drain_completed_spans,
    emit_completed_span,
    log_span,
    recent_completed_spans,
)


class TestPercentile:
    def test_empty(self) -> None:
        assert _percentile([], 0.95) == 0.0

    def test_single(self) -> None:
        assert _percentile([42.0], 0.5) == 42.0

    def test_known(self) -> None:
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        assert _percentile(sorted(values), 0.50) == 50.0
        assert _percentile(sorted(values), 0.95) == 100.0
        assert _percentile(sorted(values), 0.99) == 100.0


class TestPerfBaselineCollect:
    async def test_collect_groups_by_name(self) -> None:
        collector = PerfBaselineCollector()
        spans = [
            {"name": "db.query.users", "duration_ms": 10.0, "finished_at": 1.0},
            {"name": "db.query.users", "duration_ms": 30.0, "finished_at": 2.0},
            {"name": "llm.completion", "duration_ms": 500.0, "finished_at": 3.0},
        ]
        records = await collector.collect(spans)
        by_name = {r.endpoint: r for r in records}
        assert "db.query.users" in by_name
        assert by_name["db.query.users"].sample_count == 2
        assert by_name["db.query.users"].p95_ms == 30.0
        assert by_name["llm.completion"].sample_count == 1
        assert by_name["llm.completion"].p50_ms == 500.0

    async def test_collect_empty(self) -> None:
        collector = PerfBaselineCollector()
        assert await collector.collect([]) == []

    async def test_persist_and_query(self) -> None:
        collector = PerfBaselineCollector()
        record = PerfBaselineRecord(endpoint="/chat", method="POST", p95_ms=1500.0)
        await collector.persist(record)
        got = await collector.query("/chat")
        assert len(got) == 1
        assert got[0].p95_ms == 1500.0
        # 重复持久化同 endpoint 覆盖旧值
        record2 = PerfBaselineRecord(endpoint="/chat", method="POST", p95_ms=2000.0)
        await collector.persist(record2)
        assert (await collector.query("/chat"))[0].p95_ms == 2000.0


class TestSpanBuffer:
    def test_emit_and_drain(self) -> None:
        drain_completed_spans()  # 清空
        emit_completed_span({"name": "db.query", "duration_ms": 1.0})
        emit_completed_span({"name": "db.query", "duration_ms": 2.0})
        drained = drain_completed_spans()
        assert len(drained) == 2
        assert drain_completed_spans() == []  # 清空后为空

    def test_recent_does_not_drain(self) -> None:
        drain_completed_spans()
        emit_completed_span({"name": "x", "duration_ms": 1.0})
        assert len(recent_completed_spans(limit=10)) == 1
        assert len(recent_completed_spans(limit=0)) == 0

    def test_log_span_records_completed(self) -> None:
        drain_completed_spans()
        with log_span("db.query", kind="database", duration_ms=None):
            pass  # type: ignore[arg-type]  # kind 传给 attrs
        drained = drain_completed_spans()
        assert len(drained) == 1
        assert drained[0]["name"] == "db.query"
        assert drained[0]["kind"] == "database"
        assert "duration_ms" in drained[0]


class TestDependencyBreakdown:
    def test_infer_kinds(self) -> None:
        assert infer_span_kind("mongo.find") == "database"
        assert infer_span_kind("db.query") == "database"
        assert infer_span_kind("redis.get") == "cache"
        assert infer_span_kind("llm.completion") == "llm"
        assert infer_span_kind("httpx.post") == "external_http"
        assert infer_span_kind("s3.upload") == "filesystem"
        assert infer_span_kind("some.random") == "other"

    def test_breakdown_shares(self) -> None:
        spans = [
            {"name": "mongo.find", "duration_ms": 100.0},
            {"name": "redis.get", "duration_ms": 200.0},
            {"name": "llm.completion", "duration_ms": 700.0},
        ]
        bd = dependency_breakdown(spans, request_duration_ms=1000.0)
        assert isinstance(bd, PerfBreakdown)
        assert bd.total_ms == 1000.0
        by_kind = {i.kind: i for i in bd.items}
        assert set(by_kind.keys()) == {"database", "cache", "llm"}
        assert by_kind["llm"].share == pytest.approx(0.7)
        assert by_kind["cache"].share == pytest.approx(0.2)
        assert by_kind["database"].share == pytest.approx(0.1)
        # 按耗时降序
        assert [i.kind for i in bd.items] == ["llm", "cache", "database"]

    def test_breakdown_explicit_kind_wins(self) -> None:
        spans = [{"name": "weird.name", "duration_ms": 50.0, "kind": "database"}]
        bd = dependency_breakdown(spans)
        assert bd.items[0].kind == "database"
        assert bd.unknown_spans == []

    def test_breakdown_unknown(self) -> None:
        spans = [{"name": "random.op", "duration_ms": 10.0}]
        bd = dependency_breakdown(spans)
        # 未分类 span 归入 other 桶（占比分母含之），并在 unknown_spans 点名
        assert len(bd.items) == 1
        assert bd.items[0].kind == "other"
        assert bd.items[0].share == pytest.approx(1.0)
        assert bd.unknown_spans == ["random.op"]