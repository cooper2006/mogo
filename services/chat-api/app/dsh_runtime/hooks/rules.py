"""Declarative hook rule schema + parsing (009 FR-2 / FR-4 / FR-11).

A rule document looks like::

    {"scope": "tool", "rule_type": "deny_tool", "rule_config": {...}, "enabled": true}

Rule parsing is **fail-closed**: invalid JSON, a missing required field, or an
unknown ``rule_type`` all raise ``RuleParseError`` so the caller rejects rather
than silently ignoring a malformed rule (FR-11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class RuleType(str, Enum):
    DENY_TOOL = "deny_tool"
    REQUIRE_FIELD = "require_field"
    OBSERVE = "observe"


class RuleScope(str, Enum):
    TOOL = "tool"
    SESSION = "session"
    TENANT = "tenant"


# Scope specificity: a narrower scope wins (FR-9: tool > session > tenant).
SCOPE_PRIORITY: dict[str, int] = {
    RuleScope.TOOL.value: 3,
    RuleScope.SESSION.value: 2,
    RuleScope.TENANT.value: 1,
}

# Rule-type evaluation order: deny short-circuits before require before observe (FR-9).
TYPE_PRIORITY: dict[str, int] = {
    RuleType.DENY_TOOL.value: 3,
    RuleType.REQUIRE_FIELD.value: 2,
    RuleType.OBSERVE.value: 1,
}


class RuleParseError(ValueError):
    """Raised for a malformed rule; callers must fail closed (FR-11)."""


@dataclass(frozen=True)
class HookRule:
    scope: str
    rule_type: str
    rule_config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

    @property
    def scope_priority(self) -> int:
        return SCOPE_PRIORITY.get(self.scope, 0)

    @property
    def type_priority(self) -> int:
        return TYPE_PRIORITY.get(self.rule_type, 0)

    @property
    def is_intercepting(self) -> bool:
        """Whether this rule can block a call (observe never blocks, FR-2)."""
        return self.rule_type in (RuleType.DENY_TOOL.value, RuleType.REQUIRE_FIELD.value)

    def matches_tool(self, tool: str) -> bool:
        """Whether the rule targets ``tool`` (empty config = all tools)."""
        target = self.rule_config.get("tool")
        if target in (None, "", "*"):
            return True
        if isinstance(target, list):
            return tool in target
        return str(target) == tool

    def required_fields(self) -> list[str]:
        fields = self.rule_config.get("fields") or self.rule_config.get("required_fields")
        if isinstance(fields, str):
            return [fields]
        if isinstance(fields, list):
            return [str(item) for item in fields if str(item)]
        return []


def parse_rule(document: Any) -> HookRule:
    """Parse one rule document, raising ``RuleParseError`` when malformed."""
    if not isinstance(document, dict):
        raise RuleParseError("rule must be an object")

    scope = str(document.get("scope") or "").strip()
    if scope not in SCOPE_PRIORITY:
        raise RuleParseError(f"unknown or missing scope: {scope!r}")

    rule_type = str(document.get("rule_type") or "").strip()
    if rule_type not in TYPE_PRIORITY:
        raise RuleParseError(f"unknown or missing rule_type: {rule_type!r}")

    rule_config = document.get("rule_config")
    if rule_config is None:
        rule_config = {}
    if not isinstance(rule_config, dict):
        raise RuleParseError("rule_config must be an object")

    return HookRule(
        scope=scope,
        rule_type=rule_type,
        rule_config=dict(rule_config),
        enabled=bool(document.get("enabled", True)),
    )


def parse_rules(documents: Iterable[Any]) -> list[HookRule]:
    """Parse a set of rule documents (any malformed rule raises, fail-closed)."""
    rules: list[HookRule] = []
    for document in documents:
        rule = parse_rule(document)
        if rule.enabled:
            rules.append(rule)
    return rules


def sort_rules(rules: Iterable[HookRule]) -> list[HookRule]:
    """Order rules for evaluation: scope desc (tool>session>tenant), then type desc.

    Deterministic ordering matters because ``deny`` must short-circuit (FR-9).
    """
    return sorted(
        rules,
        key=lambda rule: (rule.scope_priority, rule.type_priority),
        reverse=True,
    )
