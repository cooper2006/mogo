"""Five-event hook interception (feature 009).

Hooks run around tool invocation and session lifecycle:

* events: SessionStart / PreToolUse / PostToolUse / SessionEnd / MemoryCommit;
* PreToolUse rules: ``deny_tool`` / ``require_field`` / ``observe``;
* every hook is guarded by a timeout and **fails closed** (timeout / error /
  rule-parse failure all reject — never fail open).

This package holds the dependency-light core (rules + engine + timeout), so it is
unit-testable without the DSH runtime. The first delivery is PreToolUse only
(clarify OQ-3); the other events are the target state.
"""

from __future__ import annotations

from .engine import HookEngine, HookOutcome
from .rules import HookRule, RuleType, RuleScope, parse_rules
from .timeout import DEFAULT_HOOK_TIMEOUT_SECONDS, HookTimeout, run_with_timeout

__all__ = [
    "HookEngine",
    "HookOutcome",
    "HookRule",
    "RuleType",
    "RuleScope",
    "parse_rules",
    "HookTimeout",
    "run_with_timeout",
    "DEFAULT_HOOK_TIMEOUT_SECONDS",
]
