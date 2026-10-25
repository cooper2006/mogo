"""026 T057 测试 — 性能回归判定端到端验证（真链）。"""
from __future__ import annotations

import pytest

from app.infrastructure.observability.perf_baseline import (
    PerfBaselineCollector,
    PerfBaselineRecord,
)
from app.infrastructure.observability.perf_budget import PerfBudgetChecker, PerfBudgetThreshold

from tools.perf.e2e_regression_check import records_to_percentiles, run_chain


def _spans(name: str, durs_ms) -> list:
    now = 1_000_000.0
    return [
        {"name": name, "duration_ms": d, "finished_at": now, "error": False}
        for d in durs_ms
    ]


def _checker(thresholds=None):
    checker = PerfBudgetChecker(service_name="chat-api")
    checker.thresholds = thresholds or [
        PerfBudgetThreshold(endpoint="/api/v1/chat/completions", metric="p95_ms",
                            max_value=2000.0, service="chat-api")
    ]
    return checker


class TestRecordsToPercentiles:
    def test_shapes(self):
        recs = [
            PerfBaselineRecord(endpoint="/a", method="span", p50_ms=10, p95_ms=20, p99_ms=30, sample_count=5),
        ]
        out = records_to_percentiles(recs)
        assert out["/a"]["p95"] == 20
        assert out["/a"]["count"] == 5

    def test_empty(self):
        assert records_to_percentiles([]) == {}


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_pass_when_within_budget(self):
        collector = PerfBaselineCollector()
        spans = _spans("/api/v1/chat/completions", [100, 200, 300, 400, 500])
        result = await run_chain(collector, _checker(), spans, [])
        assert result["breached"] == []
        assert result["regressions"] == []
        assert "/api/v1/chat/completions" in result["collected_endpoints"]

    @pytest.mark.asyncio
    async def test_breach_when_p95_over_budget(self):
        collector = PerfBaselineCollector()
        # P95 ≈ 1900ms，仍在 2000ms 内；改用 5000ms 大值触发 breach
        spans = _spans("/api/v1/chat/completions", [100, 200, 5000, 6000, 7000])
        result = await run_chain(collector, _checker(), spans, [])
        assert any(b["endpoint"] == "/api/v1/chat/completions" for b in result["breached"])

    @pytest.mark.asyncio
    async def test_regression_when_degraded_more_than_ratio(self):
        collector = PerfBaselineCollector()
        # 历史 P95=100ms，新 P95=300ms → 劣化 3x > 1.2
        hist = [
            PerfBaselineRecord(endpoint="/api/v1/chat/completions", method="span", p95_ms=100.0, sample_count=10),
        ]
        spans = _spans("/api/v1/chat/completions", [250, 260, 270, 280, 300])
        result = await run_chain(collector, _checker(), spans, hist)
        assert len(result["regressions"]) == 1
        assert result["regressions"][0]["endpoint"] == "/api/v1/chat/completions"
        assert result["regressions"][0]["current_value"] > 1.2

    @pytest.mark.asyncio
    async def test_no_regression_within_ratio(self):
        collector = PerfBaselineCollector()
        hist = [
            PerfBaselineRecord(endpoint="/api/v1/chat/completions", method="span", p95_ms=200.0, sample_count=10),
        ]
        spans = _spans("/api/v1/chat/completions", [180, 190, 200, 210, 220])
        result = await run_chain(collector, _checker(), spans, hist)
        assert result["regressions"] == []