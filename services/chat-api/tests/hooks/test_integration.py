"""Tests for 009's hook integration (turn-admission mount + audit sink).

Coverage audit (2026-10-06): ``hooks/integration.py`` was at 0%. It carries the
PreToolUse mount point (T009) and the 100%-audited execution record (T011), so
it must not regress silently.

The audit sink is injected in these tests — the default writer talks to the 001
governance stream, which is out of scope here.
"""

from __future__ import annotations

import pytest

from app.dsh_runtime.hooks.engine import HookOutcome
from app.dsh_runtime.hooks.integration import (
    HookAuditEntry,
    audit_hook_execution,
    mount_into_turn_admission,
    mount_pre_tool_use,
)


# --- mount_pre_tool_use -----------------------------------------------------


def test_mount_allows_without_rules() -> None:
    outcome = mount_pre_tool_use("bash", {"command": "ls"})
    assert outcome.allowed is True
    assert outcome.failed_closed is False


def test_mount_denies_tool_rule() -> None:
    outcome = mount_pre_tool_use(
        "bash",
        {"command": "rm -rf /"},
        raw_rules=[{"scope": "tool", "rule_type": "deny_tool", "rule_config": {"tools": ["bash"]}}],
    )
    assert outcome.allowed is False


def test_mount_require_field_rejects_missing() -> None:
    outcome = mount_pre_tool_use(
        "http",
        {"url": "https://example.com"},
        raw_rules=[
            {"scope": "tool", "rule_type": "require_field", "rule_config": {"fields": ["auth"]}}
        ],
    )
    assert outcome.allowed is False
    assert outcome.rule_type == "require_field"


def test_mount_accepts_prebuilt_rules() -> None:
    from app.dsh_runtime.hooks.rules import parse_rules

    rules = parse_rules(
        [{"scope": "tool", "rule_type": "deny_tool", "rule_config": {"tools": ["bash"]}}]
    )
    outcome = mount_pre_tool_use("bash", {"command": "ls"}, rules=rules)
    assert outcome.allowed is False


# --- turn admission mount (T009) -------------------------------------------


def test_mount_into_turn_admission_blocks_denied_tool() -> None:
    """A denied tool must never reach the real admission callable."""
    called: list[str] = []

    def _admit(*args, **kwargs):
        called.append("admitted")
        return True

    outcome = mount_into_turn_admission(
        _admit,
        "bash",
        {"command": "rm -rf /"},
        raw_rules=[{"scope": "tool", "rule_type": "deny_tool", "rule_config": {"tools": ["bash"]}}],
    )
    assert outcome.allowed is False
    assert called == [], "fail-closed must short-circuit before admission"


def test_mount_into_turn_admission_invokes_admission_when_allowed() -> None:
    """Regression: the wrapped admission must actually be called on pass.

    ``mount_into_turn_admission`` used to accept ``admit_skill_selection`` and
    silently drop it, so the hook gate ran but the real admission never did.
    """
    seen: list[tuple] = []

    def _admit(*args, **kwargs):
        seen.append((args, kwargs))
        return True

    outcome = mount_into_turn_admission(_admit, "bash", {"command": "ls"})

    assert outcome.allowed is True
    assert len(seen) == 1, "the real admission callable must run when the hook passes"
    assert seen[0][0][0] == "bash" or seen[0][1].get("tool") == "bash"


def test_mount_into_turn_admission_propagates_denial() -> None:
    def _admit(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("admission must not run on denial")

    outcome = mount_into_turn_admission(
        _admit, "bash", {"command": "x"}, raw_rules=["malformed-rule"]
    )
    assert outcome.allowed is False


def test_mount_into_turn_admission_reports_admission_rejection() -> None:
    """Hook passes but admission says no → the outcome must not read as allowed."""
    outcome = mount_into_turn_admission(
        lambda tool, request: False, "bash", {"command": "ls"}
    )
    assert outcome.allowed is False
    assert "admission" in outcome.reason


# --- audit (T011) -----------------------------------------------------------


def test_audit_entry_document_shape() -> None:
    entry = HookAuditEntry(
        tenant_id="t1",
        user_id="u1",
        tool="bash",
        allowed=False,
        reason="denied by rule",
        rule_type="deny_tool",
        scope="tool",
        failed_closed=False,
    )
    doc = entry.as_document()
    assert doc["event"] == "hook.executed"
    assert doc["tool"] == "bash"
    assert doc["allowed"] is False
    assert doc["rule_type"] == "deny_tool"


@pytest.mark.asyncio
async def test_audit_sink_receives_allowed_event() -> None:
    captured: list[dict] = []

    async def _sink(**kwargs):
        captured.append(kwargs)

    outcome = HookOutcome(allowed=True, reason="", rule_type="", scope="", failed_closed=False)
    entry = await audit_hook_execution(
        outcome, tenant_id="t1", user_id="u1", tool="bash", sink=_sink
    )

    assert entry.allowed is True
    assert len(captured) == 1
    assert captured[0]["action"] == "hook.executed"
    assert captured[0]["target"] == "bash"
    assert captured[0]["details"]["event"] == "hook.executed"


@pytest.mark.asyncio
async def test_audit_sink_receives_denied_event() -> None:
    captured: list[dict] = []

    async def _sink(**kwargs):
        captured.append(kwargs)

    outcome = HookOutcome(
        allowed=False, reason="blocked", rule_type="deny_tool", scope="tool", failed_closed=True
    )
    entry = await audit_hook_execution(
        outcome, tenant_id="t1", user_id="u1", tool="rm", sink=_sink
    )

    assert entry.failed_closed is True
    assert captured[0]["action"] == "hook.denied"
    assert captured[0]["details"]["failed_closed"] is True
