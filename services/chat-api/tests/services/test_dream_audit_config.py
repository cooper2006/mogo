"""T017 full-chain audit + T018 configurable thresholds + T019 quickstart/contract (011)."""

from __future__ import annotations

import pytest

from app.services.dream_cycle.evolution_audit import (
    EvolutionConfig,
    audit_capture,
    audit_deprecate,
    audit_generate,
    audit_mr,
    audit_restore,
    record_evolution_event,
)


def _collecting_sink():
    entries: list[dict] = []

    def sink(**kwargs):
        entries.append(dict(kwargs))
        return dict(kwargs)

    return sink, entries


# --- T017 full-chain audit ----------------------------------------------------


def test_capture_audit_event():
    sink, entries = _collecting_sink()
    record_evolution_event(sink, event_type="capture", actor="runner", payload={"key": "k1"})
    assert entries[0]["event_type"] == "capture"
    assert entries[0]["actor"] == "runner"
    assert entries[0]["payload"]["key"] == "k1"


def test_full_chain_events():
    sink, entries = _collecting_sink()
    audit_capture({"key": "frag"}, sink=sink, actor="a")
    audit_generate(3, sink=sink, actor="a")
    audit_mr({"key": "mr-1"}, sink=sink, actor="a")
    audit_deprecate({"skill_key": "s"}, sink=sink, actor="a")
    audit_restore({"skill_key": "s"}, sink=sink, actor="a")
    types = [e["event_type"] for e in entries]
    assert types == ["capture", "generate", "mr", "deprecate", "restore"]


def test_unknown_event_type_rejected():
    sink, _entries = _collecting_sink()
    with pytest.raises(ValueError):
        record_evolution_event(sink, event_type="nope", actor="a")


# --- T018 configurable thresholds ---------------------------------------------


def test_confidence_gate_configurable():
    cfg = EvolutionConfig(jaccard_threshold=0.8, min_samples=10)
    assert cfg.confidence_gate(0.8, 10) is True
    assert cfg.confidence_gate(0.79, 100) is False
    assert cfg.confidence_gate(0.99, 9) is False


def test_low_adoption_gate_configurable():
    cfg = EvolutionConfig(
        low_adoption_window_days=14,
        low_adoption_min_exposure=20,
        low_adoption_rate=0.10,
    )
    # exposure 25, adopted 2 -> rate 0.08 < 0.10 -> low
    assert cfg.is_low_adoption(25, 2, 14) is True
    # exposure 25, adopted 5 -> rate 0.20 >= 0.10 -> not low
    assert cfg.is_low_adoption(25, 5, 14) is False
    # exposure < 20 -> not low even with 0 adopted
    assert cfg.is_low_adoption(10, 0, 14) is False


def test_scan_period_configurable():
    cfg = EvolutionConfig(scan_interval_hours=6)
    assert cfg.scan_interval_hours == 6
    assert cfg.shadow_ratio == 0.1


# --- T019 quickstart + contract ----------------------------------------------


def test_quickstart_and_contract_exist():
    from pathlib import Path

    here = Path(__file__).resolve().parents[3]
    repo_root = here.parent  # services/ -> repo root
    quickstart = repo_root / "specs" / "011-dream-cycle-self-evolution" / "quickstart.md"
    contract = repo_root / "contracts" / "self-evolution.md"
    assert quickstart.exists(), f"missing {quickstart}"
    assert contract.exists(), f"missing {contract}"
    text = quickstart.read_text() + contract.read_text()
    for keyword in ("schema", "mr", "friction", "confidence", "threshold"):
        assert keyword in text.lower(), f"quickstart/contract must document {keyword}"


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
