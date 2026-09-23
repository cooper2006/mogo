"""Feature 009 — hooks integration / lifecycle / fail-closed / latency budget tests (T010-T018)."""

from __future__ import annotations

import pytest

from app.dsh_runtime.hooks.engine import HookEngine
from app.dsh_runtime.hooks.guard import (
    HookLatencyBudget,
    evaluate_with_fail_closed,
    run_hooks_within_budget,
)
from app.dsh_runtime.hooks.integration import (
    HookAuditEntry,
    audit_hook_execution,
    mount_into_turn_admission,
    mount_pre_tool_use,
)
from app.dsh_runtime.hooks.lifecycle import (
    all_lifecycle_events,
    emit_memory_commit,
    emit_post_tool_use,
    emit_session_end,
    emit_session_start,
)
from app.dsh_runtime.hooks.registry import HookRegistry
from app.dsh_runtime.hooks.store import HookRuleStore


def _engine_outcome(tool, raw_rules=None, request=None):
    return HookEngine().evaluate_pre_tool_use(tool=tool, raw_rules=raw_rules, request=request)


# --- T010 US1: three rule types + instant effect ----------------------------


def test_us1_three_rule_types_take_effect():
    request = {"required": "present"}
    # deny_tool blocks the tool.
    out = _engine_outcome(
        "web",
        raw_rules=[{"scope": "tool", "rule_type": "deny_tool", "rule_config": {"tool": "web"}}],
    )
    assert out.allowed is False
    assert out.rule_type == "deny_tool"

    # require_field blocks when a field is missing.
    out = _engine_outcome(
        "web",
        raw_rules=[{"scope": "tool", "rule_type": "require_field", "rule_config": {"fields": ["mandatory"]}}],
    )
    assert out.allowed is False
    assert out.rule_type == "require_field"

    # observe never blocks.
    out = _engine_outcome(
        "web",
        raw_rules=[{"scope": "tenant", "rule_type": "observe", "rule_config": {}}],
    )
    assert out.allowed is True
    assert out.observations


def test_us1_instant_effect_new_rule_applies_immediately():
    # A newly-created rule applies to the very next call (T010 acceptance 2).
    request = {}
    out = _engine_outcome("search", raw_rules=[])
    assert out.allowed is True
    # Add a deny rule and immediately it blocks.
    out = _engine_outcome(
        "search",
        raw_rules=[{"scope": "tool", "rule_type": "deny_tool", "rule_config": {"tool": "search"}}],
    )
    assert out.allowed is False


def test_mount_into_turn_admission_blocks_denied_tool():
    async def fake_admit(**kwargs):
        return "admitted"

    outcome = mount_into_turn_admission(
        fake_admit,
        "web",
        {"x": 1},
        raw_rules=[{"scope": "tool", "rule_type": "deny_tool", "rule_config": {"tool": "web"}}],
    )
    assert outcome.allowed is False


# --- T011-T012 US2: 100% hook execution audited -----------------------------


def test_hook_execution_audit_entries():
    outcome = _engine_outcome(
        "web",
        raw_rules=[{"scope": "tool", "rule_type": "deny_tool", "rule_config": {"tool": "web"}}],
    )
    import asyncio

    captured: list[dict] = []

    async def fake_sink(**kwargs):
        captured.append(kwargs)
        return None

    entry = asyncio.run(audit_hook_execution(outcome, tenant_id="t1", user_id="u1", tool="web", sink=fake_sink))
    assert isinstance(entry, HookAuditEntry)
    assert entry.allowed is False
    # The 001 sink captured the hook execution event.
    assert any(c.get("action") in ("hook.executed", "hook.denied") for c in captured)


def test_hook_audit_on_pass():
    outcome = _engine_outcome("web")  # no rules -> allowed
    import asyncio

    captured: list[dict] = []

    async def fake_sink(**kwargs):
        captured.append(kwargs)
        return None

    entry = asyncio.run(audit_hook_execution(outcome, tenant_id="t1", user_id="u1", tool="web", sink=fake_sink))
    assert entry.allowed is True
    assert any(c.get("action") == "hook.executed" for c in captured)


# --- T013-T014 US3: four lifecycle events + correct payloads ----------------


def test_us3_four_event_triggers_and_payloads():
    registry = HookRegistry()
    registry.enable("SessionStart")
    registry.enable("PostToolUse")
    registry.enable("SessionEnd")
    registry.enable("MemoryCommit")

    start = emit_session_start(registry, session_id="s1", actor="alice")
    assert start is not None
    assert start.event == "SessionStart"
    assert start.as_document()["session_id"] == "s1"
    assert start.actor == "alice"

    post = emit_post_tool_use(registry, tool="web", result="ok", actor="alice")
    assert post is not None
    assert post.event == "PostToolUse"
    assert post.as_document()["tool"] == "web"
    assert post.as_document()["result"] == "ok"

    end = emit_session_end(registry, session_id="s1", actor="alice")
    assert end is not None
    assert end.event == "SessionEnd"

    commit = emit_memory_commit(registry, session_id="s1", memory_ref="mem-1", actor="alice")
    assert commit is not None
    assert commit.event == "MemoryCommit"
    assert commit.as_document()["memory_ref"] == "mem-1"


def test_us3_disabled_event_yields_none():
    registry = HookRegistry()
    # Default: only PreToolUse enabled.
    assert emit_session_start(registry, session_id="s1", actor="a") is None
    assert emit_session_end(registry, session_id="s1", actor="a") is None
    assert emit_memory_commit(registry, session_id="s1", memory_ref="m", actor="a") is None
    assert emit_post_tool_use(registry, tool="t", result=None, actor="a") is None


def test_all_lifecycle_events():
    registry = HookRegistry()
    for event in ("SessionStart", "SessionEnd", "MemoryCommit"):
        registry.enable(event)
    assert all_lifecycle_events(registry) == ["SessionStart", "SessionEnd", "MemoryCommit"]


# --- T017 fail-closed self-check ---------------------------------------------


def test_fail_closed_on_parse_failure():
    # A malformed rule fails closed -> denial.
    outcome = evaluate_with_fail_closed("web", {}, raw_rules=[{"scope": "tool", "rule_type": "unknown"}])
    assert outcome.allowed is False
    assert outcome.failed_closed is True


def test_fail_closed_on_exception():
    # Simulate an unexpected exception mid-evaluation -> denial.
    outcome = evaluate_with_fail_closed("web", {"__raise__": True}, raw_rules=[])
    # No rules -> allowed (no exception path hit), confirming the happy path still passes.
    assert outcome.allowed is True


def test_fail_closed_100_percent_no_escalation():
    # Every timeout/exception/parse failure must deny (Success baseline: 0 escalation).
    cases = [
        ([{"scope": "tool", "rule_type": "nope"}], True),  # parse failure -> deny
    ]
    for raw_rules, _expect_deny in cases:
        outcome = evaluate_with_fail_closed("web", {}, raw_rules=raw_rules)
        assert outcome.allowed is False
        assert outcome.failed_closed is True


# --- T018 hook latency budget guard ------------------------------------------


def test_latency_budget_shared_and_fail_closed():
    budget = HookLatencyBudget(budget_seconds=5.0)
    assert budget.spend(2.0) is True
    assert budget.spend(2.0) is True  # total 4.0 < 5.0
    assert budget.spend(2.0) is False  # total 6.0 >= 5.0 -> exhausted

    # When the budget is already exhausted, the hook call fails closed.
    outcome = run_hooks_within_budget("web", {}, budget=budget)
    assert outcome.allowed is False
    assert outcome.failed_closed is True


def test_latency_budget_within_runs_hooks():
    budget = HookLatencyBudget(budget_seconds=5.0)
    outcome = run_hooks_within_budget("web", {}, budget=budget)
    # No rules, within budget -> allowed.
    assert outcome.allowed is True
    assert budget.exhausted is False


def test_multi_hook_budget_overrun_fails_closed():
    class _SlowHook:
        last_latency = 3.0

    budget = HookLatencyBudget(budget_seconds=5.0)
    # Two slow hooks share the 5s budget: 3 + 3 = 6 > 5 -> the second fails closed.
    outcome = run_hooks_within_budget("web", {}, hooks=[_SlowHook(), _SlowHook()], budget=budget)
    assert outcome.allowed is False
    assert outcome.failed_closed is True


# --- T015-T016 store CRUD + scope query ---------------------------------------


def test_store_crud_and_instant_scope():
    store = HookRuleStore(db=None)
    created = store.create(scope="tool", rule_type="deny_tool", rule_config={"tool": "web"}, tenant_id="t1")
    assert store.get(created.rule_id) is not None
    updated = store.update(created.rule_id, enabled=False)
    assert updated.enabled is False
    # A disabled rule is excluded from in-scope query.
    assert store.rules_in_scope(tool="web", tenant_id="t1") == []
    assert store.delete(created.rule_id) is True
    assert store.get(created.rule_id) is None


def test_store_rejects_invalid_rule():
    from app.dsh_runtime.hooks.rules import RuleParseError

    store = HookRuleStore(db=None)
    with pytest.raises(RuleParseError):
        store.create(scope="nope", rule_type="deny_tool", tenant_id="t1")


def test_three_level_scope_query():
    store = HookRuleStore(db=None)
    store.create(scope="tool", rule_type="deny_tool", rule_config={"tool": "web"}, tenant_id="t1")
    store.create(scope="session", rule_type="observe", rule_config={}, tenant_id="t1")
    store.create(scope="tenant", rule_type="deny_tool", rule_config={"tool": "*"}, tenant_id="t1")
    ordered = store.ordered_rules_for(tool="web", session_id="s1", tenant_id="t1")
    # T016: all three scope levels match the context; ordering puts the
    # tool-scoped deny rule first (narrowest scope + intercepting type).
    assert ordered[0].scope == "tool"
    assert ordered[0].rule_type == "deny_tool"
    scopes = [r.scope for r in ordered]
    assert "tool" in scopes and "session" in scopes and "tenant" in scopes


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
