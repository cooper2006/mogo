"""Server-side rule search and partial policy updates."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.core.db import get_db

from .models import TopicChangesPayload
from .service import COLLECTION, get_policy, preview


MAX_RULES = 200


async def get_summary(tenant_id: str) -> dict[str, Any]:
    row = await get_db()[COLLECTION].find_one({"tenant_id": tenant_id}, {"mode": 1, "rules.id": 1, "rules.enabled": 1, "updated_at": 1})
    return {
        "mode": (row or {}).get("mode", "off"),
        "ruleCount": len((row or {}).get("rules") or []),
        "enabledRuleCount": sum(1 for rule in (row or {}).get("rules") or [] if rule.get("enabled", True)),
        "updatedAt": row["updated_at"].isoformat() if row and row.get("updated_at") else None,
    }


async def search_rules(tenant_id: str, query: str, status: str, page: int, page_size: int, offset: int | None = None) -> dict[str, Any]:
    match: dict[str, Any] = {}
    if status in ("enabled", "disabled"):
        match["rules.enabled"] = status == "enabled"
    if query.strip():
        needle = re.escape(query.strip())
        match["$or"] = [
            {"rules.name": {"$regex": needle, "$options": "i"}},
            {"rules.terms.keyword": {"$regex": needle, "$options": "i"}},
            {"rules.terms.synonyms": {"$regex": needle, "$options": "i"}},
        ]
    pipeline: list[dict[str, Any]] = [
        {"$match": {"tenant_id": tenant_id}},
        {"$unwind": {"path": "$rules", "includeArrayIndex": "position"}},
    ]
    if match:
        pipeline.append({"$match": match})
    pipeline.append({"$facet": {
        "items": [{"$sort": {"position": 1}}, {"$skip": offset if offset is not None else (page - 1) * page_size},
                  {"$limit": page_size}, {"$replaceRoot": {"newRoot": "$rules"}}],
        "count": [{"$count": "value"}],
    }})
    rows = await get_db()[COLLECTION].aggregate(pipeline).to_list(length=1)
    result = rows[0] if rows else {"items": [], "count": []}
    return {"items": result["items"], "total": result["count"][0]["value"] if result["count"] else 0,
            "page": page, "pageSize": page_size}


def merge_rules(existing: list[dict[str, Any]], changes: TopicChangesPayload) -> list[dict[str, Any]]:
    deleted = set(changes.deletes)
    upserts = {rule.id: rule.model_dump() for rule in changes.upserts}
    rules = [upserts.pop(rule["id"], rule) for rule in existing if rule["id"] not in deleted]
    rules.extend(upserts.values())
    if len(rules) > MAX_RULES:
        raise HTTPException(status_code=422, detail="too_many_topic_rules")
    return rules


async def save_changes(tenant_id: str, actor: str, changes: TopicChangesPayload) -> dict[str, Any]:
    row = await get_db()[COLLECTION].find_one({"tenant_id": tenant_id}, {"rules": 1, "updated_at": 1})
    current_version = row["updated_at"].isoformat() if row and row.get("updated_at") else None
    if current_version != changes.updatedAt:
        raise HTTPException(status_code=409, detail="topic_policy_changed")
    rules = merge_rules((row or {}).get("rules") or [], changes)
    now = datetime.now(timezone.utc)
    filter_by_version = {"tenant_id": tenant_id, "updated_at": row["updated_at"]} if current_version else {
        "tenant_id": tenant_id, "updated_at": {"$exists": False}}
    try:
        result = await get_db()[COLLECTION].update_one(
            filter_by_version,
            {"$set": {"mode": changes.mode, "rules": rules, "updated_at": now, "updated_by": actor},
             "$setOnInsert": {"tenant_id": tenant_id, "created_at": now}},
            upsert=row is None,
        )
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="topic_policy_changed") from exc
    if result.matched_count == 0 and result.upserted_id is None:
        raise HTTPException(status_code=409, detail="topic_policy_changed")
    return await get_summary(tenant_id)


async def preview_changes(tenant_id: str, text: str, changes: TopicChangesPayload) -> dict[str, Any]:
    policy = await get_policy(tenant_id)
    policy["mode"] = changes.mode
    policy["rules"] = merge_rules(policy["rules"], changes)
    from .models import TopicPolicyPayload
    return preview(text, TopicPolicyPayload.model_validate(policy))
