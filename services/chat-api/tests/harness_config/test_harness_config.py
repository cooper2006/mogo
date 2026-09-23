"""Tests for harness elastic config core (feature 019): layers / floor / profile."""

from __future__ import annotations

import pytest

from app.harness_config.floor import (
    MIN_AUDIT_FIELDS,
    FloorViolation,
    assert_floor_intact,
    audit_covers_floor,
    minimal_audit_record,
    r4_always_denied,
)
from app.harness_config.layer_switch import (
    CANONICAL_LAYERS,
    DROPPABLE_LAYERS,
    REQUIRED_LAYERS,
    is_thin,
    resolve_layers,
)
from app.harness_config.profile import HarnessProfile, ProfileResolver


# --- layer switch (US1) ------------------------------------------------------

def test_thick_mode_enables_all_six_layers() -> None:
    assert resolve_layers("thick") == list(CANONICAL_LAYERS)


def test_thin_mode_drops_only_approval_and_quota() -> None:
    layers = resolve_layers("thin")
    assert "approval" not in layers
    assert "quota" not in layers
    for required in REQUIRED_LAYERS:
        assert required in layers


def test_droppable_is_exactly_approval_and_quota() -> None:
    assert DROPPABLE_LAYERS == {"approval", "quota"}


def test_explicit_enabled_list_still_ordered_canonically() -> None:
    layers = resolve_layers("thick", enabled=["audit", "rbac", "identity"])
    assert layers == ["identity", "rbac", "audit"]


def test_is_thin() -> None:
    assert is_thin("thin")
    assert not is_thin("thick")


# --- floor guard (US1/US3) ---------------------------------------------------

def test_floor_rejects_dropping_required_layer() -> None:
    with pytest.raises(FloorViolation):
        assert_floor_intact(enabled_layers=["identity", "approval", "quota", "audit"])


def test_floor_rejects_disabling_audit() -> None:
    with pytest.raises(FloorViolation):
        assert_floor_intact(enabled_layers=list(CANONICAL_LAYERS), audit_enabled=False)


def test_floor_allows_thin_mode() -> None:
    assert_floor_intact(enabled_layers=resolve_layers("thin"))


def test_r4_denied_in_every_mode() -> None:
    assert r4_always_denied("thick")
    assert r4_always_denied("thin")


def test_minimal_audit_record_has_four_fields() -> None:
    record = minimal_audit_record(subject="u1", tool="crm", result="denied", timestamp="2026-07-08T00:00:00Z")
    assert set(record) == set(MIN_AUDIT_FIELDS)


def test_audit_covers_floor_detects_missing_fields() -> None:
    assert audit_covers_floor(minimal_audit_record(subject="u1", tool="crm", result="ok", timestamp="t"))
    assert not audit_covers_floor({"subject": "u1", "tool": "crm"})


# --- profile resolution (US2) ------------------------------------------------

def test_default_is_thick() -> None:
    resolver = ProfileResolver()
    profile = resolver.resolve(scene="", tenant="", tool="")
    assert profile.mode == "thick"
    assert profile.resolved_layers() == list(CANONICAL_LAYERS)


def test_scene_beats_tenant_and_tool() -> None:
    resolver = ProfileResolver()
    resolver.add(HarnessProfile(scope="tenant", key="t1", mode="thin"))
    resolver.add(HarnessProfile(scope="scene", key="quick-ask", mode="thick"))
    resolver.add(HarnessProfile(scope="tool", key="crm", mode="thin"))

    profile = resolver.resolve(scene="quick-ask", tenant="t1", tool="crm")
    assert profile.scope == "scene"
    assert profile.mode == "thick"


def test_tenant_beats_tool_when_no_scene() -> None:
    resolver = ProfileResolver()
    resolver.add(HarnessProfile(scope="tenant", key="t1", mode="thin"))
    resolver.add(HarnessProfile(scope="tool", key="crm", mode="thick"))

    profile = resolver.resolve(scene="", tenant="t1", tool="crm")
    assert profile.scope == "tenant"
    assert profile.mode == "thin"


def test_tool_profile_applies_when_no_scene_or_tenant() -> None:
    resolver = ProfileResolver()
    resolver.add(HarnessProfile(scope="tool", key="crm", mode="thin"))
    assert resolver.resolve(scene="x", tenant="y", tool="crm").mode == "thin"


def test_effective_layers_switch_per_call() -> None:
    resolver = ProfileResolver()
    resolver.add(HarnessProfile(scope="tool", key="crm", mode="thin"))

    thin = resolver.effective_layers(scene="", tenant="", tool="crm")
    thick = resolver.effective_layers(scene="", tenant="", tool="other")
    assert "approval" not in thin
    assert "approval" in thick


def test_profile_validation_rejects_illegal_thinning() -> None:
    with pytest.raises(FloorViolation):
        HarnessProfile(
            scope="tenant",
            key="t1",
            mode="thin",
            enabled_layers=["approval", "quota"],  # drops required layers
        ).validate()


def test_thin_audit_granularity_is_minimal() -> None:
    assert HarnessProfile(mode="thin").resolved_audit_granularity() == "minimal"
    assert HarnessProfile(mode="thick").resolved_audit_granularity() == "full"


# --- gate adapter (T014) -----------------------------------------------------

def test_plan_thick_uses_all_layers_and_gatekeeper() -> None:
    from app.harness_config.gate_adapter import GATEKEEPER_READY, build_gate_plan

    plan = build_gate_plan(mode="thick", backend=GATEKEEPER_READY)
    assert plan.layers == list(CANONICAL_LAYERS)
    assert plan.skipped_layers == []
    assert plan.backend == GATEKEEPER_READY


def test_plan_thin_skips_approval_and_quota_keeps_audit() -> None:
    from app.harness_config.gate_adapter import build_gate_plan

    plan = build_gate_plan(mode="thin")
    assert set(plan.skipped_layers) == {"approval", "quota"}
    assert plan.audit_enabled() is True
    assert plan.audit_granularity == "minimal"


def test_plan_rejects_floor_breach() -> None:
    from app.harness_config.gate_adapter import build_gate_plan
    from app.harness_config.floor import FloorViolation
    import pytest as _pytest

    with _pytest.raises(FloorViolation):
        build_gate_plan(mode="thin", enabled_layers=["approval", "quota"])


def test_plan_rejects_unknown_backend() -> None:
    from app.harness_config.gate_adapter import GateAdapterError, build_gate_plan
    import pytest as _pytest

    with _pytest.raises(GateAdapterError):
        build_gate_plan(mode="thick", backend="magic")


def test_backend_transition_until_gatekeeper_ready() -> None:
    from app.harness_config.gate_adapter import (
        GATEKEEPER_READY,
        TRANSITION,
        backend_for,
    )

    assert backend_for(False) == TRANSITION
    assert backend_for(True) == GATEKEEPER_READY


def test_describe_plan_is_serializable() -> None:
    from app.harness_config.gate_adapter import build_gate_plan, describe_plan

    payload = describe_plan(build_gate_plan(mode="thin"))
    assert payload["mode"] == "thin"
    assert payload["auditEnabled"] is True
    assert "approval" in payload["skippedLayers"]


def test_required_layers_never_skipped() -> None:
    from app.harness_config.gate_adapter import build_gate_plan

    plan = build_gate_plan(mode="thin")
    for required in REQUIRED_LAYERS:
        assert required not in plan.skipped_layers
