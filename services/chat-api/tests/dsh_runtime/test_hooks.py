"""Tests for five-event hook interception core (feature 009): rules / engine / timeout."""

from __future__ import annotations

import asyncio

import pytest

from app.dsh_runtime.hooks.engine import HookEngine
from app.dsh_runtime.hooks.rules import (
    RuleParseError,
    RuleScope,
    RuleType,
    parse_rule,
    parse_rules,
    sort_rules,
)
from app.dsh_runtime.hooks.timeout import (
    DEFAULT_HOOK_TIMEOUT_SECONDS,
    HookTimeout,
    run_with_timeout,
    total_latency_budget_exceeded,
)


# --- rules -------------------------------------------------------------------

def test_parse_valid_rule() -> None:
    rule = parse_rule({"scope": "tool", "rule_type": "deny_tool", "rule_config": {"tool": "rm"}})
    assert rule.scope == "tool"
    assert rule.rule_type == "deny_tool"
    assert rule.enabled is True


def test_parse_rejects_unknown_scope() -> None:
    with pytest.raises(RuleParseError):
        parse_rule({"scope": "galaxy", "rule_type": "deny_tool"})


def test_parse_rejects_unknown_rule_type() -> None:
    with pytest.raises(RuleParseError):
        parse_rule({"scope": "tool", "rule_type": "explode"})


def test_parse_rejects_missing_fields() -> None:
    with pytest.raises(RuleParseError):
        parse_rule({"rule_type": "deny_tool"})
    with pytest.raises(RuleParseError):
        parse_rule({"scope": "tool"})


def test_parse_rejects_non_object() -> None:
    with pytest.raises(RuleParseError):
        parse_rule("not-an-object")


def test_parse_rules_skips_disabled() -> None:
    rules = parse_rules(
        [
            {"scope": "tool", "rule_type": "deny_tool", "enabled": True},
            {"scope": "tool", "rule_type": "observe", "enabled": False},
        ]
    )
    assert len(rules) == 1
    assert rules[0].rule_type == "deny_tool"


def test_sort_rules_scope_then_type() -> None:
    rules = parse_rules(
        [
            {"scope": "tenant", "rule_type": "deny_tool"},
            {"scope": "tool", "rule_type": "observe"},
            {"scope": "tool", "rule_type": "deny_tool"},
        ]
    )
    ordered = sort_rules(rules)
    assert ordered[0].scope == "tool" and ordered[0].rule_type == "deny_tool"
    assert ordered[-1].scope == "tenant"


def test_observe_is_not_intercepting() -> None:
    rule = parse_rule({"scope": "tool", "rule_type": "observe"})
    assert not rule.is_intercepting


# --- engine ------------------------------------------------------------------

def test_deny_tool_blocks_call() -> None:
    engine = HookEngine()
    outcome = engine.evaluate_pre_tool_use(
        tool="rm",
        raw_rules=[{"scope": "tool", "rule_type": "deny_tool", "rule_config": {"tool": "rm"}}],
    )
    assert not outcome.allowed
    assert outcome.status_code == 403
    assert "deny_tool" in outcome.reason


def test_deny_only_matches_target_tool() -> None:
    engine = HookEngine()
    outcome = engine.evaluate_pre_tool_use(
        tool="safe",
        raw_rules=[{"scope": "tool", "rule_type": "deny_tool", "rule_config": {"tool": "rm"}}],
    )
    assert outcome.allowed


def test_require_field_blocks_when_missing() -> None:
    engine = HookEngine()
    outcome = engine.evaluate_pre_tool_use(
        tool="crm",
        request={"name": "x"},
        raw_rules=[
            {"scope": "tool", "rule_type": "require_field", "rule_config": {"fields": ["customer_id"]}}
        ],
    )
    assert not outcome.allowed
    assert "customer_id" in outcome.reason


def test_require_field_passes_when_present() -> None:
    engine = HookEngine()
    outcome = engine.evaluate_pre_tool_use(
        tool="crm",
        request={"customer_id": "c-1"},
        raw_rules=[
            {"scope": "tool", "rule_type": "require_field", "rule_config": {"fields": ["customer_id"]}}
        ],
    )
    assert outcome.allowed


def test_observe_records_without_blocking() -> None:
    engine = HookEngine()
    outcome = engine.evaluate_pre_tool_use(
        tool="crm",
        raw_rules=[{"scope": "tool", "rule_type": "observe", "rule_config": {"note": "track"}}],
    )
    assert outcome.allowed
    assert outcome.observations and outcome.observations[0]["tool"] == "crm"


def test_deny_short_circuits_before_require() -> None:
    engine = HookEngine()
    outcome = engine.evaluate_pre_tool_use(
        tool="crm",
        request={},
        raw_rules=[
            {"scope": "tenant", "rule_type": "require_field", "rule_config": {"fields": ["x"]}},
            {"scope": "tool", "rule_type": "deny_tool", "rule_config": {"tool": "crm"}},
        ],
    )
    assert not outcome.allowed
    assert outcome.rule_type == "deny_tool"  # deny won despite the require rule


def test_malformed_rule_fails_closed() -> None:
    engine = HookEngine()
    outcome = engine.evaluate_pre_tool_use(
        tool="crm",
        raw_rules=[{"scope": "tool", "rule_type": "not_a_rule"}],
    )
    assert not outcome.allowed
    assert outcome.failed_closed


def test_no_rules_allows() -> None:
    engine = HookEngine()
    outcome = engine.evaluate_pre_tool_use(tool="crm", raw_rules=[])
    assert outcome.allowed


# --- timeout -----------------------------------------------------------------

def test_default_timeout_is_five_seconds() -> None:
    assert DEFAULT_HOOK_TIMEOUT_SECONDS == 5.0


@pytest.mark.asyncio
async def test_run_with_timeout_returns_result() -> None:
    async def fast() -> str:
        return "done"

    assert await run_with_timeout(fast(), timeout_seconds=1) == "done"


@pytest.mark.asyncio
async def test_run_with_timeout_raises_hook_timeout() -> None:
    async def slow() -> str:
        await asyncio.sleep(0.2)
        return "late"

    with pytest.raises(HookTimeout):
        await run_with_timeout(slow(), timeout_seconds=0.01)


def test_total_latency_budget_exceeded() -> None:
    assert total_latency_budget_exceeded(6.0, budget_seconds=5.0)
    assert not total_latency_budget_exceeded(4.0, budget_seconds=5.0)
