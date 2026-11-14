"""Paged, authorized document lookup for workflow source selection."""

from __future__ import annotations

import re
from typing import Any

from app.core.db import get_db
from app.core.tenant import resolve_tenant_id

from .access import GRANT_COLLECTION, RESOURCE_COLLECTION, PersonalKnowledgeAccessService
from .service import PersonalKnowledgeService


def _keyword_match(keyword: str, prefix: str = "") -> dict[str, Any]:
    needle = str(keyword or "").strip()[:120]
    if not needle:
        return {}
    pattern = {"$regex": re.escape(needle), "$options": "i"}
    return {"$or": [
        {f"{prefix}name": pattern},
        {f"{prefix}description": pattern},
        {f"{prefix}tags": pattern},
    ]}


async def search_selectable_documents(
    *, main_id: str, user_id: str, view: str, directory_id: str,
    keyword: str, page: int, page_size: int,
) -> dict[str, Any]:
    db = get_db()
    tenant_id = resolve_tenant_id(main_id)
    offset = (page - 1) * page_size
    service = PersonalKnowledgeService()
    ready = {
        "main_id": tenant_id,
        "deleted_at": None,
        "status": {"$in": ["parsed", "indexed"]},
        "active_document_id": {"$exists": True, "$nin": ["", None]},
    }
    if view == "mine":
        query = {**ready, "owner_user_id": str(user_id), **_keyword_match(keyword)}
        if directory_id != "all":
            query["directory_id"] = str(directory_id or "")
        collection = db[RESOURCE_COLLECTION]
        total = await collection.count_documents(query)
        rows = await collection.find(query).sort("updated_at", -1).skip(offset).limit(page_size).to_list(length=page_size)
        items = [service.resource_view(row) for row in rows]
    else:
        grant_query = {
            "main_id": tenant_id,
            "resource_type": "personal_knowledge",
            "recipient_user_id": str(user_id),
            "status": "active",
        }
        resource_query = {f"resource.{key}": value for key, value in ready.items()}
        resource_query.update(_keyword_match(keyword, "resource."))
        pipeline = [
            {"$match": grant_query},
            {"$lookup": {
                "from": RESOURCE_COLLECTION,
                "localField": "resource_id",
                "foreignField": "_id",
                "as": "resource",
            }},
            {"$unwind": "$resource"},
            {"$match": resource_query},
            {"$sort": {"resource.updated_at": -1, "_id": -1}},
            {"$facet": {
                "items": [{"$skip": offset}, {"$limit": page_size}],
                "count": [{"$count": "total"}],
            }},
        ]
        result = await db[GRANT_COLLECTION].aggregate(pipeline).to_list(length=1)
        batch = result[0] if result else {}
        total = int((batch.get("count") or [{}])[0].get("total") or 0)
        items = [
            service.resource_view(row.get("resource"), grant=row)
            for row in batch.get("items") or []
        ]
        await service._attach_people(tenant_id, items)
    return {"items": items, "total": total, "page": page, "pageSize": page_size}


async def selectable_document(
    *, main_id: str, user_id: str, resource_id: str,
) -> dict[str, Any]:
    access = await PersonalKnowledgeAccessService().require_view(
        main_id=main_id, user_id=user_id, resource_id=resource_id,
    )
    row = access.resource
    if (
        row.get("deleted_at") is not None
        or str(row.get("status") or "") not in {"parsed", "indexed"}
        or not str(row.get("active_document_id") or "")
    ):
        raise LookupError("knowledge_document_not_ready")
    return PersonalKnowledgeService.resource_view(row, grant=access.grant)


async def validate_personal_workflow_documents(
    *, main_id: str, user_id: str, nodes: list[dict[str, Any]],
) -> None:
    """Check bound personal documents when a workflow draft is saved."""
    checked: set[str] = set()
    for node in nodes:
        if str(node.get("type") or "") != "read_material":
            continue
        config = node.get("businessConfig") if isinstance(node.get("businessConfig"), dict) else {}
        if config.get("sourceType") != "knowledge_document" or config.get("knowledgeScope") != "personal":
            continue
        resource_id = str(config.get("knowledgeSourceId") or "").strip()
        if not resource_id:
            raise ValueError("knowledge_source_id_required")
        if resource_id not in checked:
            await selectable_document(main_id=main_id, user_id=user_id, resource_id=resource_id)
            checked.add(resource_id)
