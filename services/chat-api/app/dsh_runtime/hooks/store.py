"""Hook rules management (009 T015-T016 / US5) — CRUD + three-level scope query.

``HookRuleStore`` persists declarative hook rules (MongoDB-backed when a DB is
available, in-memory otherwise). Rules take effect immediately: the PreToolUse
engine reads the latest rules at call time.

Scope query (T016) matches rules at three levels: ``tool`` > ``session`` >
``tenant`` — a rule is in scope for a request when its scope level is at least
the request's context, with the narrowest matching scope winning (FR-9).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .registry import PRE_TOOL_USE
from .rules import (
    HookRule,
    RuleParseError,
    RuleScope,
    SCOPE_PRIORITY,
    parse_rule,
    parse_rules,
    sort_rules,
)


HOOK_RULES_COLLECTION = "hook_rules"


def _rule_id() -> str:
    return f"hr-{uuid.uuid4()}"


@dataclass
class HookRuleDocument:
    rule_id: str
    scope: str
    rule_type: str
    rule_config: dict[str, Any]
    enabled: bool = True
    tenant_id: str = ""

    def as_document(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "scope": self.scope,
            "rule_type": self.rule_type,
            "rule_config": dict(self.rule_config),
            "enabled": self.enabled,
            "tenant_id": self.tenant_id,
        }

    def to_hook_rule(self) -> HookRule:
        return HookRule(
            scope=self.scope,
            rule_type=self.rule_type,
            rule_config=dict(self.rule_config),
            enabled=self.enabled,
        )


class HookRuleStore:
    """In-memory / Mongo-backed declarative hook rule CRUD (009 T015)."""

    def __init__(self, db: Optional[Any] = None) -> None:
        self._db = db
        self._rules: dict[str, HookRuleDocument] = {}

    # --- create / read / update / delete ------------------------------------

    def create(
        self,
        *,
        scope: str,
        rule_type: str,
        rule_config: dict[str, Any] | None = None,
        enabled: bool = True,
        tenant_id: str = "",
    ) -> HookRuleDocument:
        # Fail-closed: validate the rule before persisting (FR-11).
        try:
            parse_rule(
                {
                    "scope": scope,
                    "rule_type": rule_type,
                    "rule_config": rule_config or {},
                    "enabled": enabled,
                }
            )
        except RuleParseError as error:
            raise RuleParseError(f"invalid hook rule rejected: {error}") from error
        document = HookRuleDocument(
            rule_id=_rule_id(),
            scope=scope,
            rule_type=rule_type,
            rule_config=dict(rule_config or {}),
            enabled=enabled,
            tenant_id=tenant_id,
        )
        if self._db is not None:
            self._db[HOOK_RULES_COLLECTION].insert_one(document.as_document())
        else:
            self._rules[document.rule_id] = document
        return document

    def get(self, rule_id: str) -> Optional[HookRuleDocument]:
        if self._db is not None:
            row = self._db[HOOK_RULES_COLLECTION].find_one({"rule_id": rule_id})
            return self._from_row(row) if row else None
        return self._rules.get(rule_id)

    def update(
        self,
        rule_id: str,
        *,
        enabled: Optional[bool] = None,
        rule_config: Optional[dict[str, Any]] = None,
        scope: Optional[str] = None,
        rule_type: Optional[str] = None,
    ) -> Optional[HookRuleDocument]:
        document = self.get(rule_id)
        if document is None:
            return None
        document.enabled = enabled if enabled is not None else document.enabled
        document.rule_config = rule_config if rule_config is not None else document.rule_config
        document.scope = scope if scope is not None else document.scope
        document.rule_type = rule_type if rule_type is not None else document.rule_type
        if self._db is not None:
            self._db[HOOK_RULES_COLLECTION].update_one(
                {"rule_id": rule_id}, {"$set": document.as_document()}
            )
        return document

    def delete(self, rule_id: str) -> bool:
        if self._db is not None:
            result = self._db[HOOK_RULES_COLLECTION].delete_one({"rule_id": rule_id})
            return bool(getattr(result, "deleted_count", 0))
        return self._rules.pop(rule_id, None) is not None

    def list(self, *, tenant_id: str = "") -> list[HookRuleDocument]:
        if self._db is not None:
            query = {"tenant_id": tenant_id} if tenant_id else {}
            rows = self._db[HOOK_RULES_COLLECTION].find(query).to_list(length=10000)
            return [self._from_row(row) for row in rows if row]
        return [r for r in self._rules.values() if not tenant_id or r.tenant_id == tenant_id]

    # --- scope query (009 T016) ---------------------------------------------

    def rules_in_scope(
        self,
        *,
        tool: str,
        session_id: str = "",
        tenant_id: str = "",
    ) -> list[HookRuleDocument]:
        """Rules matching the request context, narrowed to the matching scope level.

        T016: tool > session > tenant. A rule applies when its ``scope`` level
        matches the most specific context present. The narrowest matching scope
        wins (FR-9); ties keep all matching rules so the engine can order them.
        """
        all_rules = self.list(tenant_id=tenant_id)
        enabled = [r for r in all_rules if r.enabled]
        matching: list[HookRuleDocument] = []
        # Most specific first: tool, then session, then tenant.
        for document in enabled:
            if document.scope == RuleScope.TOOL.value:
                rule = document.to_hook_rule()
                if rule.matches_tool(tool):
                    matching.append(document)
            elif document.scope == RuleScope.SESSION.value and session_id:
                matching.append(document)
            elif document.scope == RuleScope.TENANT.value:
                matching.append(document)
        return matching

    def ordered_rules_for(
        self,
        *,
        tool: str,
        session_id: str = "",
        tenant_id: str = "",
    ) -> list[HookRule]:
        """In-scope rules ordered for evaluation (scope desc, then type desc)."""
        documents = self.rules_in_scope(tool=tool, session_id=session_id, tenant_id=tenant_id)
        rules = [document.to_hook_rule() for document in documents]
        return sort_rules(rules)

    @staticmethod
    def _from_row(row: dict[str, Any]) -> HookRuleDocument:
        return HookRuleDocument(
            rule_id=str(row.get("rule_id") or ""),
            scope=str(row.get("scope") or ""),
            rule_type=str(row.get("rule_type") or ""),
            rule_config=dict(row.get("rule_config") or {}),
            enabled=bool(row.get("enabled", True)),
            tenant_id=str(row.get("tenant_id") or ""),
        )


__all__ = ["HOOK_RULES_COLLECTION", "HookRuleDocument", "HookRuleStore"]
