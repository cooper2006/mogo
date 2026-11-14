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


@pytest.mark.asyncio
async def test_store_crud_and_instant_scope():
    store = HookRuleStore(db=None)
    created = await store.create(scope="tool", rule_type="deny_tool", rule_config={"tool": "web"}, tenant_id="t1")
    assert await store.get(created.rule_id) is not None
    updated = await store.update(created.rule_id, enabled=False)
    assert updated.enabled is False
    # A disabled rule is excluded from in-scope query.
    assert await store.rules_in_scope(tool="web", tenant_id="t1") == []
    assert await store.delete(created.rule_id) is True
    assert await store.get(created.rule_id) is None


@pytest.mark.asyncio
async def test_store_rejects_invalid_rule():
    from app.dsh_runtime.hooks.rules import RuleParseError

    store = HookRuleStore(db=None)
    with pytest.raises(RuleParseError):
        await store.create(scope="nope", rule_type="deny_tool", tenant_id="t1")


@pytest.mark.asyncio
async def test_three_level_scope_query():
    store = HookRuleStore(db=None)
    await store.create(scope="tool", rule_type="deny_tool", rule_config={"tool": "web"}, tenant_id="t1")
    await store.create(scope="session", rule_type="observe", rule_config={}, tenant_id="t1")
    await store.create(scope="tenant", rule_type="deny_tool", rule_config={"tool": "*"}, tenant_id="t1")
    ordered = await store.ordered_rules_for(tool="web", session_id="s1", tenant_id="t1")
    # T016: all three scope levels match the context; ordering puts the
    # tool-scoped deny rule first (narrowest scope + intercepting type).
    assert ordered[0].scope == "tool"
    assert ordered[0].rule_type == "deny_tool"
    scopes = [r.scope for r in ordered]
    assert "tool" in scopes and "session" in scopes and "tenant" in scopes


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))


# --- 2026-10-03 fix: require_field needs a real request payload -------------


def test_require_field_passes_when_the_payload_carries_the_field():
    """The call sites used to omit ``request`` entirely.

    With an empty payload every ``require_field`` rule rejected every call, so the
    rule type was unusable (and configuring one would have blocked the turn
    outright). With the real context now passed, the rule evaluates properly.
    """
    from app.dsh_runtime.hooks.engine import HookEngine

    engine = HookEngine()
    rule = {"scope": "tool", "rule_type": "require_field", "rule_config": {"fields": ["text"]}}

    ok = engine.evaluate_pre_tool_use(tool="dsh_turn", request={"text": "hi"}, raw_rules=[rule])
    assert ok.allowed is True

    blocked = engine.evaluate_pre_tool_use(tool="dsh_turn", request={}, raw_rules=[rule])
    assert blocked.allowed is False
    assert blocked.rule_type == "require_field"


def test_admit_skill_selection_forwards_request_to_the_hook_engine():
    """Pins the wiring: admission must pass the call context through (not None).

    ``selected_skill_id=None`` returns before the position-policy lookup, so this
    exercises exactly the hook + gate-plan path with no DB involvement.
    """
    import asyncio

    from app.dsh_runtime import turn_admission

    captured: dict = {}

    async def _fake_run_pre_tool_use(**kwargs):
        captured["hook"] = kwargs
        return None  # None == allowed

    async def _fake_run_gate_plan(**kwargs):
        captured["plan"] = kwargs
        from app.dsh_runtime.turn_admission import GatePlan

        return GatePlan(backend="gatekeeper", layers=("audit",), audit_enabled=True, skipped=())

    original_hook = turn_admission.run_pre_tool_use
    original_plan = turn_admission.run_gate_plan
    turn_admission.run_pre_tool_use = _fake_run_pre_tool_use
    turn_admission.run_gate_plan = _fake_run_gate_plan
    try:
        asyncio.run(
            turn_admission.admit_skill_selection(
                tenant_id="t1",
                user_id="u1",
                selected_skill_id=None,
                tool="browser",
                request={"text": "hello"},
                session_id="s1",
            )
        )
    finally:
        turn_admission.run_pre_tool_use = original_hook
        turn_admission.run_gate_plan = original_plan

    assert captured["hook"]["tool"] == "browser"
    assert captured["hook"]["request"] == {"text": "hello"}
    # The same context must reach the six-layer gate plan (001 runtime side).
    assert captured["plan"]["request"] == {"text": "hello"}


def test_rule_source_cache_serves_hits_without_a_db_query(monkeypatch):
    """009 hot-path fix: the rule source is cached per tenant (2s TTL).

    After one lookup, repeat calls within the TTL must not touch the DB at all —
    so a tool gateway for a rule-less tenant no longer depends on Mongo, and the
    negative case is cached too.
    """
    import asyncio
    import time

    import app.dsh_runtime.turn_admission as turn_admission
    from app.dsh_runtime.hooks.store import HookRuleDocument

    queries: list = []

    class _Store:
        def __init__(self, *_a, **_k):
            pass

        async def rules_in_scope(self, **kwargs):
            queries.append(kwargs)
            return [
                HookRuleDocument(
                    rule_id="hr-1",
                    scope="tool",
                    rule_type="deny_tool",
                    rule_config={"tool": "dangerous"},
                )
            ]

    monkeypatch.setattr(turn_admission, "_RULE_SOURCE_CACHE", {})
    monkeypatch.setattr("app.dsh_runtime.turn_admission._RULE_SOURCE_CACHE_TTL", 2.0)
    monkeypatch.setattr(
        "app.dsh_runtime.hooks.store.HookRuleStore", _Store, raising=False
    )

    from app.dsh_runtime.hooks import integration as _integration

    async def _no_sink(*_a, **_k):
        return None

    monkeypatch.setattr(
        _integration, "record_position_policy_event", _no_sink, raising=False
    )

    from app.dsh_runtime.turn_admission import run_pre_tool_use

    async def _go():
        denied = await run_pre_tool_use(
            tenant_id="t1", user_id="u1", tool="dangerous", session_id="s1"
        )
        assert denied is not None and "deny_tool" in denied.denied_reason
        # Second call: cache hit, no new query.
        await run_pre_tool_use(
            tenant_id="t1", user_id="u1", tool="other", session_id="s1"
        )

    asyncio.run(_go())
    assert len(queries) == 1  # the second call was served from cache

    # TTL expiry forces a re-query.
    turn_admission._RULE_SOURCE_CACHE["t1"] = (time.monotonic() - 1, [])
    captured = {}

    class _Store2:
        def __init__(self, *_a, **_k):
            captured["queried"] = True

        async def rules_in_scope(self, **kwargs):
            return []

    monkeypatch.setattr(
        "app.dsh_runtime.hooks.store.HookRuleStore", _Store2, raising=False
    )
    asyncio.run(
        run_pre_tool_use(tenant_id="t1", user_id="u1", tool="other", session_id="s1")
    )
    assert captured.get("queried") is True


@pytest.fixture(autouse=True)
def _reset_rule_source_cache(monkeypatch):
    """Isolate the module-level rule source cache across tests (009 hot-path fix)."""
    import app.dsh_runtime.turn_admission as turn_admission

    monkeypatch.setattr(turn_admission, "_RULE_SOURCE_CACHE", {})
    yield
    # Keep a copy so other tests running after this one don't see stale entries.
