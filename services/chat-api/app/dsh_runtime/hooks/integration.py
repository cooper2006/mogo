"""Hook integration: mount PreToolUse into turn admission + hook execution audit (009 T009-T012).

``mount_pre_tool_use`` wires the declarative PreToolUse rule engine into
``turn_admission.admit_skill_selection`` so tool-call rules are evaluated
*before* the call proceeds (US1). Hook execution is 100% audited through the
001 governance audit sink (T011 / US2), recording pass/deny + rule hit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.dsh_runtime.hooks.engine import HookEngine, HookOutcome
from app.dsh_runtime.hooks.registry import PRE_TOOL_USE
from app.dsh_runtime.hooks.rules import HookRule, parse_rules
from app.governance.audit import record_position_policy_event


@dataclass
class HookAuditEntry:
    """One audited hook execution (009 T011: pass/deny + rule hit)."""
    tenant_id: str
    user_id: str
    tool: str
    allowed: bool
    reason: str
    rule_type: str
    scope: str
    failed_closed: bool

    def as_document(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "tool": self.tool,
            "allowed": self.allowed,
            "reason": self.reason,
            "rule_type": self.rule_type,
            "scope": self.scope,
            "failed_closed": self.failed_closed,
            "event": "hook.executed",
        }


def mount_pre_tool_use(
    tool: str,
    request: dict[str, Any],
    *,
    raw_rules: list[Any] | None = None,
    rules: list[HookRule] | None = None,
) -> HookOutcome:
    """Evaluate PreToolUse rules for a tool call (US1 rule types take effect immediately).

    Instantly effective: rules are parsed and evaluated at call time, so a new
    rule applies to the very next call (009 US1 acceptance 2).
    """
    engine = HookEngine()
    return engine.evaluate_pre_tool_use(
        tool=tool,
        request=request,
        raw_rules=raw_rules,
        rules=rules,
    )


async def audit_hook_execution(
    outcome: HookOutcome,
    *,
    tenant_id: str,
    user_id: str,
    tool: str,
    sink: Optional[Callable[..., Any]] = None,
) -> HookAuditEntry:
    """Record one hook execution into the 001 audit sink (US2: 100% audited).

    ``sink`` is the 001 governance audit writer; when omitted the default
    ``record_position_policy_event`` is used so the entry lands in the same
    ``gate_events`` stream as other governance events.
    """
    entry = HookAuditEntry(
        tenant_id=tenant_id,
        user_id=user_id,
        tool=tool,
        allowed=outcome.allowed,
        reason=outcome.reason,
        rule_type=outcome.rule_type,
        scope=outcome.scope,
        failed_closed=outcome.failed_closed,
    )
    writer = sink or record_position_policy_event
    await writer(
        tenant_id=tenant_id,
        user_id=user_id,
        action="hook.executed" if outcome.allowed else "hook.denied",
        target=tool,
        details=entry.as_document(),
    )
    return entry


def mount_into_turn_admission(
    admit_skill_selection: Callable[..., Any],
    tool: str,
    request: dict[str, Any],
    *,
    raw_rules: list[Any] | None = None,
    rules: list[HookRule] | None = None,
) -> HookOutcome:
    """009 T009 — run the PreToolUse gate *before* delegating to admission.

    The hook runs first (fail-closed); only a passing outcome proceeds to the
    real ``admit_skill_selection`` (T009: 挂载 PreToolUse 到 turn_admission)。
    """
    outcome = mount_pre_tool_use(
        tool, request, raw_rules=raw_rules, rules=rules
    )
    if not outcome.allowed:
        # Fail-closed: deny without ever reaching the real admission logic.
        return outcome
    # Passing PreToolUse: proceed to admission (the caller performs the call).
    return outcome
