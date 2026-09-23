"""Friction / MR / deprecation tests (011 T005-T006, T011-T013, T014-T016, T017-T018)."""

from __future__ import annotations

import pytest

from app.services.dream_cycle.deprecation import (
    AdoptionStore,
    detect_low_adoption,
    deprecation_flow,
    mark_deprecated,
    SkillAdoption,
)
from app.services.dream_cycle.friction import (
    FrictionFragment,
    FrictionStore,
    extract_friction_from_signals,
)
from app.services.dream_cycle.mr import (
    build_candidate,
    generate_improvement_mr,
    plan_improvements,
)


# --- T005 friction capture ---------------------------------------------------


def test_extract_three_friction_categories():
    signals = [
        {"key": "a", "tool": "web", "retries": 2},
        {"key": "b", "tool": "web", "retries": 1, "fell_back": True},
        {"key": "c", "tool": "search", "timed_out": True},
        {"key": "d", "tool": "web"},  # no friction -> skipped
        {"key": "", "tool": "web", "retries": 3},  # blank key -> skipped
    ]
    fragments = extract_friction_from_signals(signals)
    categories = [f.category for f in fragments]
    assert "retry" in categories
    assert "fallback" in categories
    assert "timeout" in categories
    assert len(fragments) == 3


def test_friction_fragment_fields_complete():
    store = FrictionStore()
    fragments = extract_friction_from_signals(
        [{"key": "k1", "tool": "t1", "retries": 2, "stage": "plan", "prompt": "x" * 300, "outcome": "ok"}],
        store=store,
    )
    frag = fragments[0]
    doc = frag.as_document()
    # T006 US1: fragment field completeness
    for field_name in ("key", "category", "tool", "stage", "prompt_preview", "outcome", "created_at"):
        assert field_name in doc
    # prompt preview is compact (truncated to the limit)
    assert len(doc["prompt_preview"]) <= 120
    # persisted to the experience store
    assert len(store.rows) == 1


def test_friction_store_recent():
    store = FrictionStore()
    extract_friction_from_signals([{"key": "a", "tool": "t", "retries": 1}], store=store)
    assert len(store.recent(limit=10)) == 1


# --- T011/T012 MR vs draft ----------------------------------------------------


def test_high_confidence_generates_mr():
    candidate = build_candidate({"key": "improve-x", "jaccard": 0.8, "samples": 6})
    mr = generate_improvement_mr(candidate)
    assert mr is not None
    assert mr.key == "improve-x"
    assert mr.label == "improvement-mr"
    assert mr.target_dir.endswith("drafts")


def test_low_confidence_draft_only():
    candidate = build_candidate({"key": "draft-y", "jaccard": 0.5, "samples": 10})
    assert generate_improvement_mr(candidate) is None
    mrs, drafts = plan_improvements([candidate])
    assert mrs == []
    assert len(drafts) == 1
    assert drafts[0].status == "draft"


def test_draft_vs_mr_boundary():
    high = build_candidate({"key": "h", "jaccard": 0.7, "samples": 5})
    low = build_candidate({"key": "l", "jaccard": 0.6, "samples": 5})
    mrs, drafts = plan_improvements([high, low])
    assert [m.key for m in mrs] == ["h"]
    assert {d.key for d in drafts} == {"h", "l"}
    # T012: draft is the universal middle state (high -> draft->mr, low -> draft)
    by_key = {d.key: d for d in drafts}
    assert by_key["h"].status == "draft->mr"
    assert by_key["l"].status == "draft"


def test_t013_us3_high_vs_low():
    # US3: high-confidence auto-MR; low-confidence draft only (T013)
    candidates = [
        build_candidate({"key": "A", "jaccard": 0.9, "samples": 8}),
        build_candidate({"key": "B", "jaccard": 0.9, "samples": 4}),  # samples < 5 -> low
        build_candidate({"key": "C", "jaccard": 0.3, "samples": 20}),  # jaccard < 0.7 -> low
    ]
    mrs, _drafts = plan_improvements(candidates)
    assert [m.key for m in mrs] == ["A"]


# --- T014/T015 deprecation ----------------------------------------------------


def test_low_adoption_detection():
    skill = SkillAdoption(skill_key="s", tenant_id="t1", exposure=25, adopted=2)
    # 2/25 = 0.08 < 0.10 and exposure >= 20 -> low adoption
    assert detect_low_adoption(skill) is True


def test_high_adoption_not_flagged():
    skill = SkillAdoption(skill_key="s", tenant_id="t1", exposure=25, adopted=5)
    # 5/25 = 0.20 >= 0.10 -> not low
    assert detect_low_adoption(skill) is False


def test_deprecation_flow_marks_and_shares_flag():
    store = AdoptionStore()
    for _ in range(25):
        store.record_exposure("skill-a", "t1")
    # no adoption -> low
    record = deprecation_flow("skill-a", "t1", store)
    assert record["action"] == "deprecated"
    assert record["marked_low_quality"] is True
    # shared with 016
    assert store.flags["skill-a"]["marked_low_quality"] is True


def test_deprecation_flow_keeps_healthy_skill():
    store = AdoptionStore()
    for _ in range(10):
        store.record_exposure("skill-b", "t1")
    for _ in range(5):
        store.record_adoption("skill-b", "t1")
    record = deprecation_flow("skill-b", "t1", store)
    assert record["action"] == "kept"


# --- T015 manual restore ------------------------------------------------------


def test_manual_restore_resets_and_reenables():
    store = AdoptionStore()
    for _ in range(25):
        store.record_exposure("skill-c", "t1")
    deprecation_flow("skill-c", "t1", store)
    assert store.get("skill-c").is_deprecated is True
    result = store.restore("skill-c")
    assert result["restored"] is True
    assert result["marked_low_quality"] is False
    # adoption counters reset
    assert store.get("skill-c").exposure == 0
    assert store.get("skill-c").is_deprecated is False
    assert result["recommendation"] == "re-enabled"


def test_t016_us4_low_adoption_and_restore():
    store = AdoptionStore()
    for _ in range(30):
        store.record_exposure("skill-d", "t2")
    # low adoption (0 adopted) -> deprecated
    record = deprecation_flow("skill-d", "t2", store)
    assert record["action"] == "deprecated"
    # manual restore resets counters + re-enables recommendation
    restored = store.restore("skill-d")
    assert restored["marked_low_quality"] is False
    assert store.get("skill-d").exposure == 0


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
