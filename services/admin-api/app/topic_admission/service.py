"""Organization-scoped persistence and preview for topic admission."""

from __future__ import annotations

from datetime import datetime, timezone
import unicodedata
from typing import Any

from app.core.db import get_db

from .models import TopicPolicyPayload


COLLECTION = "topic_admission_policies"


def empty_policy() -> dict[str, Any]:
    return {"mode": "off", "rules": [], "updatedAt": None}


async def get_policy(tenant_id: str) -> dict[str, Any]:
    row = await get_db()[COLLECTION].find_one({"tenant_id": tenant_id})
    if row is None:
        return empty_policy()
    return {
        "mode": row.get("mode", "off"),
        "rules": row.get("rules") or [],
        "updatedAt": row.get("updated_at").isoformat() if row.get("updated_at") else None,
    }


async def save_policy(tenant_id: str, actor: str, payload: TopicPolicyPayload) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    await get_db()[COLLECTION].update_one(
        {"tenant_id": tenant_id},
        {"$set": {"mode": payload.mode, "rules": [rule.model_dump() for rule in payload.rules],
                  "updated_at": now, "updated_by": actor},
         "$setOnInsert": {"tenant_id": tenant_id, "created_at": now}},
        upsert=True,
    )
    return await get_policy(tenant_id)


def preview(text: str, payload: TopicPolicyPayload) -> dict[str, Any]:
    content = unicodedata.normalize("NFKC", text).casefold()
    matched: dict[str, Any] | None = None
    if payload.mode != "off":
        for rule in payload.rules:
            if not rule.enabled:
                continue
            if any(unicodedata.normalize("NFKC", token).casefold() in content
                   for entry in rule.terms for token in [entry.keyword, *entry.synonyms]):
                matched = {"id": rule.id, "keyword": rule.terms[0].keyword}
                break
    allowed = payload.mode == "off" or (matched is None if payload.mode == "denylist" else matched is not None)
    return {"allowed": allowed, "matchedRule": matched, "mode": payload.mode}


async def ensure_indexes() -> None:
    await get_db()[COLLECTION].create_index([("tenant_id", 1)], unique=True)
