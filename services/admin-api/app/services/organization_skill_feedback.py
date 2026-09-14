from __future__ import annotations

import datetime
from typing import Any

from app.core.db import get_db
from app.services.member_identity import public_identity


class OrganizationSkillFeedbackService:
    """Read the shared discussion attached to an enterprise Skill identity."""

    async def list(self, *, main_id: str, skill_id: str, limit: int = 100) -> dict[str, Any]:
        db = get_db()
        skill = await db.skills.find_one({"_id": skill_id, "main_id": main_id}, {"_id": 1})
        if skill is None:
            raise LookupError("技能不存在")
        query = {
            "main_id": main_id,
            "resource_type": "organization_skill",
            "resource_id": skill_id,
        }
        size = min(max(limit, 1), 200)
        rows = await db.resource_comments.find({**query, "status": "active"}).sort("created_at", 1).limit(size).to_list(length=size)
        comment_ids = [str(row.get("_id") or "") for row in rows]
        reactions = await db.resource_comment_reactions.find({
            "main_id": main_id, "comment_id": {"$in": comment_ids}, "reaction": "like",
        }).to_list(length=max(len(comment_ids) * 1000, 1)) if comment_ids else []
        comment_likes: dict[str, int] = {}
        for reaction in reactions:
            comment_id = str(reaction.get("comment_id") or "")
            comment_likes[comment_id] = comment_likes.get(comment_id, 0) + 1
        likes = await db.resource_reactions.count_documents({**query, "reaction": "like"})
        return {"items": [self._view(row, comment_likes) for row in rows], "likes": likes}

    @staticmethod
    def _view(row: dict[str, Any], comment_likes: dict[str, int]) -> dict[str, Any]:
        created = row.get("created_at")
        return {
            "id": str(row.get("_id") or ""),
            "content": str(row.get("content") or ""),
            "parentId": str(row.get("parent_id") or ""),
            "author": public_identity(row.get("author"), user_id=str(row.get("user_id") or "")),
            "likes": int(comment_likes.get(str(row.get("_id") or ""), 0)),
            "createdAt": created.isoformat() if isinstance(created, datetime.datetime) else "",
        }


organization_skill_feedback_service = OrganizationSkillFeedbackService()
