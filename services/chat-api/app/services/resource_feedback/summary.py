from __future__ import annotations

import logging
from typing import Any

from app.core.db import get_db
from app.core.tenant import resolve_main_id


logger = logging.getLogger(__name__)


class SkillFeedbackSummaryService:
    """Adds batched discussion counters and channel roles to Skill list rows."""

    async def attach(self, *, main_id: str, user_id: str, skills: list[dict[str, Any]]) -> None:
        candidates: dict[str, list[str]] = {}
        channel_ids: set[str] = set()
        for skill in skills:
            source = dict(skill.get("package_source") or {})
            ids = [str(source.get("distributionId") or ""), str(skill.get("distribution_id") or "")]
            unique = list(dict.fromkeys(item for item in ids if item))
            candidates[str(skill.get("id") or skill.get("_id") or "")] = unique
            channel_ids.update(unique)
        if not channel_ids:
            for skill in skills:
                skill["feedback"] = self._empty()
            return
        try:
            await self._attach(main_id=resolve_main_id(main_id), user_id=str(user_id), skills=skills, candidates=candidates, channel_ids=channel_ids)
        except Exception as exc:
            logger.warning("Skill feedback summaries unavailable", extra={"error": str(exc)[:500]})
            for skill in skills:
                skill["feedback"] = self._empty()

    async def _attach(self, *, main_id: str, user_id: str, skills: list[dict[str, Any]], candidates: dict[str, list[str]], channel_ids: set[str]) -> None:
        db = get_db()
        distributions = await db.skill_distributions.find({
            "main_id": main_id, "_id": {"$in": list(channel_ids)}, "status": "active",
        }).to_list(length=len(channel_ids))
        by_id = {str(row.get("_id") or ""): row for row in distributions}
        members = await db.skill_distribution_members.find({
            "main_id": main_id, "distribution_id": {"$in": list(channel_ids)},
            "recipient_user_id": user_id, "status": "active",
        }).to_list(length=len(channel_ids))
        member_ids = {str(row.get("distribution_id") or "") for row in members}
        allowed = {
            channel_id for channel_id, row in by_id.items()
            if str(row.get("owner_user_id") or "") == user_id or channel_id in member_ids
        }
        counts = await self._group_counts(db.resource_comments, {
            "main_id": main_id, "resource_type": "skill_distribution",
            "resource_id": {"$in": list(allowed)}, "status": "active",
        }, include_latest=True)
        unread = await self._group_counts(db.resource_feedback_notifications, {
            "main_id": main_id, "resource_type": "skill_distribution",
            "resource_id": {"$in": list(allowed)}, "recipient_user_id": user_id, "status": "unread",
        })
        for skill in skills:
            skill_id = str(skill.get("id") or skill.get("_id") or "")
            channels = []
            for channel_id in candidates.get(skill_id, []):
                if channel_id not in allowed:
                    continue
                role = "owner" if str(by_id[channel_id].get("owner_user_id") or "") == user_id else "member"
                channels.append({
                    "id": channel_id, "role": role,
                    "commentCount": int((counts.get(channel_id) or {}).get("count") or 0),
                    "unreadCount": int((unread.get(channel_id) or {}).get("count") or 0),
                    "latestCommentAt": str((counts.get(channel_id) or {}).get("latest") or ""),
                })
            skill["feedback"] = {
                "commentCount": sum(item["commentCount"] for item in channels),
                "unreadCount": sum(item["unreadCount"] for item in channels),
                "channels": channels,
            }

    @staticmethod
    async def _group_counts(collection: Any, match: dict[str, Any], *, include_latest: bool = False) -> dict[str, dict[str, Any]]:
        group: dict[str, Any] = {"_id": "$resource_id", "count": {"$sum": 1}}
        if include_latest:
            group["latest"] = {"$max": "$created_at"}
        rows = await collection.aggregate([{"$match": match}, {"$group": group}]).to_list(length=100_000)
        result = {}
        for row in rows:
            latest = row.get("latest")
            result[str(row.get("_id") or "")] = {
                "count": int(row.get("count") or 0),
                "latest": latest.isoformat() if hasattr(latest, "isoformat") else "",
            }
        return result

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"commentCount": 0, "unreadCount": 0, "channels": []}


skill_feedback_summary_service = SkillFeedbackSummaryService()
