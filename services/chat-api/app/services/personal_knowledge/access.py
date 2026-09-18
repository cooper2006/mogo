from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.db import get_db
from app.core.tenant import resolve_main_id


RESOURCE_COLLECTION = "knowledge_resources"
GRANT_COLLECTION = "resource_grants"


@dataclass(frozen=True)
class KnowledgeAccess:
    resource: dict[str, Any]
    grant: dict[str, Any] | None
    is_owner: bool
    can_view: bool
    can_share: bool
    can_manage: bool


class PersonalKnowledgeAccessService:
    async def resolve(self, *, main_id: str, user_id: str, resource_id: str) -> KnowledgeAccess | None:
        tenant_id = resolve_main_id(main_id)
        resource = await get_db()[RESOURCE_COLLECTION].find_one({
            "_id": str(resource_id), "main_id": tenant_id, "deleted_at": None,
        })
        if resource is None:
            return None
        owner = str(resource.get("owner_user_id") or "") == str(user_id)
        grant = None
        if not owner:
            grant = await get_db()[GRANT_COLLECTION].find_one({
                "main_id": tenant_id,
                "resource_type": "personal_knowledge",
                "resource_id": str(resource_id),
                "recipient_user_id": str(user_id),
                "status": "active",
            })
        can_view = owner or grant is not None
        return KnowledgeAccess(
            resource=resource,
            grant=grant,
            is_owner=owner,
            can_view=can_view,
            can_share=owner or bool((grant or {}).get("can_reshare")),
            can_manage=owner,
        )

    async def require_view(self, *, main_id: str, user_id: str, resource_id: str) -> KnowledgeAccess:
        access = await self.resolve(main_id=main_id, user_id=user_id, resource_id=resource_id)
        if access is None:
            raise LookupError("knowledge_not_found")
        if not access.can_view:
            raise PermissionError("knowledge_forbidden")
        return access

    async def require_owner(self, *, main_id: str, user_id: str, resource_id: str) -> KnowledgeAccess:
        access = await self.require_view(main_id=main_id, user_id=user_id, resource_id=resource_id)
        if not access.is_owner:
            raise PermissionError("knowledge_owner_required")
        return access

    async def require_share(self, *, main_id: str, user_id: str, resource_id: str) -> KnowledgeAccess:
        access = await self.require_view(main_id=main_id, user_id=user_id, resource_id=resource_id)
        if not access.can_share:
            raise PermissionError("knowledge_reshare_forbidden")
        return access

    async def resource_for_document(self, *, main_id: str, document_id: str) -> dict[str, Any] | None:
        doc = await get_db().knowledge_documents.find_one({
            "_id": str(document_id), "main_id": resolve_main_id(main_id), "deleted_at": None,
        }, {"resource_id": 1, "scope": 1})
        if not doc or str(doc.get("scope") or "organization") != "personal":
            return None
        return await get_db()[RESOURCE_COLLECTION].find_one({
            "_id": str(doc.get("resource_id") or ""),
            "main_id": resolve_main_id(main_id),
            "deleted_at": None,
        })
