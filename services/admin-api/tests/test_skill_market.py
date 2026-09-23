"""Tests for skill market hardening (feature 016): scoring / canary."""

from __future__ import annotations

import pytest

from app.services.skill_market.canary import (
    DEFAULT_CANARY_ROLLBACK_THRESHOLD,
    DEFAULT_MIN_CANARY_SAMPLES,
    CanaryError,
    Rollout,
    RolloutState,
    apply_rollback,
    evaluate_canary,
)
from app.services.skill_market.scoring import (
    EFFECT_WEIGHTS,
    LOW_QUALITY_MARKER,
    LOW_QUALITY_SUSTAINED_DAYS,
    LOW_QUALITY_THRESHOLD,
    compute_effect_score,
    is_low_quality,
)


# --- effect scoring ----------------------------------------------------------

def test_effect_weights_match_clarify() -> None:
    assert EFFECT_WEIGHTS == {"success": 0.5, "adoption": 0.3, "correction_inverse": 0.2}


def test_perfect_skill_scores_one() -> None:
    score = compute_effect_score(
        total_calls=100, successful_calls=100, adopted_calls=100, corrected_calls=0
    )
    assert score.score == pytest.approx(1.0)


def test_worst_skill_scores_only_correction_weight() -> None:
    # 0 success, 0 adoption, all corrected -> 1.0 * 0.0 + 1.0 * 0.0 + 0.0 * 0.2
    score = compute_effect_score(
        total_calls=100, successful_calls=0, adopted_calls=0, corrected_calls=100
    )
    assert score.score == pytest.approx(0.0)


def test_effect_score_blends_components() -> None:
    # success 1.0*0.5 + adoption 0.5*0.3 + (1-0.2)*0.2 = 0.5+0.15+0.16 = 0.81
    score = compute_effect_score(
        total_calls=100, successful_calls=100, adopted_calls=50, corrected_calls=20
    )
    assert score.score == pytest.approx(0.81)


def test_effect_score_empty_sample_is_zero() -> None:
    assert compute_effect_score(total_calls=0, successful_calls=0, adopted_calls=0, corrected_calls=0).score == 0.0


def test_weights_are_configurable() -> None:
    score = compute_effect_score(
        total_calls=10,
        successful_calls=10,
        adopted_calls=0,
        corrected_calls=0,
        weights={"success": 1.0, "adoption": 0.0, "correction_inverse": 0.0},
    )
    assert score.score == pytest.approx(1.0)


def test_low_quality_thresholds_match_clarify() -> None:
    assert LOW_QUALITY_THRESHOLD == 0.4
    assert LOW_QUALITY_SUSTAINED_DAYS == 7
    assert LOW_QUALITY_MARKER == "marked_low_quality"


def test_is_low_quality_requires_both_conditions() -> None:
    assert is_low_quality(score=0.3, sustained_days=7) is True
    assert is_low_quality(score=0.3, sustained_days=6) is False   # not sustained long enough
    assert is_low_quality(score=0.5, sustained_days=10) is False  # above threshold


# --- canary ------------------------------------------------------------------

def test_defaults_match_clarify() -> None:
    assert DEFAULT_CANARY_ROLLBACK_THRESHOLD == 0.20
    assert DEFAULT_MIN_CANARY_SAMPLES == 20


def test_rollout_requires_skill_id() -> None:
    with pytest.raises(CanaryError):
        Rollout(skill_id="", version=1)


def test_record_calls_sets_running() -> None:
    rollout = Rollout(skill_id="s", version=2, stable_version=1)
    rollout.record_calls(calls=10, errors=1)
    assert rollout.state == RolloutState.RUNNING.value
    assert rollout.error_rate() == pytest.approx(0.1)


def test_record_calls_rejects_invalid_counts() -> None:
    rollout = Rollout(skill_id="s", version=2)
    with pytest.raises(CanaryError):
        rollout.record_calls(calls=5, errors=6)


def test_canary_below_threshold_does_not_rollback() -> None:
    rollout = Rollout(skill_id="s", version=2, stable_version=1)
    rollout.record_calls(calls=100, errors=5)   # 5% < 20%
    decision = evaluate_canary(rollout)
    assert decision.should_rollback is False
    assert decision.sample_sufficient is True


def test_canary_above_threshold_rolls_back() -> None:
    rollout = Rollout(skill_id="s", version=2, stable_version=1)
    rollout.record_calls(calls=100, errors=30)  # 30% > 20%
    decision = evaluate_canary(rollout)
    assert decision.should_rollback is True
    assert decision.state == RolloutState.ROLLED_BACK.value


def test_canary_insufficient_samples_not_judged() -> None:
    rollout = Rollout(skill_id="s", version=2, stable_version=1)
    rollout.record_calls(calls=5, errors=5)     # 100% but tiny sample
    decision = evaluate_canary(rollout)
    assert decision.should_rollback is False
    assert decision.sample_sufficient is False


def test_apply_rollback_records_stable_target() -> None:
    rollout = Rollout(skill_id="s", version=2, stable_version=1)
    rollout.record_calls(calls=100, errors=30)
    decision = evaluate_canary(rollout)
    audit = apply_rollback(rollout, decision)
    assert audit["action"] == "rollback"
    assert audit["toVersion"] == 1
    assert rollout.state == RolloutState.ROLLED_BACK.value


def test_apply_rollback_noop_when_not_needed() -> None:
    rollout = Rollout(skill_id="s", version=2, stable_version=1)
    rollout.record_calls(calls=100, errors=1)
    assert apply_rollback(rollout, evaluate_canary(rollout)) == {}
