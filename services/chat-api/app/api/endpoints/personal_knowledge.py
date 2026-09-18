from __future__ import annotations

import datetime
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.api.principal import ApiPrincipal, require_end_user_principal
from app.core.db import get_db
from app.services.personal_knowledge.access import GRANT_COLLECTION
from app.services.personal_knowledge.lifecycle_client import knowledge_lifecycle_client
from app.services.personal_knowledge.inactive_access import PersonalKnowledgeInactiveAccessService
from app.services.personal_knowledge.service import DIRECTORY_COLLECTION, PersonalKnowledgeService


router = APIRouter(dependencies=[Depends(require_end_user_principal)])
service = PersonalKnowledgeService()
inactive_access_service = PersonalKnowledgeInactiveAccessService()


def _response(data: Any) -> dict[str, Any]:
    return {"code": 0, "message": "success", "data": data}


def _raise(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise exc


class DirectoryPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: str = Field(default="", alias="parentId")


class ResourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = None
    directory_id: str | None = Field(default=None, alias="directoryId")


class ShareRecipient(BaseModel):
    user_id: str = Field(alias="userId")
    can_reshare: bool = Field(default=False, alias="canReshare")


class SharePayload(BaseModel):
    recipients: list[ShareRecipient] = Field(min_length=1, max_length=100)


class GrantPatch(BaseModel):
    can_reshare: bool = Field(alias="canReshare")


class AskPayload(BaseModel):
    query: str = Field(min_length=1, max_length=8000)


@router.get("/personal-knowledge/directories")
async def list_directories(principal: ApiPrincipal = Depends(require_end_user_principal)):
    rows = await get_db()[DIRECTORY_COLLECTION].find({
        "main_id": principal.main_id, "owner_user_id": principal.user_id, "deleted_at": None,
    }).sort("created_at", 1).to_list(length=5000)
    counts_pipeline = [
        {"$match": {"main_id": principal.main_id, "owner_user_id": principal.user_id, "deleted_at": None}},
        {"$group": {"_id": "$directory_id", "count": {"$sum": 1}}},
    ]
    counts = {str(item.get("_id") or ""): int(item.get("count") or 0) async for item in get_db().knowledge_resources.aggregate(counts_pipeline)}
    nodes = {str(row["_id"]): {"id": str(row["_id"]), "name": str(row.get("name") or ""), "parentId": str(row.get("parent_id") or ""), "count": counts.get(str(row["_id"]), 0), "children": []} for row in rows}
    roots = []
    for node in nodes.values():
        parent = nodes.get(node["parentId"])
        (parent["children"] if parent else roots).append(node)
    return _response({"items": roots, "rootCount": counts.get("", 0)})


@router.post("/personal-knowledge/directories")
async def create_directory(payload: DirectoryPayload, principal: ApiPrincipal = Depends(require_end_user_principal)):
    await service.require_directory(main_id=principal.main_id, owner_user_id=principal.user_id, directory_id=payload.parent_id)
    query = {"main_id": principal.main_id, "owner_user_id": principal.user_id, "parent_id": payload.parent_id, "name": payload.name.strip(), "deleted_at": None}
    if await get_db()[DIRECTORY_COLLECTION].find_one(query):
        raise HTTPException(status_code=409, detail="knowledge_directory_duplicate")
    now, row_id = datetime.datetime.now(datetime.timezone.utc), uuid.uuid4().hex
    await get_db()[DIRECTORY_COLLECTION].insert_one({"_id": row_id, **query, "created_at": now, "updated_at": now})
    return _response({"id": row_id, "name": payload.name.strip(), "parentId": payload.parent_id})


@router.patch("/personal-knowledge/directories/{directory_id}")
async def update_directory(directory_id: str, payload: DirectoryPayload, principal: ApiPrincipal = Depends(require_end_user_principal)):
    await service.require_directory(main_id=principal.main_id, owner_user_id=principal.user_id, directory_id=directory_id)
    await service.require_directory(main_id=principal.main_id, owner_user_id=principal.user_id, directory_id=payload.parent_id)
    if payload.parent_id == directory_id:
        raise HTTPException(status_code=400, detail="knowledge_directory_cycle")
    # Parent-only traversal is cheap for personal trees and avoids maintaining duplicated path state.
    cursor, visited = payload.parent_id, {directory_id}
    while cursor:
        if cursor in visited:
            raise HTTPException(status_code=400, detail="knowledge_directory_cycle")
        visited.add(cursor)
        parent = await get_db()[DIRECTORY_COLLECTION].find_one({"_id": cursor, "main_id": principal.main_id, "owner_user_id": principal.user_id}, {"parent_id": 1})
        cursor = str((parent or {}).get("parent_id") or "")
    duplicate = await get_db()[DIRECTORY_COLLECTION].find_one({
        "_id": {"$ne": directory_id}, "main_id": principal.main_id,
        "owner_user_id": principal.user_id, "parent_id": payload.parent_id,
        "name": payload.name.strip(), "deleted_at": None,
    })
    if duplicate:
        raise HTTPException(status_code=409, detail="knowledge_directory_duplicate")
    await get_db()[DIRECTORY_COLLECTION].update_one({"_id": directory_id}, {"$set": {"name": payload.name.strip(), "parent_id": payload.parent_id, "updated_at": datetime.datetime.now(datetime.timezone.utc)}})
    return _response({"id": directory_id})


@router.delete("/personal-knowledge/directories/{directory_id}")
async def delete_directory(directory_id: str, principal: ApiPrincipal = Depends(require_end_user_principal)):
    await service.require_directory(main_id=principal.main_id, owner_user_id=principal.user_id, directory_id=directory_id)
    if await get_db()[DIRECTORY_COLLECTION].find_one({"main_id": principal.main_id, "owner_user_id": principal.user_id, "parent_id": directory_id, "deleted_at": None}):
        raise HTTPException(status_code=409, detail="knowledge_directory_not_empty")
    if await get_db().knowledge_resources.find_one({"main_id": principal.main_id, "owner_user_id": principal.user_id, "directory_id": directory_id, "deleted_at": None}):
        raise HTTPException(status_code=409, detail="knowledge_directory_not_empty")
    await get_db()[DIRECTORY_COLLECTION].update_one({"_id": directory_id}, {"$set": {"deleted_at": datetime.datetime.now(datetime.timezone.utc)}})
    return _response({"id": directory_id})


@router.get("/personal-knowledge")
async def list_resources(
    view: str = Query(default="mine", pattern="^(mine|shared)$"), directoryId: str = "", keyword: str = "",
    page: int = Query(default=1, ge=1), pageSize: int = Query(default=12, ge=1, le=100),
    principal: ApiPrincipal = Depends(require_end_user_principal),
):
    result = await service.list_resources(
        main_id=principal.main_id, user_id=principal.user_id, view=view,
        directory_id=directoryId, keyword=keyword, page=page, page_size=pageSize,
    )
    return _response(result)


@router.post("/personal-knowledge")
async def upload_resources(files: list[UploadFile] = File(...), directoryId: str = Form(default=""), tags: str = Form(default=""), principal: ApiPrincipal = Depends(require_end_user_principal)):
    if len(files) > 50:
        raise HTTPException(status_code=400, detail="knowledge_too_many_files")
    tag_list = [item.strip() for item in tags.replace("，", ",").split(",") if item.strip()]
    results = []
    for file in files:
        resource = await service.create_resource(main_id=principal.main_id, owner_user_id=principal.user_id, filename=file.filename or "document", directory_id=directoryId, tags=tag_list)
        try:
            document = await knowledge_lifecycle_client.upload(main_id=principal.main_id, owner_user_id=principal.user_id, resource_id=str(resource["_id"]), file=file, name=str(resource["name"]), description="", tags=tag_list)
            results.append({**service.resource_view(resource), "status": str(document.get("status") or "pending_parse"), "activeDocumentId": str(document.get("id") or "")})
        except Exception as exc:
            await service.mark_upload(resource_id=str(resource["_id"]), error=str(exc))
            results.append({**service.resource_view(resource), "status": "failed", "error": str(exc)[:500]})
        finally:
            await file.close()
    return _response({"items": results})


@router.get("/personal-knowledge/{resource_id}")
async def get_resource(resource_id: str, principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        access = await service.access.require_view(main_id=principal.main_id, user_id=principal.user_id, resource_id=resource_id)
    except Exception as exc:
        inactive = await inactive_access_service.resolve(
            main_id=principal.main_id, user_id=principal.user_id, resource_id=resource_id,
        )
        if inactive is None:
            _raise(exc)
        await inactive_access_service.acknowledge(access=inactive, user_id=principal.user_id)
        inactive_grant = {**inactive.grant, "seen_at": datetime.datetime.now(datetime.timezone.utc)}
        return _response({
            **service.resource_view(inactive.resource, grant=inactive_grant),
            "isOwner": False, "canShare": False,
        })
    if access.grant:
        seen_at = datetime.datetime.now(datetime.timezone.utc)
        await get_db()[GRANT_COLLECTION].update_one({"_id": access.grant["_id"]}, {"$set": {"seen_at": seen_at}})
        access_grant = {**access.grant, "seen_at": seen_at}
    else:
        access_grant = None
    return _response({**service.resource_view(access.resource, grant=access_grant), "isOwner": access.is_owner, "canShare": access.can_share})


@router.patch("/personal-knowledge/{resource_id}")
async def update_resource(resource_id: str, payload: ResourcePatch, principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        await service.access.require_owner(main_id=principal.main_id, user_id=principal.user_id, resource_id=resource_id)
        if payload.directory_id is not None:
            await service.require_directory(main_id=principal.main_id, owner_user_id=principal.user_id, directory_id=payload.directory_id)
    except Exception as exc:
        _raise(exc)
    values = {key: value for key, value in {
        "name": payload.name.strip() if payload.name else None, "description": payload.description,
        "tags": payload.tags, "directory_id": payload.directory_id,
    }.items() if value is not None}
    values["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
    await get_db().knowledge_resources.update_one({"_id": resource_id}, {"$set": values})
    row = await get_db().knowledge_resources.find_one({"_id": resource_id})
    return _response(service.resource_view(row))


@router.delete("/personal-knowledge/{resource_id}")
async def delete_resource(resource_id: str, principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        await service.access.require_owner(main_id=principal.main_id, user_id=principal.user_id, resource_id=resource_id)
        await knowledge_lifecycle_client.action(action="delete", main_id=principal.main_id, owner_user_id=principal.user_id, resource_id=resource_id)
    except Exception as exc:
        _raise(exc)
    now = datetime.datetime.now(datetime.timezone.utc)
    await get_db().knowledge_resources.update_one({"_id": resource_id}, {"$set": {"status": "deleted", "deleted_at": now, "updated_at": now}})
    await get_db()[GRANT_COLLECTION].update_many({"main_id": principal.main_id, "resource_type": "personal_knowledge", "resource_id": resource_id, "status": "active"}, {"$set": {"status": "revoked", "revoke_reason": "source_deleted", "revoked_by_user_id": principal.user_id, "revoked_at": now, "seen_at": None, "updated_at": now}})
    return _response({"id": resource_id})


@router.delete("/personal-knowledge/{resource_id}/shared-record")
async def dismiss_deleted_shared_record(resource_id: str, principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        await inactive_access_service.dismiss_deleted(
            main_id=principal.main_id, user_id=principal.user_id, resource_id=resource_id,
        )
    except Exception as exc:
        _raise(exc)
    return _response({"id": resource_id})


@router.post("/personal-knowledge/{resource_id}/ask")
async def ask_resource(resource_id: str, payload: AskPayload, principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        await service.access.require_view(main_id=principal.main_id, user_id=principal.user_id, resource_id=resource_id)
        from app.services.rag_service.internal_knowledge_qa_service import internal_knowledge_qa_service
        result = await internal_knowledge_qa_service.answer(
            query=payload.query, user_id=principal.user_id, main_id=principal.main_id,
            knowledge_ids=[resource_id], top_k=8,
        )
    except Exception as exc:
        _raise(exc)
    return _response(result)


@router.post("/personal-knowledge/{resource_id}/relearn")
async def relearn(resource_id: str, principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        await service.access.require_owner(main_id=principal.main_id, user_id=principal.user_id, resource_id=resource_id)
        result = await knowledge_lifecycle_client.action(action="relearn", main_id=principal.main_id, owner_user_id=principal.user_id, resource_id=resource_id)
    except Exception as exc:
        _raise(exc)
    await get_db().knowledge_resources.update_one(
        {"_id": resource_id}, {"$set": {"status": "pending_parse", "error": "", "updated_at": datetime.datetime.now(datetime.timezone.utc)}},
    )
    return _response(result)


@router.post("/personal-knowledge/{resource_id}/replace")
async def replace_resource(resource_id: str, file: UploadFile = File(...), principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        access = await service.access.require_owner(main_id=principal.main_id, user_id=principal.user_id, resource_id=resource_id)
        document = await knowledge_lifecycle_client.upload(
            main_id=principal.main_id, owner_user_id=principal.user_id, resource_id=resource_id,
            file=file, name=str(access.resource.get("name") or ""),
            description=str(access.resource.get("description") or ""), tags=list(access.resource.get("tags") or []),
            replace_existing=True,
        )
    except Exception as exc:
        _raise(exc)
    finally:
        await file.close()
    return _response(document)


@router.get("/personal-knowledge/{resource_id}/grants")
async def list_grants(resource_id: str, principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        await service.access.require_owner(main_id=principal.main_id, user_id=principal.user_id, resource_id=resource_id)
    except Exception as exc:
        _raise(exc)
    rows = await get_db()[GRANT_COLLECTION].find({"main_id": principal.main_id, "resource_type": "personal_knowledge", "resource_id": resource_id}).sort("created_at", -1).to_list(length=5000)
    from app.services.skill_sharing.member_directory import member_id_candidates
    ids = list({str(value) for row in rows for value in (row.get("recipient_user_id"), row.get("granted_by_user_id")) if value})
    members = await get_db().end_users.find({
        "_id": {"$in": member_id_candidates(ids)}, "main_id": principal.main_id,
    }, {"name": 1, "display_name": 1, "login_name": 1, "email": 1}).to_list(length=len(ids)) if ids else []
    identities = {str(row.get("_id") or ""): service.members.member_view(row) for row in members}
    return _response({"items": [{
        "userId": str(row.get("recipient_user_id") or ""),
        "user": identities.get(str(row.get("recipient_user_id") or ""), {}),
        "grantedByUserId": str(row.get("granted_by_user_id") or ""),
        "grantedBy": identities.get(str(row.get("granted_by_user_id") or ""), {}),
        "canReshare": bool(row.get("can_reshare")), "status": str(row.get("status") or ""),
    } for row in rows]})


@router.post("/personal-knowledge/{resource_id}/grants")
async def share_resource(resource_id: str, payload: SharePayload, principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        items = await service.share(main_id=principal.main_id, user_id=principal.user_id, resource_id=resource_id, recipients=[item.model_dump(by_alias=True) for item in payload.recipients])
    except Exception as exc:
        _raise(exc)
    return _response({"items": items})


@router.delete("/personal-knowledge/{resource_id}/grants/{recipient_user_id}")
async def revoke_resource(resource_id: str, recipient_user_id: str, cascade: bool = False, principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        await service.revoke(main_id=principal.main_id, user_id=principal.user_id, resource_id=resource_id, recipient_user_id=recipient_user_id, cascade=cascade)
    except Exception as exc:
        _raise(exc)
    return _response({"userId": recipient_user_id})


@router.patch("/personal-knowledge/{resource_id}/grants/{recipient_user_id}")
async def update_grant(resource_id: str, recipient_user_id: str, payload: GrantPatch, principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        await service.access.require_owner(main_id=principal.main_id, user_id=principal.user_id, resource_id=resource_id)
    except Exception as exc:
        _raise(exc)
    result = await get_db()[GRANT_COLLECTION].update_one({
        "main_id": principal.main_id, "resource_type": "personal_knowledge", "resource_id": resource_id,
        "recipient_user_id": recipient_user_id, "status": "active",
    }, {"$set": {"can_reshare": payload.can_reshare, "updated_at": datetime.datetime.now(datetime.timezone.utc)}})
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="knowledge_grant_not_found")
    return _response({"userId": recipient_user_id, "canReshare": payload.can_reshare})


@router.get("/personal-knowledge-counts")
async def counts(principal: ApiPrincipal = Depends(require_end_user_principal)):
    db = get_db()
    grant_query = {
        "main_id": principal.main_id,
        "resource_type": "personal_knowledge",
        "recipient_user_id": principal.user_id,
        "status": {"$in": ["active", "revoked"]},
    }
    unseen = await db[GRANT_COLLECTION].count_documents({**grant_query, "seen_at": None})
    grants = await db[GRANT_COLLECTION].find(grant_query, {"resource_id": 1}).to_list(length=5000)
    shared_resource_ids = list({str(row.get("resource_id") or "") for row in grants if row.get("resource_id")})
    from app.services.resource_feedback import ResourceFeedbackService
    feedback = await ResourceFeedbackService().unread_count(
        main_id=principal.main_id, user_id=principal.user_id, resource_types=["personal_knowledge"],
    )
    shared_feedback = await db.resource_feedback_notifications.count_documents({
        "main_id": principal.main_id,
        "resource_type": "personal_knowledge",
        "recipient_user_id": principal.user_id,
        "resource_id": {"$in": shared_resource_ids},
        "status": "unread",
    }) if shared_resource_ids else 0
    return _response({
        "unreadCount": unseen + feedback,
        "shareCount": unseen + shared_feedback,
        "feedbackCount": feedback,
    })
