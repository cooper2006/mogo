"""PreToolUse rule engine (009 FR-2 / FR-9 / FR-10 / FR-11).

Evaluation order (FR-9): rules are sorted by scope (tool > session > tenant) then
by type (deny > require > observe). ``deny`` short-circuits immediately; ``require``
rejects when a required field is missing; ``observe`` only records.

Any parse failure or unexpected error denies the call (fail-closed, FR-11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .rules import HookRule, RuleParseError, RuleType, parse_rules, sort_rules


@dataclass
class HookOutcome:
    """Result of evaluating PreToolUse rules for one tool call."""

    allowed: bool
    reason: str = ""
    rule_type: str = ""
    scope: str = ""
    observations: list[dict[str, Any]] = field(default_factory=list)
    failed_closed: bool = False

    @property
    def status_code(self) -> int:
        return 403 if not self.allowed else 200


class HookEngine:
    """Evaluates declarative PreToolUse rules against a tool call."""

    def evaluate_pre_tool_use(
        self,
        *,
        tool: str,
        request: dict[str, Any] | None = None,
        raw_rules: Iterable[Any] | None = None,
        rules: Iterable[HookRule] | None = None,
    ) -> HookOutcome:
        payload = request or {}
        try:
            if rules is None:
                parsed = parse_rules(raw_rules or [])
            else:
                parsed = list(rules)
        except RuleParseError as error:
            # A malformed rule is a configuration failure: deny (FR-11).
            return HookOutcome(
                allowed=False,
                reason=f"钩子规则解析失败：{error}",
                failed_closed=True,
            )

        observations: list[dict[str, Any]] = []
        for rule in sort_rules(parsed):
            if not rule.matches_tool(tool):
                continue

            if rule.rule_type == RuleType.DENY_TOOL.value:
                return HookOutcome(
                    allowed=False,
                    reason=f"被钩子规则拒绝：deny_tool({tool})",
                    rule_type=rule.rule_type,
                    scope=rule.scope,
                    observations=observations,
                )

            if rule.rule_type == RuleType.REQUIRE_FIELD.value:
                missing = [
                    name
                    for name in rule.required_fields()
                    if name not in payload or payload.get(name) in (None, "")
                ]
                if missing:
                    return HookOutcome(
                        allowed=False,
                        reason=f"缺少必填字段：{', '.join(missing)}",
                        rule_type=rule.rule_type,
                        scope=rule.scope,
                        observations=observations,
                    )

            if rule.rule_type == RuleType.OBSERVE.value:
                observations.append(
                    {
                        "scope": rule.scope,
                        "tool": tool,
                        "config": dict(rule.rule_config),
                    }
                )

        return HookOutcome(allowed=True, reason="hooks passed", observations=observations)
