from __future__ import annotations

from typing import Any

from .access import GRANT_COLLECTION


async def attach_share_summary(*, db: Any, main_id: str, items: list[dict[str, Any]]) -> None:
    """Attach active recipient counts to owner-facing knowledge rows in one query."""
    resource_ids = [str(item.get("id") or "") for item in items if item.get("id")]
    if not resource_ids:
        return
    rows = await db[GRANT_COLLECTION].find({
        "main_id": main_id,
        "resource_type": "personal_knowledge",
        "resource_id": {"$in": resource_ids},
        "status": "active",
    }, {"resource_id": 1}).to_list(length=100_000)
    counts: dict[str, int] = {}
    for row in rows:
        resource_id = str(row.get("resource_id") or "")
        if resource_id:
            counts[resource_id] = counts.get(resource_id, 0) + 1
    for item in items:
        recipient_count = counts.get(str(item.get("id") or ""), 0)
        item["share"] = {
            "shared": recipient_count > 0,
            "recipientCount": recipient_count,
        }
