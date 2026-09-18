from __future__ import annotations

from datetime import datetime
from typing import Any


def is_personal_document(document: dict[str, Any]) -> bool:
    return str(document.get("scope") or "") == "personal" and bool(document.get("resource_id"))


async def update_current_resource(
    db: Any,
    document: dict[str, Any],
    values: dict[str, Any],
) -> bool:
    resource, guard = await _current_resource(db, document)
    if resource is None:
        return False
    result = await db.knowledge_resources.update_one(guard, {"$set": values})
    return bool(result.matched_count)


async def activate_indexed_document(
    db: Any,
    document: dict[str, Any],
    *,
    updated_at: datetime,
) -> tuple[bool, str]:
    resource, guard = await _current_resource(db, document)
    if resource is None:
        return False, ""
    document_id = str(document.get("_id") or "")
    previous_document_id = str(resource.get("active_document_id") or "")
    result = await db.knowledge_resources.update_one(
        guard,
        {"$set": {
            "status": "indexed",
            "error": "",
            "active_document_id": document_id,
            "processing_document_id": "",
            "updated_at": updated_at,
        }},
    )
    return bool(result.matched_count), previous_document_id


async def _current_resource(db: Any, document: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not is_personal_document(document):
        return None, {}
    main_id = str(document.get("main_id") or "default")
    resource_id = str(document.get("resource_id") or "")
    resource = await db.knowledge_resources.find_one({
        "_id": resource_id,
        "main_id": main_id,
        "deleted_at": None,
    })
    if resource is None:
        return None, {}
    document_id = str(document.get("_id") or "")
    processing_id = str(resource.get("processing_document_id") or "")
    active_id = str(resource.get("active_document_id") or "")
    is_current = processing_id == document_id or (
        not processing_id and (active_id == document_id or not active_id)
    )
    if not is_current:
        return None, {}
    guard = {
        "_id": resource_id,
        "main_id": main_id,
        "deleted_at": None,
        "processing_document_id": resource.get("processing_document_id", ""),
        "active_document_id": resource.get("active_document_id", ""),
    }
    return resource, guard
