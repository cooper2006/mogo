"""Admin hook_rules CRUD store (009 T015-T016) — admin-api side.

Mirrors the chat-api ``HookRuleStore`` collection layout (``hook_rules``) so the
admin console and the runtime PreToolUse engine share one Mongo collection.
This copy is intentionally dependency-free (no chat-api imports) and only
validates the rule's *shape*; the runtime's own ``parse_rule`` remains the
authoritative fail-closed check.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

HOOK_RULES_COLLECTION = "hook_rules"

VALID_SCOPES = ("tool", "session", "tenant")
VALID_RULE_TYPES = ("deny_tool", "require_field", "observe")


def _rule_id() -> str:
    return f"hr-{uuid.uuid4()}"


@dataclass
class HookRuleDocument:
    rule_id: str
    scope: str
    rule_type: str
    rule_config: dict[str, Any] = field(default_factory=dict)
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


class RuleValidationError(ValueError):
    """Fail-closed rejection of an invalid hook rule shape."""


class HookRuleStore:
    """In-memory / Mongo-backed declarative hook rule CRUD (009 T015)."""

    def __init__(self, db: Optional[Any] = None) -> None:
        self._db = db
        self._rules: dict[str, HookRuleDocument] = {}

    # --- shape validation (fail-closed, T015) ---------------------------------

    @staticmethod
    def _validate(*, scope: str, rule_type: str, rule_config: dict[str, Any]) -> None:
        if scope not in VALID_SCOPES:
            raise RuleValidationError(f"invalid hook rule scope: {scope!r} (must be one of {VALID_SCOPES})")
        if rule_type not in VALID_RULE_TYPES:
            raise RuleValidationError(f"invalid hook rule type: {rule_type!r} (must be one of {VALID_RULE_TYPES})")
        if not isinstance(rule_config, dict):
            raise RuleValidationError("rule_config must be an object")
        if rule_type == "deny_tool" and not rule_config.get("tool"):
            raise RuleValidationError("deny_tool rule requires 'tool' in rule_config")
        if rule_type == "require_field" and not rule_config.get("field"):
            raise RuleValidationError("require_field rule requires 'field' in rule_config")

    # --- CRUD -----------------------------------------------------------------

    async def create(
        self,
        *,
        scope: str,
        rule_type: str,
        rule_config: dict[str, Any] | None = None,
        enabled: bool = True,
        tenant_id: str = "",
    ) -> HookRuleDocument:
        self._validate(scope=scope, rule_type=rule_type, rule_config=rule_config or {})
        document = HookRuleDocument(
            rule_id=_rule_id(),
            scope=scope,
            rule_type=rule_type,
            rule_config=dict(rule_config or {}),
            enabled=enabled,
            tenant_id=tenant_id,
        )
        if self._db is not None:
            await self._db[HOOK_RULES_COLLECTION].insert_one(document.as_document())
        else:
            self._rules[document.rule_id] = document
        return document

    async def get(self, rule_id: str) -> Optional[HookRuleDocument]:
        if self._db is not None:
            row = await self._db[HOOK_RULES_COLLECTION].find_one({"rule_id": rule_id})
            return self._from_row(row) if row else None
        return self._rules.get(rule_id)

    async def update(
        self,
        rule_id: str,
        *,
        enabled: Optional[bool] = None,
        rule_config: Optional[dict[str, Any]] = None,
        scope: Optional[str] = None,
        rule_type: Optional[str] = None,
    ) -> Optional[HookRuleDocument]:
        document = await self.get(rule_id)
        if document is None:
            return None
        document.enabled = enabled if enabled is not None else document.enabled
        document.rule_config = rule_config if rule_config is not None else document.rule_config
        document.scope = scope if scope is not None else document.scope
        document.rule_type = rule_type if rule_type is not None else document.rule_type
        self._validate(scope=document.scope, rule_type=document.rule_type, rule_config=document.rule_config)
        if self._db is not None:
            await self._db[HOOK_RULES_COLLECTION].update_one(
                {"rule_id": rule_id}, {"$set": document.as_document()}
            )
        return document

    async def delete(self, rule_id: str) -> bool:
        if self._db is not None:
            result = await self._db[HOOK_RULES_COLLECTION].delete_one({"rule_id": rule_id})
            return bool(getattr(result, "deleted_count", 0))
        return self._rules.pop(rule_id, None) is not None

    async def list(self, *, tenant_id: str = "") -> list[HookRuleDocument]:
        if self._db is not None:
            query = {"tenant_id": tenant_id} if tenant_id else {}
            rows = await self._db[HOOK_RULES_COLLECTION].find(query).to_list(length=10000)
            return [self._from_row(row) for row in rows if row]
        return [r for r in self._rules.values() if not tenant_id or r.tenant_id == tenant_id]

    # --- scope query (009 T016): tool > session > tenant ---------------------

    async def rules_in_scope(
        self,
        *,
        tool: str,
        session_id: str = "",
        tenant_id: str = "",
    ) -> list[HookRuleDocument]:
        """Enabled rules matching the request context (T016: tool > session > tenant)."""
        enabled = [r for r in await self.list(tenant_id=tenant_id) if r.enabled]
        matching: list[HookRuleDocument] = []
        for document in enabled:
            if document.scope == "tool":
                if document.rule_config.get("tool") == tool:
                    matching.append(document)
            elif document.scope == "session" and session_id:
                matching.append(document)
            elif document.scope == "tenant":
                matching.append(document)
        return matching

    async def ordered_rules_for(
        self,
        *,
        tool: str,
        session_id: str = "",
        tenant_id: str = "",
    ) -> list[HookRuleDocument]:
        """In-scope rules ordered most-specific-first (tool, session, tenant)."""
        scope_rank = {"tool": 0, "session": 1, "tenant": 2}
        documents = await self.rules_in_scope(tool=tool, session_id=session_id, tenant_id=tenant_id)
        return sorted(documents, key=lambda d: scope_rank.get(d.scope, 3))

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


__all__ = [
    "HOOK_RULES_COLLECTION",
    "HookRuleDocument",
    "HookRuleStore",
    "RuleValidationError",
    "VALID_RULE_TYPES",
    "VALID_SCOPES",
]
