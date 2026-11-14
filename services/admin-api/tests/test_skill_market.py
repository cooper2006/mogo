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
    inspect_skill_quality,
    is_low_quality,
    mark_low_quality,
    restore_skill_quality,
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


# --- 016 quality inspection / marking / restore (T999 wired) -------------------

def test_mark_low_quality_flags_when_sustained() -> None:
    assert mark_low_quality("s1", score=0.3, sustained_days=7) is True
    assert mark_low_quality("s1", score=0.3, sustained_days=6) is False


def test_inspect_skill_quality_marks_low_quality() -> None:
    outcome = inspect_skill_quality(
        skill_id="s2",
        total_calls=100,
        successful_calls=20,   # success 0.2
        adopted_calls=10,      # adoption 0.1
        corrected_calls=0,
        sustained_days=7,
    )
    assert outcome["marked_low_quality"] is True
    assert outcome["effect"]["score"] < LOW_QUALITY_THRESHOLD


def test_inspect_skill_quality_keeps_healthy_skill() -> None:
    outcome = inspect_skill_quality(
        skill_id="s3",
        total_calls=100,
        successful_calls=80,
        adopted_calls=60,
        corrected_calls=0,
        sustained_days=14,
    )
    assert outcome["marked_low_quality"] is False


def test_restore_skill_quality_resets_window() -> None:
    record = restore_skill_quality("s4", actor="admin")
    assert record["restored"] is True
    assert record["window_reset_days"] == LOW_QUALITY_SUSTAINED_DAYS
    assert record["ranking"] == "normal"



# --- 016 FR-5 residual: auto-rollback scheduled scan -------------------------

def test_scan_and_auto_rollback_applies_rollback_when_breached() -> None:
    """An active rollout whose error rate exceeds the threshold gets rolled
    back and persisted; healthy rollouts are left untouched."""
    import asyncio
    from app.services.skill_market.canary import (
        Rollout,
        ROLLBACK_SCAN_COLLECTION,
        scan_and_auto_rollback,
        _row_to_rollout,
        _rollout_to_row,
    )

    class _Coll:
        def __init__(self):
            self.rows: list[dict] = []
            self.replaced: list[dict] = []

        def find(self, query):
            def _match(row):
                if "state" in query and "$in" in query["state"]:
                    return row.get("state") in query["state"]["$in"]
                return True
            rows = [r for r in self.rows if _match(r)]
            class _Cur:
                async def to_list(self, length):
                    return rows[:length]
            return _Cur()

        async def replace_one(self, query, doc):
            for row in self.rows:
                if all(row.get(k) == v for k, v in query.items()):
                    row.update(doc)
                    self.replaced.append(dict(doc))
                    return True
            return False

    class _DB:
        def __init__(self, coll):
            self._coll = coll
        def __getitem__(self, name):
            assert name == ROLLBACK_SCAN_COLLECTION
            return self._coll

    coll = _Coll()
    coll.rows.append(_rollout_to_row(Rollout(skill_id="bad", version=2, stable_version=1)))
    bad = coll.rows[0]
    bad["error_count"] = 50
    bad["call_count"] = 100   # 50% > 20% threshold
    good = _rollout_to_row(Rollout(skill_id="good", version=3, stable_version=2))
    good["error_count"] = 2
    good["call_count"] = 100  # 2% < threshold
    coll.rows.append(good)

    applied = asyncio.run(scan_and_auto_rollback(_DB(coll)))
    assert [item["skillId"] for item in applied] == ["bad"]
    assert applied[0]["fromVersion"] == 2
    assert applied[0]["toVersion"] == 1
    # The bad rollout was persisted as rolled_back; the good one untouched.
    assert coll.rows[0]["state"] == "rolled_back"
    assert coll.rows[1]["state"] == "pending"
    assert len(coll.replaced) == 1


def test_scan_and_auto_rollback_respects_min_samples() -> None:
    """Below the minimum sample size no rollback is applied even with a high
    observed error rate (FR-10)."""
    import asyncio
    from app.services.skill_market.canary import Rollout, _rollout_to_row, scan_and_auto_rollback

    class _Coll:
        def __init__(self, rows):
            self.rows = rows
        def find(self, query):
            rows = self.rows
            class _Cur:
                async def to_list(self, length):
                    return rows[:length]
            return _Cur()
        async def replace_one(self, query, doc):
            raise AssertionError("no replacement expected")

    class _DB:
        def __init__(self, rows):
            self._coll = _Coll(rows)
        def __getitem__(self, name):
            return self._coll

    row = _rollout_to_row(Rollout(skill_id="few", version=2, stable_version=1))
    row["error_count"] = 9
    row["call_count"] = 10  # 90% error but only 10 samples (< 20 min)
    applied = asyncio.run(scan_and_auto_rollback(_DB([row])))
    assert applied == []
