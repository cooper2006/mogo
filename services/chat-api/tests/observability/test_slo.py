"""023 T059 — SLO 错误预算与燃速计算测试。

口径（spec Clarify 决策 OQ-6，2026-10-24）：
- 可用性 99.9%、请求延迟 P99 < 3s、LLM 错误率 < 1%；
- burn rate 双窗口多燃速：快档 1h/6h（阈值 14.4 / 6，page）、慢档 6h/3d（6 / 2）。
"""
from __future__ import annotations

import pytest

from app.common.slo import (
    BurnLevel,
    BurnRate,
    SLOKind,
    SLOSpec,
    compute_error_budget,
    evaluate_burn,
)


def _availability_spec(target: float = 0.999) -> SLOSpec:
    return SLOSpec(name="availability_30d", kind=SLOKind.AVAILABILITY, target=target)


def test_error_budget_remaining_and_consumption():
    spec = _availability_spec()
    budget = compute_error_budget(spec, total_events=1_000_000, bad_events=500)
    assert budget.budget_total == pytest.approx(1000.0)
    assert budget.budget_remaining == pytest.approx(500.0)
    assert budget.budget_consumed_ratio == pytest.approx(0.5)
    assert budget.exhausted is False
    assert budget.observed_ratio == pytest.approx(0.9995)


def test_error_budget_exhausted_when_bad_reaches_budget():
    spec = _availability_spec()
    budget = compute_error_budget(spec, total_events=1_000_000, bad_events=1000)
    assert budget.exhausted is True
    assert budget.budget_remaining == 0.0
    assert budget.budget_consumed_ratio == pytest.approx(1.0)


def test_error_budget_no_observations_is_none():
    spec = _availability_spec()
    budget = compute_error_budget(spec, total_events=0, bad_events=0)
    assert budget.observed_ratio is None
    assert budget.budget_remaining == 0.0


def test_compute_error_budget_rejects_invalid_inputs():
    spec = _availability_spec()
    with pytest.raises(ValueError):
        compute_error_budget(spec, total_events=10, bad_events=20)
    with pytest.raises(ValueError):
        compute_error_budget(spec, total_events=-1, bad_events=0)


def test_slo_spec_rejects_out_of_range_target():
    with pytest.raises(ValueError):
        SLOSpec(name="bad", kind=SLOKind.AVAILABILITY, target=1.0)
    with pytest.raises(ValueError):
        SLOSpec(name="bad", kind=SLOKind.AVAILABILITY, target=0.0)


def test_burn_level_page_fast_when_both_windows_exceed():
    spec = _availability_spec()
    burn = BurnRate(
        short_window_seconds=3600.0,
        long_window_seconds=21600.0,
        short_bad=100.0,
        short_total=1000.0,
        long_bad=100.0,
        long_total=1000.0,
        budget_ratio=spec.budget_ratio,
    )
    assert burn.short_rate == pytest.approx(100.0)
    assert burn.long_rate == pytest.approx(100.0)
    assert evaluate_burn(burn) == BurnLevel.PAGE_FAST


def test_burn_level_none_when_within_budget():
    spec = _availability_spec()
    burn = BurnRate(
        short_window_seconds=3600.0,
        long_window_seconds=21600.0,
        short_bad=1.0,
        short_total=1000.0,
        long_bad=1.0,
        long_total=1000.0,
        budget_ratio=spec.budget_ratio,
    )
    assert evaluate_burn(burn) == BurnLevel.NONE


def test_default_slos_match_clarify_targets():
    """FR-14：首期三件套目标值与 Clarify 决策逐项对应。"""
    from app.common.slo import DEFAULT_SLOS

    by_name = {s.name: s for s in DEFAULT_SLOS}
    assert by_name["availability_30d"].target == pytest.approx(0.999)
    assert by_name["latency_p99_30d"].target == pytest.approx(0.99)
    assert by_name["llm_error_rate_30d"].target == pytest.approx(0.99)
