from __future__ import annotations

import datetime
import uuid
from pathlib import Path
from typing import Any

from app.core.db import get_db
from app.core.tenant import resolve_main_id
from app.services.skill_sharing.member_directory import SkillShareMemberDirectory

from .access import GRANT_COLLECTION, RESOURCE_COLLECTION, PersonalKnowledgeAccessService
from .feedback_summary import personal_knowledge_feedback_summary_service
from .share_summary import attach_share_summary


DIRECTORY_COLLECTION = "personal_knowledge_directories"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _time_sort_value(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


class PersonalKnowledgeService:
    def __init__(self) -> None:
        self.access = PersonalKnowledgeAccessService()
        self.members = SkillShareMemberDirectory()

    async def create_resource(
        self, *, main_id: str, owner_user_id: str, filename: str,
        directory_id: str = "", name: str = "", description: str = "", tags: list[str] | None = None,
    ) -> dict[str, Any]:
        tenant_id = resolve_main_id(main_id)
        await self.require_directory(main_id=tenant_id, owner_user_id=owner_user_id, directory_id=directory_id)
        resource_id = uuid.uuid4().hex
        now = _now()
        row = {
            "_id": resource_id, "main_id": tenant_id, "owner_user_id": str(owner_user_id),
            "directory_id": str(directory_id or ""),
            "name": str(name or Path(filename).stem or filename or "未命名知识").strip()[:180],
            "description": str(description or "").strip()[:2000],
            "tags": list(dict.fromkeys(str(item).strip()[:40] for item in list(tags or []) if str(item).strip()))[:20],
            "share_policy": "per_grant", "active_document_id": "", "processing_document_id": "",
            "status": "uploading", "error": "", "created_at": now, "updated_at": now, "deleted_at": None,
        }
        await get_db()[RESOURCE_COLLECTION].insert_one(row)
        return row

    async def mark_upload(self, *, resource_id: str, document: dict[str, Any] | None = None, error: str = "") -> None:
        values: dict[str, Any] = {"updated_at": _now()}
        if error:
            values.update({"status": "failed", "error": error[:2000]})
        else:
            document = document or {}
            values.update({
                "status": str(document.get("status") or "pending_parse"), "error": "",
                "processing_document_id": str(document.get("id") or document.get("_id") or ""),
            })
        await get_db()[RESOURCE_COLLECTION].update_one({"_id": resource_id}, {"$set": values})

    async def list_resources(
        self, *, main_id: str, user_id: str, view: str, directory_id: str = "",
        keyword: str = "", page: int = 1, page_size: int = 12,
    ) -> dict[str, Any]:
        db, tenant_id = get_db(), resolve_main_id(main_id)
        offset = (page - 1) * page_size
        feedback = await personal_knowledge_feedback_summary_service.unread_by_resource(
            main_id=tenant_id, user_id=user_id,
        )
        if view == "shared":
            grants = await db[GRANT_COLLECTION].find({
                "main_id": tenant_id, "resource_type": "personal_knowledge",
                "recipient_user_id": str(user_id), "status": {"$in": ["active", "revoked"]},
            }).sort("updated_at", -1).to_list(length=1000)
            resource_ids = [str(item.get("resource_id") or "") for item in grants]
            resources = await db[RESOURCE_COLLECTION].find({
                "_id": {"$in": resource_ids}, "main_id": tenant_id,
            }).to_list(length=len(resource_ids)) if resource_ids else []
            by_id = {str(item.get("_id") or ""): item for item in resources}
            views = [self.resource_view(by_id.get(str(grant.get("resource_id") or "")), grant=grant) for grant in grants if by_id.get(str(grant.get("resource_id") or ""))]
            needle = keyword.strip().casefold()
            if needle:
                views = [item for item in views if needle in " ".join([
                    str(item.get("name") or ""), str(item.get("description") or ""),
                    *[str(tag) for tag in item.get("tags") or []],
                ]).casefold()]
            views.sort(key=lambda item: (
                int(not bool(item.get("seen"))),
                int((feedback.get(str(item.get("id") or "")) or {}).get("count") or 0) > 0,
                _time_sort_value(
                    (feedback.get(str(item.get("id") or "")) or {}).get("latest")
                    or item.get("sharedAt")
                    or item.get("updatedAt")
                ),
            ), reverse=True)
            total = len(views)
            views = views[offset:offset + page_size]
            await self._attach_people(tenant_id, views)
            personal_knowledge_feedback_summary_service.attach(views, feedback)
            return {"items": views, "total": total, "page": page, "pageSize": page_size}
        query: dict[str, Any] = {"main_id": tenant_id, "owner_user_id": str(user_id), "deleted_at": None}
        if directory_id != "all":
            query["directory_id"] = str(directory_id or "")
        if keyword.strip():
            query["$or"] = [
                {"name": {"$regex": keyword.strip(), "$options": "i"}},
                {"description": {"$regex": keyword.strip(), "$options": "i"}},
                {"tags": {"$regex": keyword.strip(), "$options": "i"}},
            ]
        total = await db[RESOURCE_COLLECTION].count_documents(query)
        priority_ids = [
            resource_id for resource_id, _ in sorted(
                feedback.items(), key=lambda pair: _time_sort_value(pair[1].get("latest")), reverse=True,
            )
        ]
        priority_rows = await db[RESOURCE_COLLECTION].find({
            **query, "_id": {"$in": priority_ids},
        }).to_list(length=len(priority_ids)) if priority_ids else []
        priority_by_id = {str(row.get("_id") or ""): row for row in priority_rows}
        priority_rows = [priority_by_id[item] for item in priority_ids if item in priority_by_id]
        page_rows = priority_rows[offset:offset + page_size]
        remaining = page_size - len(page_rows)
        rows = list(page_rows)
        if remaining > 0:
            regular_offset = max(0, offset - len(priority_rows))
            regular_query = {**query, "_id": {"$nin": list(priority_by_id)}} if priority_by_id else query
            regular_rows = await db[RESOURCE_COLLECTION].find(regular_query).sort("updated_at", -1).skip(regular_offset).limit(remaining).to_list(length=remaining)
            rows.extend(regular_rows)
        views = [self.resource_view(row) for row in rows]
        await self._attach_people(tenant_id, views)
        personal_knowledge_feedback_summary_service.attach(views, feedback)
        await attach_share_summary(db=db, main_id=tenant_id, items=views)
        return {"items": views, "total": total, "page": page, "pageSize": page_size}

    async def _attach_people(self, main_id: str, items: list[dict[str, Any]]) -> None:
        from app.services.skill_sharing.member_directory import member_id_candidates
        ids = list({str(value) for item in items for value in (item.get("ownerUserId"), item.get("grantedByUserId")) if value})
        if not ids:
            return
        rows = await get_db().end_users.find({
            "_id": {"$in": member_id_candidates(ids)}, "main_id": main_id,
        }, {"name": 1, "display_name": 1, "login_name": 1, "email": 1}).to_list(length=len(ids))
        people = {str(row.get("_id") or ""): self.members.member_view(row) for row in rows}
        for item in items:
            item["owner"] = people.get(str(item.get("ownerUserId") or ""), {})
            item["grantedBy"] = people.get(str(item.get("grantedByUserId") or ""), {})

    async def share(self, *, main_id: str, user_id: str, resource_id: str, recipients: list[dict[str, Any]]) -> list[dict[str, Any]]:
        access = await self.access.require_share(main_id=main_id, user_id=user_id, resource_id=resource_id)
        ids = [str(item.get("userId") or "") for item in recipients]
        members = await self.members.require_members(main_id=main_id, requester_user_id=user_id, user_ids=ids)
        allowed = {str(item.get("userId") or ""): bool(item.get("canReshare")) for item in recipients}
        now, db = _now(), get_db()
        output = []
        for member in members:
            recipient_id = str(member.get("_id") or "")
            if recipient_id == str(access.resource.get("owner_user_id") or ""):
                continue
            query = {"main_id": resolve_main_id(main_id), "resource_type": "personal_knowledge", "resource_id": resource_id, "recipient_user_id": recipient_id}
            values = {"granted_by_user_id": str(user_id), "can_reshare": bool(allowed.get(recipient_id)), "status": "active", "revoked_at": None, "updated_at": now}
            current = await db[GRANT_COLLECTION].find_one(query)
            if current:
                if str(current.get("status") or "") == "active" and not access.is_owner:
                    values = {
                        "granted_by_user_id": str(current.get("granted_by_user_id") or ""),
                        "can_reshare": bool(current.get("can_reshare")),
                        "status": "active", "revoked_at": None, "updated_at": current.get("updated_at") or now,
                    }
                else:
                    if str(current.get("status") or "") != "active":
                        values["seen_at"] = None
                    await db[GRANT_COLLECTION].update_one({"_id": current["_id"]}, {"$set": values})
            else:
                await db[GRANT_COLLECTION].insert_one({"_id": uuid.uuid4().hex, **query, **values, "seen_at": None, "created_at": now})
            output.append({**self.members.member_view(member), "canReshare": values["can_reshare"]})
        return output

    async def revoke(self, *, main_id: str, user_id: str, resource_id: str, recipient_user_id: str, cascade: bool = False) -> None:
        access = await self.access.require_view(main_id=main_id, user_id=user_id, resource_id=resource_id)
        db, tenant_id = get_db(), resolve_main_id(main_id)
        grant = await db[GRANT_COLLECTION].find_one({
            "main_id": tenant_id, "resource_type": "personal_knowledge", "resource_id": resource_id,
            "recipient_user_id": str(recipient_user_id), "status": "active",
        })
        if grant is None:
            raise LookupError("knowledge_grant_not_found")
        if not access.is_owner and str(grant.get("granted_by_user_id") or "") != str(user_id):
            raise PermissionError("knowledge_grant_revoke_forbidden")
        now = _now()
        await db[GRANT_COLLECTION].update_one({"_id": grant["_id"]}, {"$set": {"status": "revoked", "revoked_by_user_id": str(user_id), "revoked_at": now, "seen_at": None, "updated_at": now}})
        if cascade and access.is_owner:
            descendants: set[str] = set()
            frontier = {str(recipient_user_id)}
            while frontier:
                rows = await db[GRANT_COLLECTION].find({
                    "main_id": tenant_id, "resource_type": "personal_knowledge", "resource_id": resource_id,
                    "granted_by_user_id": {"$in": list(frontier)}, "status": "active",
                }).to_list(length=5000)
                next_frontier = {str(row.get("recipient_user_id") or "") for row in rows} - descendants - {""}
                descendants.update(next_frontier)
                frontier = next_frontier
            if descendants:
                await db[GRANT_COLLECTION].update_many({
                    "main_id": tenant_id, "resource_type": "personal_knowledge", "resource_id": resource_id,
                    "recipient_user_id": {"$in": list(descendants)}, "status": "active",
                }, {"$set": {"status": "revoked", "revoked_by_user_id": str(user_id), "revoked_at": now, "seen_at": None, "updated_at": now}})

    async def require_directory(self, *, main_id: str, owner_user_id: str, directory_id: str) -> None:
        if not directory_id:
            return
        row = await get_db()[DIRECTORY_COLLECTION].find_one({
            "_id": str(directory_id), "main_id": resolve_main_id(main_id),
            "owner_user_id": str(owner_user_id), "deleted_at": None,
        })
        if row is None:
            raise LookupError("knowledge_directory_not_found")

    @staticmethod
    def resource_view(row: dict[str, Any] | None, *, grant: dict[str, Any] | None = None) -> dict[str, Any]:
        row = row or {}
        grant = grant or {}
        def iso(value: Any) -> str:
            return value.isoformat() if isinstance(value, datetime.datetime) else ""
        deleted = row.get("deleted_at") is not None
        grant_status = str(grant.get("status") or "")
        inactive = bool(grant) and (deleted or grant_status != "active")
        return {
            "id": str(row.get("_id") or ""), "ownerUserId": str(row.get("owner_user_id") or ""),
            "directoryId": str(row.get("directory_id") or ""), "name": str(row.get("name") or ""),
            "description": str(row.get("description") or ""), "tags": list(row.get("tags") or []),
            "status": str(row.get("status") or ""), "error": str(row.get("error") or ""),
            "activeDocumentId": "" if inactive else str(row.get("active_document_id") or row.get("processing_document_id") or ""),
            "canReshare": False if inactive else bool(grant.get("can_reshare")),
            "accessStatus": "deleted" if deleted and grant else str(grant.get("status") or "owner"),
            "grantedByUserId": str(grant.get("granted_by_user_id") or ""), "seen": bool(grant.get("seen_at")),
            "sharedAt": iso(grant.get("updated_at") or grant.get("created_at")),
            "createdAt": iso(row.get("created_at")), "updatedAt": iso(row.get("updated_at")),
            "deleted": deleted, "deletedAt": iso(row.get("deleted_at")),
        }
