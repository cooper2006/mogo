"""026 T053 测试 — LLM 耗时占比 × 韧性事件交叉归因。"""
from __future__ import annotations

import pytest

from tools.perf.llm_resilience_correlate import (
    HIGH_LLM_SHARE,
    correlate,
    llm_share_from_breakdown,
    pick_llm_item,
    summarize,
)


class _Item:
    def __init__(self, kind: str, total_ms: float = 0.0, share: float = 0.0) -> None:
        self.kind = kind
        self.total_ms = total_ms
        self.share = share


class _Breakdown:
    """与 execution_trace.PerfBreakdown 鸭子类型兼容的桩。"""

    def __init__(self, items, request_duration_ms=None) -> None:
        self.items = items
        self.request_duration_ms = request_duration_ms


def _mk_breakdown(llm_share: float = 0.8, request_ms: float = 1000.0):
    return _Breakdown(
        [_Item("database", 100, 0.1), _Item("llm", 800, llm_share), _Item("redis", 100, 0.1)],
        request_duration_ms=request_ms,
    )


class TestPickLlmItem:
    def test_picks_llm_item(self):
        bd = _mk_breakdown()
        item = pick_llm_item(bd)
        assert item is not None and item.kind == "llm"

    def test_none_when_missing(self):
        bd = _Breakdown([_Item("database", 100, 1.0)])
        assert pick_llm_item(bd) is None

    def test_share_zero_without_llm(self):
        bd = _Breakdown([_Item("database", 100, 1.0)])
        assert llm_share_from_breakdown(bd) == 0.0


class TestCorrelate:
    def test_matches_by_trace_id(self):
        bd = _mk_breakdown(llm_share=0.8, request_ms=1000.0)
        rows = correlate(
            {"trace-1": bd},
            [{"trace_id": "trace-1", "request_id": "llm_x",
              "resilience_events": {"degradation_step": 2, "failover_from": "model-a"}}],
        )
        assert len(rows) == 1
        assert rows[0].trace_id == "trace-1"
        assert rows[0].llm_share == pytest.approx(0.8)
        assert rows[0].llm_ms == pytest.approx(800)
        assert rows[0].request_ms == pytest.approx(1000)
        assert rows[0].high_llm_share is True
        assert rows[0].resilience_events["degradation_step"] == 2

    def test_skips_records_without_resilience_events(self):
        rows = correlate(
            {"trace-1": _mk_breakdown()},
            [{"trace_id": "trace-1", "request_id": "llm_y", "resilience_events": None}],
        )
        assert rows == []

    def test_skips_empty_trace_id(self):
        rows = correlate(
            {"trace-1": _mk_breakdown()},
            [{"trace_id": "", "request_id": "llm_z",
              "resilience_events": {"degradation_step": 1}}],
        )
        assert rows == []

    def test_unmatched_trace_reports_unknown_share(self):
        rows = correlate(
            {"trace-1": _mk_breakdown()},
            [{"trace_id": "trace-9", "request_id": "llm_w",
              "resilience_events": {"failover_to": "model-b"}}],
        )
        assert len(rows) == 1
        assert rows[0].llm_share == -1.0
        assert rows[0].high_llm_share is False


class TestSummarize:
    def test_summary_counts(self):
        rows = correlate(
            {"trace-1": _mk_breakdown(0.8), "trace-2": _mk_breakdown(0.2)},
            [
                {"trace_id": "trace-1", "request_id": "a",
                 "resilience_events": {"degradation_step": 2}},
                {"trace_id": "trace-2", "request_id": "b",
                 "resilience_events": {"failover_from": "model-a"}},
            ],
        )
        summary = summarize(rows)
        assert summary["correlated_rows"] == 2
        assert summary["high_llm_share_rows"] == 1
        assert summary["degraded_rows"] == 1
        assert summary["degradation_step_distribution"] == {"2": 1}

    def test_high_threshold_constant(self):
        assert HIGH_LLM_SHARE == 0.5