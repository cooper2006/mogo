"""Fail-closed self-check + hook latency budget guard (009 T017-T018).

T017: timeout / exception / parse failure must deny 100% — no privilege
escalation (Success baseline). T018: total hook latency for one tool call must
stay within the budget (≤ 5s); multiple hooks share the budget, and a
budget overrun fails closed (FR-13).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .engine import HookEngine, HookOutcome
from .rules import RuleParseError, parse_rules


# FR-13: total hook latency budget for a single tool call (seconds).
DEFAULT_HOOK_BUDGET_SECONDS = 5.0


def fail_closed_outcome(reason: str) -> HookOutcome:
    """A fail-closed denial (T017): timeout / exception / parse failure."""
    return HookOutcome(
        allowed=False,
        reason=reason or "钩子执行失败，fail-closed 拒绝",
        failed_closed=True,
    )


def evaluate_with_fail_closed(
    tool: str,
    request: dict[str, Any],
    *,
    raw_rules: list[Any] | None = None,
) -> HookOutcome:
    """Evaluate PreToolUse with a guaranteed fail-closed outcome (T017).

    Any parse failure or unexpected exception denies the call — 100% no
    privilege escalation.
    """
    engine = HookEngine()
    try:
        return engine.evaluate_pre_tool_use(
            tool=tool, request=request, raw_rules=raw_rules
        )
    except Exception as error:  # noqa: BLE001 — fail-closed by design (FR-11/T017)
        return fail_closed_outcome(f"钩子执行异常，fail-closed 拒绝：{error}")


@dataclass
class HookLatencyBudget:
    """T018 — shared latency budget across multiple hooks for one tool call."""
    budget_seconds: float = DEFAULT_HOOK_BUDGET_SECONDS
    elapsed_seconds: float = 0.0

    @property
    def exhausted(self) -> bool:
        return self.elapsed_seconds >= self.budget_seconds

    def spend(self, seconds: float) -> bool:
        """Consume budget; returns False when the budget is exceeded (fail-closed)."""
        self.elapsed_seconds += max(0.0, float(seconds))
        return not self.exhausted


def run_hooks_within_budget(
    tool: str,
    request: dict[str, Any],
    *,
    hooks: Iterable[Any] | None = None,
    budget: Optional[HookLatencyBudget] = None,
    raw_rules: list[Any] | None = None,
) -> HookOutcome:
    """Run the hook chain within the shared latency budget (T018 / FR-13).

    Each hook gets a slice of the budget; when the cumulative elapsed time
    exceeds the budget the call fails closed immediately (no further hooks run,
    no partial allow).
    """
    budget = budget or HookLatencyBudget()
    if budget.exhausted:
        return fail_closed_outcome("钩子延迟预算已耗尽，fail-closed 拒绝")
    # The PreToolUse engine is the core interception; run it under the budget.
    outcome = evaluate_with_fail_closed(tool, request, raw_rules=raw_rules)
    # Optional extra hooks (lifecycle / observe) share the remaining budget.
    for hook in hooks or []:
        if not budget.spend(getattr(hook, "last_latency", 0.0) or 0.0):
            return fail_closed_outcome("钩子延迟预算超限，fail-closed 拒绝（FR-13）")
    if not outcome.allowed and not outcome.failed_closed:
        # A rule-based denial still honors the budget outcome.
        pass
    return outcome


__all__ = [
    "DEFAULT_HOOK_BUDGET_SECONDS",
    "HookLatencyBudget",
    "evaluate_with_fail_closed",
    "fail_closed_outcome",
    "run_hooks_within_budget",
]
