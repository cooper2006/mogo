"""009 production wiring: PreToolUse gate mounted into turn admission.

``run_pre_tool_use`` is the production entry point: it loads declarative rules
from the ``hook_rules`` store at call time (FR-4 immediate effect), evaluates
them fail-closed, and audits every execution through the 001 governance sink
(US2 / T011). ``admit_skill_selection`` calls it before the skill policy when
the caller declares a tool context, so a denied tool never reaches the policy.
"""

from __future__ import annotations

import asyncio

import pytest

from app.dsh_runtime import turn_admission
from app.dsh_runtime.turn_admission import PreToolUseGate, run_pre_tool_use


def _patch_store(monkeypatch, rules_in_scope: list, audits: list | None = None) -> None:
    """Point the hook store and audit sink at in-memory fakes."""
    from app.dsh_runtime.hooks import integration as integration_module
    from app.dsh_runtime.hooks import store as store_module

    class _FakeStore:
        def __init__(self, db=None) -> None:
            self._rules = list(rules_in_scope)

        async def rules_in_scope(self, **kwargs) -> list:
            return list(self._rules)

    async def _fake_audit(outcome, **kwargs):
        if audits is not None:
            audits.append(outcome)
        return None

    monkeypatch.setattr(store_module, "HookRuleStore", _FakeStore)
    monkeypatch.setattr(
        integration_module,
        "audit_hook_execution",
        _fake_audit,
    )


def test_run_pre_tool_use_no_rules_is_noop(monkeypatch) -> None:
    _patch_store(monkeypatch, rules_in_scope=[])
    gate = asyncio.run(run_pre_tool_use(tenant_id="t1", user_id="u1", tool="web_search"))
    assert gate is None


def test_run_pre_tool_use_deny_tool_rule_denies(monkeypatch) -> None:
    from app.dsh_runtime.hooks.store import HookRuleDocument

    document = HookRuleDocument(
        rule_id="hr-deny",
        scope="tenant",
        rule_type="deny_tool",
        rule_config={"tool": "web_search"},
        enabled=True,
        tenant_id="t1",
    )
    _patch_store(monkeypatch, rules_in_scope=[document])
    gate = asyncio.run(run_pre_tool_use(tenant_id="t1", user_id="u1", tool="web_search"))
    assert isinstance(gate, PreToolUseGate)
    assert not gate.allowed
    assert gate.denied_rule_type == "deny_tool"


def test_run_pre_tool_use_require_field_missing_denies(monkeypatch) -> None:
    from app.dsh_runtime.hooks.store import HookRuleDocument

    document = HookRuleDocument(
        rule_id="hr-req",
        scope="tenant",
        rule_type="require_field",
        rule_config={"tool": "web_search", "fields": ["query"]},
        enabled=True,
        tenant_id="t1",
    )
    _patch_store(monkeypatch, rules_in_scope=[document])
    gate = asyncio.run(
        run_pre_tool_use(
            tenant_id="t1",
            user_id="u1",
            tool="web_search",
            request={},  # missing the required field
        )
    )
    assert gate is not None and not gate.allowed
    assert gate.denied_rule_type == "require_field"


def test_run_pre_tool_use_require_field_satisfied_passes(monkeypatch) -> None:
    from app.dsh_runtime.hooks.store import HookRuleDocument

    document = HookRuleDocument(
        rule_id="hr-req",
        scope="tenant",
        rule_type="require_field",
        rule_config={"tool": "web_search", "fields": ["query"]},
        enabled=True,
        tenant_id="t1",
    )
    _patch_store(monkeypatch, rules_in_scope=[document])
    gate = asyncio.run(
        run_pre_tool_use(
            tenant_id="t1",
            user_id="u1",
            tool="web_search",
            request={"query": "hello"},
        )
    )
    assert gate is None  # allowed → no gate returned


def test_run_pre_tool_use_audits_every_execution(monkeypatch) -> None:
    """US2 / T011: pass and deny both reach the 001 audit sink."""
    from app.dsh_runtime.hooks.store import HookRuleDocument

    deny_rule = HookRuleDocument(
        rule_id="hr-deny",
        scope="tenant",
        rule_type="deny_tool",
        rule_config={"tool": "browser"},
        enabled=True,
        tenant_id="t1",
    )
    pass_rule = HookRuleDocument(
        rule_id="hr-obs",
        scope="tenant",
        rule_type="observe",
        rule_config={"tool": "web_search"},
        enabled=True,
        tenant_id="t1",
    )
    audits: list = []
    _patch_store(monkeypatch, rules_in_scope=[deny_rule, pass_rule], audits=audits)

    denied = asyncio.run(run_pre_tool_use(tenant_id="t1", user_id="u1", tool="browser"))
    allowed = asyncio.run(run_pre_tool_use(tenant_id="t1", user_id="u1", tool="web_search"))
    assert denied is not None and not denied.allowed
    assert allowed is None
    assert [entry.allowed for entry in audits] == [False, True]


def test_admit_skill_selection_runs_hook_gate_first(monkeypatch) -> None:
    """The gate runs before skill policy; a deny raises PermissionError without
    touching the position policy resolver."""
    from app.dsh_runtime.hooks.store import HookRuleDocument

    document = HookRuleDocument(
        rule_id="hr-deny",
        scope="tenant",
        rule_type="deny_tool",
        rule_config={"tool": "browser"},
        enabled=True,
        tenant_id="t1",
    )
    _patch_store(monkeypatch, rules_in_scope=[document])

    # Count whether the skill policy resolver was ever reached.
    resolver_calls: list[bool] = []

    class _SpyResolver:
        async def resolve(self, tenant_id, user_id):
            resolver_calls.append(True)
            raise AssertionError("policy resolver must not run when hook denies")

        def allows_skill(self, skill_id: str) -> bool:  # pragma: no cover
            return True

    monkeypatch.setattr(
        turn_admission.MongoEmployeePolicyResolver,
        "resolve",
        lambda self, tenant_id, user_id: _SpyResolver().resolve(tenant_id, user_id),
    )

    with pytest.raises(PermissionError, match="钩子规则拒绝工具调用"):
        asyncio.run(
            turn_admission.admit_skill_selection(
                tenant_id="t1",
                user_id="u1",
                selected_skill_id="sk-1",
                tool="browser",
            )
        )
    assert resolver_calls == []  # policy resolver never reached — gate first


def test_admit_skill_selection_without_tool_is_unchanged(monkeypatch) -> None:
    """No ``tool`` argument → original admission path, no hook store access."""

    class _Policy:
        def allows_skill(self, skill_id: str) -> bool:
            return True

    async def _fake_resolve(self, tenant_id, user_id):
        return _Policy()

    async def _fake_require_skill(catalog, **kwargs):
        return "skill", {"_id": "sk-1"}

    _patch_store(monkeypatch, rules_in_scope=[])
    monkeypatch.setattr(
        turn_admission.MongoEmployeePolicyResolver, "resolve", _fake_resolve
    )
    monkeypatch.setattr(turn_admission, "require_selected_skill", _fake_require_skill)
    monkeypatch.setattr(
        turn_admission, "record_position_policy_event", _noop_record
    )

    async def _run():
        return await turn_admission.admit_skill_selection(
            tenant_id="t1",
            user_id="u1",
            selected_skill_id="sk-1",
        )

    selection = asyncio.run(_run())
    assert selection.selected_skill_id == "sk-1"


async def _noop_record(*args, **kwargs) -> None:
    return None
