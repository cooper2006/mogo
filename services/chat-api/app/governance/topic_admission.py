"""Deterministic, pre-model topic admission for organization chat turns."""

from __future__ import annotations

from typing import Any

from app.utils.topic_matcher import matching_rule


COLLECTION = "topic_admission_policies"


class TopicAdmissionDenied(PermissionError):
    """The organization's current topic mode rejects this turn."""


class TopicAdmissionService:
    """Evaluate a tenant's policy using the application's explicit database."""

    def __init__(self, db: Any, *, audience_policy: Any | None = None) -> None:
        self._policies = db[COLLECTION]
        self._audience_policy = audience_policy

    async def require(self, *, tenant_id: str, user_id: str, text: str) -> None:
        allowed, _matched_rule_id = await self.evaluate(
            tenant_id=tenant_id, user_id=user_id, text=text,
        )
        if not allowed:
            raise TopicAdmissionDenied("当前任务被准入规则拦截，请联系管理员。")

    async def evaluate(self, *, tenant_id: str, user_id: str, text: str) -> tuple[bool, str | None]:
        policy = await self._policies.find_one({"tenant_id": tenant_id}, {"mode": 1, "rules": 1})
        mode = str((policy or {}).get("mode") or "off")
        if mode == "off":
            return True, None
        rules = [rule for rule in (policy or {}).get("rules") or [] if rule.get("enabled", True)]
        if self._audience_policy is not None:
            rules = await self._audience_policy.filter_rules(
                main_id=tenant_id, user_id=user_id, rules=rules,
            )
        matched = matching_rule(text, rules)
        if mode == "denylist":
            return matched is None, str(matched.get("id")) if matched else None
        if mode == "allowlist":
            return matched is not None, str(matched.get("id")) if matched else None
        return False, None
