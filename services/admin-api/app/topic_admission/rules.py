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


def _rule_matches(rule: dict[str, Any], status: str, pattern: re.Pattern[str] | None) -> bool:
    """复现原 ``$unwind`` + ``$match`` 的过滤语义，不依赖聚合管道。

    该集合是「每租户一个文档」（见 ``service.get_policy``），规则存在 ``rules``
    数组里。PanWeiDB 兼容层 ``pg_compat`` 未实现 ``$unwind`` / ``$facet``，
    原来走 ``aggregate`` 会在 panweidb 后端抛 ``PgCompatUnsupported`` → 500。
    改为在 ``find_one`` 取回单文档后于 Python 侧展开，两个后端行为一致。
    """
    if status in ("enabled", "disabled"):
        # 与 TopicRule.enabled 默认值、get_summary 的 enabledRuleCount 口径一致：
        # 历史数据缺字段时按「启用」处理，避免列表可见却筛不出来。
        if bool(rule.get("enabled", True)) != (status == "enabled"):
            return False
    if pattern is None:
        return True
    haystacks = [str(rule.get("name") or "")]
    for term in rule.get("terms") or []:
        if not isinstance(term, dict):
            continue
        haystacks.append(str(term.get("keyword") or ""))
        synonyms = term.get("synonyms") or []
        if isinstance(synonyms, (list, tuple)):
            haystacks.extend(str(value) for value in synonyms)
        else:
            haystacks.append(str(synonyms))
    # Mongo 的 $regex 对数组字段匹配任一元素；这里等价地逐项 search。
    return any(pattern.search(text) for text in haystacks)


async def search_rules(tenant_id: str, query: str, status: str, page: int, page_size: int, offset: int | None = None) -> dict[str, Any]:
    row = await get_db()[COLLECTION].find_one({"tenant_id": tenant_id})
    rules: list[dict[str, Any]] = list((row or {}).get("rules") or [])
    needle = query.strip()
    pattern = re.compile(re.escape(needle), re.IGNORECASE) if needle else None
    matched = [rule for rule in rules if _rule_matches(rule, status, pattern)]
    start = offset if offset is not None else (page - 1) * page_size
    items = matched[start:start + page_size]
    return {"items": items, "total": len(matched), "page": page, "pageSize": page_size}


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
