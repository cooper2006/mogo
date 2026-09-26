"""001 US1 runtime-side wiring: gate plan enforced on the tool-call path.

``run_gate_plan`` mounts the 019 ``build_gate_plan`` (the six-layer enablement
plan) onto the tool-call admission path, fail-closed when the audit layer is
skipped (floor breach) and auditing every resolution through the 001 sink.
"""

from __future__ import annotations

import asyncio

import pytest

from app.dsh_runtime import turn_admission
from app.dsh_runtime.turn_admission import GatePlan, run_gate_plan


def _patch(monkeypatch, events: list) -> None:
    from app.dsh_runtime.hooks import integration as integration_module
    from app.dsh_runtime.hooks import store as store_module

    class _FakeStore:
        def __init__(self, db=None) -> None:
            pass

        async def rules_in_scope(self, **kwargs):
            return []

    async def _fake_audit(outcome, **kwargs):
        return None

    async def _capture(tenant_id, user_id, action, target, details=None):
        events.append((action, target, dict(details or {})))

    monkeypatch.setattr(store_module, "HookRuleStore", _FakeStore)
    monkeypatch.setattr(integration_module, "audit_hook_execution", _fake_audit)
    monkeypatch.setattr(turn_admission, "record_position_policy_event", _capture)


def test_run_gate_plan_thick_backend(monkeypatch) -> None:
    events: list = []
    _patch(monkeypatch, events)
    plan = asyncio.run(
        run_gate_plan(
            tenant_id="t1",
            user_id="u1",
            tool="browser",
            request={"harness_mode": "thick", "gatekeeper_ready": True},
        )
    )
    assert isinstance(plan, GatePlan)
    assert plan.backend == "gatekeeper"
    assert "audit" in plan.layers
    assert plan.audit_enabled is True
    # The resolution is audited through the 001 sink.
    assert ("gate.plan.resolved", "browser") in [(a, t) for (a, t, _d) in events]


def test_run_gate_plan_transition_backend_when_gatekeeper_not_ready(monkeypatch) -> None:
    events: list = []
    _patch(monkeypatch, events)
    plan = asyncio.run(
        run_gate_plan(
            tenant_id="t1",
            user_id="u1",
            tool="browser",
            request={"harness_mode": "thick", "gatekeeper_ready": False},
        )
    )
    assert plan.backend == "transition"


def test_run_gate_plan_thin_mode_drops_approval_and_quota_keeps_audit(monkeypatch) -> None:
    events: list = []
    _patch(monkeypatch, events)
    plan = asyncio.run(
        run_gate_plan(
            tenant_id="t1",
            user_id="u1",
            tool="browser",
            request={"harness_mode": "thin"},
        )
    )
    assert "audit" in plan.layers  # floor: audit never dropped
    assert "approval" in plan.skipped
    assert "quota" in plan.skipped
    assert plan.audit_enabled is True


def test_run_gate_plan_floor_breach_fails_closed(monkeypatch) -> None:
    """An explicit enabled list that drops audit must be rejected (FR-8 floor)."""
    events: list = []
    _patch(monkeypatch, events)
    # Force an audit-free layer set via the gate_adapter to confirm the floor guard.
    from app.harness_config import gate_adapter

    original_build = gate_adapter.build_gate_plan

    def _no_audit_build(**kwargs):
        plan = original_build(**kwargs)
        return gate_adapter.GatePlan(
            mode=plan.mode,
            layers=[name for name in plan.layers if name != "audit"],
            backend=plan.backend,
            audit_granularity=plan.audit_granularity,
            skipped_layers=list(plan.skipped_layers) + ["audit"],
            timeout_seconds=plan.timeout_seconds,
        )

    monkeypatch.setattr(gate_adapter, "build_gate_plan", _no_audit_build)
    with pytest.raises(PermissionError, match="审计层不可跳过"):
        asyncio.run(
            run_gate_plan(tenant_id="t1", user_id="u1", tool="browser", request={"harness_mode": "thick"})
        )


def test_admit_skill_selection_enforces_gate_plan_after_hook(monkeypatch) -> None:
    """The tool path runs the 001 gate plan after the PreToolUse hook passes."""
    from app.dsh_runtime.hooks import store as store_module
    from app.dsh_runtime.hooks import integration as integration_module

    events: list = []

    class _FakeStore:
        def __init__(self, db=None) -> None:
            pass

        async def rules_in_scope(self, **kwargs):
            return []

    async def _fake_audit(outcome, **kwargs):
        return None

    async def _capture(tenant_id, user_id, action, target, details=None):
        events.append((action, target, dict(details or {})))

    monkeypatch.setattr(store_module, "HookRuleStore", _FakeStore)
    monkeypatch.setattr(integration_module, "audit_hook_execution", _fake_audit)
    monkeypatch.setattr(turn_admission, "record_position_policy_event", _capture)

    class _Policy:
        def allows_skill(self, skill_id: str) -> bool:
            return True

    async def _fake_resolve(self, tenant_id, user_id):
        return _Policy()

    async def _fake_require_skill(catalog, **kwargs):
        return "skill", {"_id": "sk-1"}

    monkeypatch.setattr(turn_admission.MongoEmployeePolicyResolver, "resolve", _fake_resolve)
    monkeypatch.setattr(turn_admission, "require_selected_skill", _fake_require_skill)

    selection = asyncio.run(
        turn_admission.admit_skill_selection(
            tenant_id="t1",
            user_id="u1",
            selected_skill_id="sk-1",
            tool="browser",
            request={"harness_mode": "thick", "gatekeeper_ready": True},
        )
    )
    assert selection.selected_skill_id == "sk-1"
    # The 001 gate plan resolution was audited on the tool path.
    assert ("gate.plan.resolved", "browser") in [(a, t) for (a, t, _d) in events]
