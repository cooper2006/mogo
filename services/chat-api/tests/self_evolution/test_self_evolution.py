"""Tests for the Dream Cycle core (feature 011): friction / similarity / fragments."""

from __future__ import annotations

import pytest

from app.self_evolution.fragment import ExperienceFragment, FragmentStore
from app.self_evolution.friction import (
    AUTO_CAPTURED,
    FrictionKind,
    detect_friction,
    detect_friction_batch,
)
from app.self_evolution.similarity import (
    DEFAULT_JACCARD_THRESHOLD,
    DEFAULT_MIN_SAMPLES,
    cluster_by_similarity,
    edit_distance,
    is_high_confidence,
    jaccard,
    normalized_edit_similarity,
    similarity,
)


# --- friction detection ------------------------------------------------------

def test_failed_then_succeeded_after_retry_is_captured() -> None:
    signal = detect_friction(attempts=3, succeeded=True)
    assert signal is not None
    assert signal.kind == FrictionKind.FAILED_THEN_SUCCEEDED.value
    assert signal.retries == 2
    assert signal.captured_automatically


def test_success_without_retry_is_not_friction() -> None:
    assert detect_friction(attempts=1, succeeded=True) is None


def test_human_correction_is_captured() -> None:
    signal = detect_friction(corrected=True, feedback="should use metric units")
    assert signal is not None
    assert signal.kind == FrictionKind.HUMAN_CORRECTION.value
    assert signal.feedback == "should use metric units"


def test_explicit_mark_requires_user_action() -> None:
    # Not captured unless the user explicitly marks it.
    assert detect_friction(attempts=1, succeeded=True) is None
    signal = detect_friction(explicit_mark=True, feedback="this went wrong")
    assert signal is not None
    assert signal.kind == FrictionKind.EXPLICIT_MARK.value
    assert not signal.captured_automatically


def test_explicit_mark_takes_priority() -> None:
    signal = detect_friction(attempts=3, succeeded=True, corrected=True, explicit_mark=True)
    assert signal is not None
    assert signal.kind == FrictionKind.EXPLICIT_MARK.value


def test_auto_captured_set_matches_clarify() -> None:
    assert AUTO_CAPTURED == {"failed_then_succeeded", "human_correction"}


def test_detect_friction_batch() -> None:
    signals = detect_friction_batch(
        [
            {"attempts": 3, "succeeded": True},
            {"attempts": 1, "succeeded": True},   # no friction
            {"corrected": True},
        ]
    )
    assert len(signals) == 2


# --- similarity --------------------------------------------------------------

def test_jaccard_identical_sets() -> None:
    assert jaccard(["a", "b"], ["a", "b"]) == 1.0


def test_jaccard_partial_overlap() -> None:
    # {a,b} vs {b,c} -> |{b}| / |{a,b,c}| = 1/3
    assert jaccard(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)


def test_jaccard_normalizes_case_and_whitespace() -> None:
    assert jaccard(["  A ", "b"], ["a", "B"]) == 1.0


def test_jaccard_empty_sets() -> None:
    assert jaccard([], []) == 0.0


def test_edit_distance_identical() -> None:
    assert edit_distance(["a", "b", "c"], ["a", "b", "c"]) == 0


def test_edit_distance_substitution() -> None:
    assert edit_distance(["a", "b"], ["a", "c"]) == 1


def test_edit_distance_insertion_deletion() -> None:
    assert edit_distance(["a", "b", "c"], ["a", "c"]) == 1
    assert edit_distance([], ["a", "b"]) == 2


def test_normalized_edit_similarity_bounds() -> None:
    assert normalized_edit_similarity(["a"], ["a"]) == 1.0
    assert normalized_edit_similarity(["a", "b"], ["c", "d"]) == 0.0


def test_similarity_uses_jaccard() -> None:
    assert similarity(["a", "b"], ["a", "b"]) == 1.0


def test_is_high_confidence_thresholds() -> None:
    assert is_high_confidence(0.7, 5) is True
    assert is_high_confidence(0.69, 5) is False   # below Jaccard threshold
    assert is_high_confidence(0.9, 4) is False    # too few samples


def test_default_thresholds_match_clarify() -> None:
    assert DEFAULT_JACCARD_THRESHOLD == 0.7
    assert DEFAULT_MIN_SAMPLES == 5


def test_cluster_by_similarity_groups_similar_scenes() -> None:
    fragments = [
        ExperienceFragment(scene=["invoice", "pdf", "parse"]),
        ExperienceFragment(scene=["invoice", "pdf", "parse"]),
        ExperienceFragment(scene=["photo", "resize", "export"]),
    ]
    clusters = cluster_by_similarity(fragments)
    assert len(clusters) == 2
    assert len(clusters[0]) == 2


# --- fragment store ----------------------------------------------------------

def test_fragment_store_assigns_ids() -> None:
    store = FragmentStore()
    fragment = store.add(ExperienceFragment(scene=["a"]))
    assert fragment.fragment_id
    assert len(store) == 1


def test_fragment_store_scopes_by_tenant() -> None:
    store = FragmentStore()
    store.add(ExperienceFragment(scene=["a"], tenant_id="t1"))
    store.add(ExperienceFragment(scene=["b"], tenant_id="t2"))
    assert len(store.all("t1")) == 1


def test_fragment_as_document_includes_source_session_and_feedback() -> None:
    fragment = ExperienceFragment(scene=["a"], source_session="s-1", feedback="fix units")
    document = fragment.as_document()
    assert document["source_session"] == "s-1"
    assert document["feedback"] == "fix units"
    assert document["scene"] == ["a"]
