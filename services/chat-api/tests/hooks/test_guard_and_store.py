"""Tests for 009's fail-closed guard, latency budget, and rule store.

Coverage audit (2026-10-06) found ``hooks/guard.py``, ``hooks/store.py`` and
``hooks/integration.py`` at **0%** — they are the fail-closed enforcement path
(FR-11/FR-13) and the declarative-rule store (T015/T016), i.e. exactly the code
that must not regress silently.

No MongoDB required: ``HookRuleStore`` falls back to its in-memory path.
"""

from __future__ import annotations

import pytest

from app.dsh_runtime.hooks.guard import (
    DEFAULT_HOOK_BUDGET_SECONDS,
    HookLatencyBudget,
    evaluate_with_fail_closed,
    fail_closed_outcome,
    run_hooks_within_budget,
)
from app.dsh_runtime.hooks.store import HookRuleDocument, HookRuleStore


# --- guard: fail-closed (FR-11 / T017) ------------------------------------


def test_fail_closed_outcome_defaults_reason() -> None:
    outcome = fail_closed_outcome("")
    assert outcome.allowed is False
    assert outcome.failed_closed is True
    assert outcome.reason  # a default message is supplied


def test_evaluate_with_fail_closed_allows_without_rules() -> None:
    outcome = evaluate_with_fail_closed("bash", {"command": "ls"})
    assert outcome.failed_closed is False


def test_evaluate_with_fail_closed_denies_on_parse_error() -> None:
    """Malformed rules must deny, never allow (no privilege escalation)."""
    outcome = evaluate_with_fail_closed("bash", {"command": "ls"}, raw_rules=["not-a-rule"])
    assert outcome.allowed is False
    assert outcome.failed_closed is True


def test_evaluate_with_fail_closed_denies_deny_rule() -> None:
    outcome = evaluate_with_fail_closed(
        "bash",
        {"command": "rm -rf /"},
        raw_rules=[{"scope": "tool", "rule_type": "deny_tool", "rule_config": {"tools": ["bash"]}}],
    )
    assert outcome.allowed is False
    # A rule-based denial is not "failed_closed" — the distinction matters.
    assert outcome.failed_closed is False


# --- guard: latency budget (FR-13 / T018) ---------------------------------


def test_budget_defaults_to_five_seconds() -> None:
    assert DEFAULT_HOOK_BUDGET_SECONDS == 5.0
    assert HookLatencyBudget().budget_seconds == 5.0


def test_budget_spend_accumulates() -> None:
    budget = HookLatencyBudget(budget_seconds=5.0)
    assert budget.exhausted is False
    assert budget.spend(1.5) is True
    assert budget.elapsed_seconds == pytest.approx(1.5)
    assert budget.spend(2.0) is True
    assert budget.exhausted is False


def test_budget_spend_reports_exhaustion() -> None:
    budget = HookLatencyBudget(budget_seconds=1.0)
    assert budget.spend(0.9) is True
    assert budget.spend(0.2) is False, "exceeding the budget must report failure"
    assert budget.exhausted is True


def test_budget_spend_ignores_negative() -> None:
    """A hook reporting negative latency must not refund the budget."""
    budget = HookLatencyBudget(budget_seconds=5.0)
    budget.spend(-10.0)
    assert budget.elapsed_seconds == 0.0


def test_run_hooks_within_budget_denies_when_pre_exhausted() -> None:
    budget = HookLatencyBudget(budget_seconds=5.0)
    budget.elapsed_seconds = 99.0
    outcome = run_hooks_within_budget("bash", {"command": "ls"}, budget=budget)
    assert outcome.allowed is False
    assert outcome.failed_closed is True
    assert "预算" in outcome.reason


def test_run_hooks_within_budget_denies_on_overrun() -> None:
    class _SlowHook:
        last_latency = 10.0

    outcome = run_hooks_within_budget(
        "bash",
        {"command": "ls"},
        hooks=[_SlowHook()],
        budget=HookLatencyBudget(budget_seconds=5.0),
    )
    assert outcome.allowed is False
    assert outcome.failed_closed is True
    assert "FR-13" in outcome.reason


def test_run_hooks_within_budget_allows_when_fast() -> None:
    class _FastHook:
        last_latency = 0.1

    outcome = run_hooks_within_budget(
        "bash",
        {"command": "ls"},
        hooks=[_FastHook()],
        budget=HookLatencyBudget(budget_seconds=5.0),
    )
    assert outcome.failed_closed is False


def test_run_hooks_within_budget_denies_on_bad_rules() -> None:
    outcome = run_hooks_within_budget(
        "bash", {"command": "ls"}, raw_rules=["garbage"]
    )
    assert outcome.allowed is False
    assert outcome.failed_closed is True


# --- store: declarative rule CRUD (T015) -----------------------------------


def test_document_roundtrip() -> None:
    doc = HookRuleDocument(
        rule_id="hr-1",
        scope="tool",
        rule_type="deny",
        rule_config={"tool": "bash"},
        tenant_id="t1",
    )
    as_doc = doc.as_document()
    assert as_doc["rule_id"] == "hr-1"
    assert as_doc["enabled"] is True
    # as_document must copy the config, not alias it.
    as_doc["rule_config"]["tool"] = "mutated"
    assert doc.rule_config["tool"] == "bash"

    rule = doc.to_hook_rule()
    assert rule.scope == "tool"
    assert rule.rule_type == "deny"
    assert rule.enabled is True


@pytest.mark.asyncio
async def test_store_create_get_update_delete() -> None:
    store = HookRuleStore()
    created = await store.create(scope="tenant", rule_type="observe", rule_config={"a": 1}, tenant_id="t1")
    rule_id = created.rule_id
    assert rule_id.startswith("hr-")

    fetched = await store.get(rule_id)
    assert fetched is not None
    assert fetched.scope == "tenant"

    updated = await store.update(rule_id, rule_config={"a": 2})
    assert updated.rule_config["a"] == 2

    assert await store.delete(rule_id) is True
    assert await store.get(rule_id) is None
    assert await store.delete(rule_id) is False


@pytest.mark.asyncio
async def test_store_get_missing_returns_none() -> None:
    store = HookRuleStore()
    assert await store.get("hr-nope") is None


@pytest.mark.asyncio
async def test_store_update_missing_returns_none() -> None:
    store = HookRuleStore()
    assert await store.update("hr-nope", rule_config={"x": 1}) is None


@pytest.mark.asyncio
async def test_store_list_and_scope_query() -> None:
    """Narrowest matching scope must win (FR-9)."""
    store = HookRuleStore()
    await store.create(scope="tenant", rule_type="observe", rule_config={"n": 1}, tenant_id="t1")
    await store.create(scope="session", rule_type="observe", rule_config={"n": 2}, tenant_id="t1")
    await store.create(scope="tool", rule_type="observe", rule_config={"n": 3}, tenant_id="t1")
    await store.create(scope="tool", rule_type="observe", rule_config={"n": 4}, tenant_id="OTHER")

    everything = await store.list()
    assert len(everything) == 4

    scoped = await store.rules_in_scope(tool="bash", session_id="s1", tenant_id="t1")
    # The OTHER-tenant rule must not be visible.
    assert all(d.tenant_id == "t1" for d in scoped)
    configs = [d.rule_config["n"] for d in scoped]
    assert 4 not in configs

    ordered = await store.ordered_rules_for(tool="bash", session_id="s1", tenant_id="t1")
    scopes = [r.scope for r in ordered]
    # scope priority: tool > session > tenant
    assert scopes.index("tool") < scopes.index("session") < scopes.index("tenant")


@pytest.mark.asyncio
async def test_store_disabled_rule_is_excluded() -> None:
    store = HookRuleStore()
    doc = await store.create(scope="tool", rule_type="observe", rule_config={}, tenant_id="t1")
    await store.update(doc.rule_id, enabled=False)
    ordered = await store.ordered_rules_for(tool="bash", session_id="s", tenant_id="t1")
    assert all(r.enabled for r in ordered)


# --- store: cross-tenant isolation (regression) -----------------------------
#
# ``rule_id`` is a globally-unique uuid, so a lookup by id alone would let any
# tenant read / mutate / delete another tenant's hook rule — and hook rules are
# enforced on the tool-call path (``turn_admission`` → ``rules_in_scope``), so
# cross-tenant tampering hijacks another tenant's tool gating.


@pytest.mark.asyncio
async def test_store_get_is_tenant_scoped() -> None:
    store = HookRuleStore()
    doc = await store.create(scope="tool", rule_type="observe", rule_config={}, tenant_id="t1")

    assert await store.get(doc.rule_id, tenant_id="t1") is not None
    assert await store.get(doc.rule_id, tenant_id="t2") is None


@pytest.mark.asyncio
async def test_store_update_cannot_cross_tenant() -> None:
    store = HookRuleStore()
    doc = await store.create(scope="tool", rule_type="observe", rule_config={"n": 1}, tenant_id="t1")

    denied = await store.update(doc.rule_id, rule_config={"n": 999}, tenant_id="t2")
    assert denied is None, "a foreign tenant must not be able to update the rule"

    unchanged = await store.get(doc.rule_id, tenant_id="t1")
    assert unchanged.rule_config["n"] == 1


@pytest.mark.asyncio
async def test_store_delete_cannot_cross_tenant() -> None:
    store = HookRuleStore()
    doc = await store.create(scope="tool", rule_type="observe", rule_config={}, tenant_id="t1")

    assert await store.delete(doc.rule_id, tenant_id="t2") is False
    assert await store.get(doc.rule_id, tenant_id="t1") is not None
    assert await store.delete(doc.rule_id, tenant_id="t1") is True


@pytest.mark.asyncio
async def test_store_tenant_filter_on_create() -> None:
    """Rules must carry the tenant that created them, or isolation is meaningless."""
    store = HookRuleStore()
    doc = await store.create(scope="tenant", rule_type="observe", rule_config={}, tenant_id="t9")
    assert doc.tenant_id == "t9"
    stored = await store.get(doc.rule_id, tenant_id="t9")
    assert stored is not None and stored.tenant_id == "t9"
