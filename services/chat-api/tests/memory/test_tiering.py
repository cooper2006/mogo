"""Tests for 017 density tiering (FR-13 / FR-14 / FR-15)."""

from __future__ import annotations

import time

from app.memory.tiering import (
    NoopSummarizer,
    SUMMARY_REFRESH_DAYS_DEFAULT,
    TierResult,
    decide_tierable,
    is_summary_stale,
    tier_content,
)


class FakeSummarizer:
    def __init__(self) -> None:
        self.calls = 0

    def summarize(self, content: str):
        self.calls += 1
        return (content[:10], f"overview:{content[:5]}")


def test_decide_tierable_text() -> None:
    assert decide_tierable("hello") is True


def test_decide_tierable_empty() -> None:
    assert decide_tierable("") is False


def test_is_summary_stale() -> None:
    now = 1_000_000.0
    assert is_summary_stale(0, 30, now) is True
    assert is_summary_stale(now - 31 * 86_400, 30, now) is True
    assert is_summary_stale(now - 10 * 86_400, 30, now) is False


def test_tier_content_write_time_supplied() -> None:
    # Write-time: summaries supplied and marked fresh (as the endpoint does).
    r = tier_content(
        "long content", NoopSummarizer(), l0_summary="L0", l1_overview="L1",
        summary_generated_at=time.time(),
    )
    assert r.l0_summary == "L0" and r.l1_overview == "L1"
    assert r.l2_raw == "long content" and r.tierable is True
    assert isinstance(r, TierResult)


def test_tier_content_write_time_stale_overrides() -> None:
    # Supplied but stale (generated_at=0 default) → lazy regeneration wins.
    s = FakeSummarizer()
    r = tier_content("long content", s, l0_summary="L0", l1_overview="L1")
    assert s.calls == 1
    assert r.l0_summary != "L0"


def test_tier_content_lazy_generation() -> None:
    s = FakeSummarizer()
    r = tier_content("some long text here", s)
    assert s.calls == 1
    assert r.l0_summary == "some long " and r.l1_overview.startswith("overview:")
    assert r.summary_generated_at > 0


def test_tier_content_lazy_on_stale() -> None:
    s = FakeSummarizer()
    old = time.time() - 40 * 86_400
    r = tier_content("abc", s, l0_summary="old", summary_generated_at=old, refresh_days=30)
    assert s.calls == 1
    assert r.l0_summary == "abc"[:10]


def test_tier_content_force_refresh() -> None:
    s = FakeSummarizer()
    r = tier_content("abc", s, l0_summary="keep", force_refresh=True)
    assert s.calls == 1


def test_tier_content_non_tierable_rejects_summaries() -> None:
    r = tier_content("x", NoopSummarizer(), tierable=False)
    assert r.tierable is False
    assert r.l0_summary == "" and r.l1_overview == ""
    assert r.summary_generated_at == 0.0


def test_default_refresh_days_constant() -> None:
    assert SUMMARY_REFRESH_DAYS_DEFAULT == 30
