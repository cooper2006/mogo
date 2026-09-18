from __future__ import annotations

from typing import Any

from app.core.db import get_db
from app.core.tenant import resolve_main_id


class PersonalKnowledgeFeedbackSummaryService:
    """Batched unread comment summaries used to prioritize knowledge list rows."""

    async def unread_by_resource(self, *, main_id: str, user_id: str) -> dict[str, dict[str, Any]]:
        rows = await get_db().resource_feedback_notifications.aggregate([
            {"$match": {
                "main_id": resolve_main_id(main_id),
                "resource_type": "personal_knowledge",
                "recipient_user_id": str(user_id),
                "status": "unread",
            }},
            {"$group": {
                "_id": "$resource_id",
                "count": {"$sum": 1},
                "latest": {"$max": "$created_at"},
            }},
        ]).to_list(length=100_000)
        return {
            str(row.get("_id") or ""): {
                "count": int(row.get("count") or 0),
                "latest": row.get("latest"),
            }
            for row in rows
            if str(row.get("_id") or "")
        }

    @staticmethod
    def attach(items: list[dict[str, Any]], summaries: dict[str, dict[str, Any]]) -> None:
        for item in items:
            summary = summaries.get(str(item.get("id") or ""), {})
            latest = summary.get("latest")
            item["feedback"] = {
                "unreadCount": int(summary.get("count") or 0),
                "latestUnreadAt": latest.isoformat() if hasattr(latest, "isoformat") else "",
            }


personal_knowledge_feedback_summary_service = PersonalKnowledgeFeedbackSummaryService()

