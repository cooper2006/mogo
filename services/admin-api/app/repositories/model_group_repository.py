"""Tenant-owned connections shared by a group of model instances."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from app.core.db import get_db
from app.repositories.model_repository import encrypt_secret, mask_secret


COLLECTION = "admin_model_groups"
INSTANCE_COLLECTION = "admin_model_instances"


async def ensure_indexes() -> None:
    db = get_db()
    await db[COLLECTION].create_index([("tenant_id", 1), ("name", 1)], unique=True)
    await db[INSTANCE_COLLECTION].create_index([("tenant_id", 1), ("group_id", 1)])


async def list_groups(tenant_id: str) -> list[dict[str, Any]]:
    return await get_db()[COLLECTION].find({"tenant_id": tenant_id}).sort("created_at", 1).to_list(length=500)


async def find_group(group_id: str, tenant_id: str) -> dict[str, Any] | None:
    if not ObjectId.is_valid(group_id):
        return None
    return await get_db()[COLLECTION].find_one({"_id": ObjectId(group_id), "tenant_id": tenant_id})


async def create_group(tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    doc = {
        "tenant_id": tenant_id,
        "name": payload["name"],
        "provider_id": ObjectId(payload["provider_id"]),
        "base_url": payload["base_url"],
        "api_version": payload.get("api_version", ""),
        "api_key_encrypted": encrypt_secret(payload["api_key"]),
        "api_key_masked": mask_secret(payload["api_key"]),
        "status": payload.get("status", "active"),
        "created_at": now,
        "updated_at": now,
    }
    result = await get_db()[COLLECTION].insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def update_group(group_id: str, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    update = {
        "name": payload["name"],
        "provider_id": ObjectId(payload["provider_id"]),
        "base_url": payload["base_url"],
        "api_version": payload.get("api_version", ""),
        "status": payload.get("status", "active"),
        "updated_at": datetime.now(timezone.utc),
    }
    if payload.get("api_key"):
        update["api_key_encrypted"] = encrypt_secret(payload["api_key"])
        update["api_key_masked"] = mask_secret(payload["api_key"])
    result = await get_db()[COLLECTION].update_one(
        {"_id": ObjectId(group_id), "tenant_id": tenant_id}, {"$set": update}
    )
    return await find_group(group_id, tenant_id) if result.matched_count else None


async def delete_empty_group(group_id: str, tenant_id: str) -> bool:
    db = get_db()
    if await db[INSTANCE_COLLECTION].find_one({"tenant_id": tenant_id, "group_id": group_id}, {"_id": 1}):
        raise ValueError("model_group_has_models")
    result = await db[COLLECTION].delete_one({"_id": ObjectId(group_id), "tenant_id": tenant_id})
    return result.deleted_count > 0
