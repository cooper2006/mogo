"""Dream-cycle runner tests (011 T001-T016).

Covers: candidate ranking, validation, dry-run, shadow rollout, and the full
cycle report (T001-T008); plus the dry-run acceptance (T009) and shadow-
acceptance (T010) self-checks.
"""

from __future__ import annotations

import pytest

from app.services.dream_cycle.runner import (
    DreamCandidate,
    apply_dry_run,
    apply_shadow,
    rank_candidates,
    run_dream_cycle,
    validate_candidates,
)


def _signals():
    return [
        {"key": "sig-a", "score": 0.9, "note": "strong"},
        {"key": "sig-b", "score": 0.5},
        {"key": "sig-c", "score": 0.1},
        {"key": "", "score": 0.99},  # blank key -> filtered out
    ]


# --- T002 candidate ranking -------------------------------------------------


def test_rank_candidates_top_n():
    ranked = rank_candidates(_signals(), top_n=2)
    assert [c.key for c in ranked] == ["sig-a", "sig-b"]
    # Higher score -> smaller rank
    assert ranked[0].rank() < ranked[1].rank()


def test_rank_candidates_filters_blank_keys():
    ranked = rank_candidates(_signals(), top_n=10)
    assert all(c.key for c in ranked)
    assert len(ranked) == 3


# --- T004 candidate validation ----------------------------------------------


def test_validate_candidates_with_validator():
    cands = rank_candidates(_signals(), top_n=3)
    kept = validate_candidates(cands, validator=lambda c: c.score >= 0.5)
    assert [c.key for c in kept] == ["sig-a", "sig-b"]


def test_validate_candidates_no_validator_keeps_all():
    cands = rank_candidates(_signals(), top_n=3)
    kept = validate_candidates(cands)
    assert len(kept) == 3


# --- T005 dry-run ------------------------------------------------------------


def test_apply_dry_run_changes_nothing():
    journal_calls: list[tuple[str, dict]] = []
    cands = [DreamCandidate("k1", 0.8), DreamCandidate("k2", 0.6)]
    count = apply_dry_run(cands, journal=lambda op, data: journal_calls.append((op, data)))
    assert count == 2
    assert all(op == "dry_run" for op, _ in journal_calls)


# --- T005 shadow rollout -----------------------------------------------------


def test_apply_shadow_routes_traffic():
    journal_calls: list[tuple[str, dict]] = []
    cands = [DreamCandidate("k1", 0.8)]
    count = apply_shadow(cands, shadow_ratio=0.1, journal=lambda op, data: journal_calls.append((op, data)))
    assert count == 1
    assert journal_calls[0][0] == "shadow"
    assert journal_calls[0][1]["shadow_ratio"] == 0.1


def test_apply_shadow_zero_ratio_applies_nothing():
    cands = [DreamCandidate("k1", 0.8)]
    assert apply_shadow(cands, shadow_ratio=0.0) == 0


# --- T001/T008 full cycle ----------------------------------------------------


def test_run_dream_cycle_dry_run():
    result = run_dream_cycle(signals=_signals(), dry_run=True, top_n=2)
    assert result.dry_run is True
    assert result.candidates == 2
    assert result.applied == 2
    assert result.cycle_id.startswith("dream-")


def test_run_dream_cycle_shadow():
    result = run_dream_cycle(signals=_signals(), dry_run=False, shadow_ratio=0.1, top_n=2)
    assert result.dry_run is False
    assert result.applied == 2
    assert result.report["shadow_ratio"] == 0.1


def test_run_dream_cycle_report_shape():
    result = run_dream_cycle(signals=_signals(), dry_run=True)
    for field in ("candidates", "validated", "applied", "dry_run", "report"):
        assert hasattr(result, field)
    assert result.report["top_n"] > 0


# --- T009 dry-run acceptance -------------------------------------------------


def test_dry_run_acceptance_does_not_mutate():
    # Dry-run must not apply any real change: journal records the plan only.
    journal_calls: list[tuple[str, dict]] = []
    result = run_dream_cycle(
        signals=_signals(),
        dry_run=True,
        journal=lambda op, data: journal_calls.append((op, data)),
        top_n=3,
    )
    assert result.applied == 3
    assert all(op == "dry_run" for op, _ in journal_calls)
    assert not any(op == "shadow" for op, _ in journal_calls)


# --- T010 shadow acceptance --------------------------------------------------


def test_shadow_acceptance_ratio_bounds():
    cands = [DreamCandidate(f"k{i}", 0.5) for i in range(5)]
    # Ratio > 1 clamps to 1 (all apply)
    assert apply_shadow(cands, shadow_ratio=2.0) == 5
    # Ratio < 0 clamps to 0 (none apply)
    assert apply_shadow(cands, shadow_ratio=-0.5) == 0
    assert apply_shadow(cands, shadow_ratio=0.5) == 5


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
