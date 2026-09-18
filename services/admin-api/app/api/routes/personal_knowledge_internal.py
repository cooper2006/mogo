from __future__ import annotations

import hmac

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.routes.knowledge_documents import delete_document, retry_document_parse, retry_document_preview, upload_document
from app.core.config import settings
from app.core.db import get_db


router = APIRouter()


def _require_service(token: str) -> None:
    expected = str(settings.backend_service_token or "")
    if not token or not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="invalid_service_token")


def _actor(main_id: str, owner_user_id: str) -> dict[str, str]:
    return {"main_id": main_id, "username": owner_user_id, "display_name": owner_user_id}


@router.post("/documents")
async def upload_personal_document(
    file: UploadFile = File(...), mainId: str = Form(...), ownerUserId: str = Form(...),
    resourceId: str = Form(...), name: str = Form(default=""), description: str = Form(default=""),
    tags: str = Form(default=""), replaceExisting: bool = Form(default=False),
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
):
    _require_service(service_token)
    result = await upload_document(
        file=file, name=name, description=description, directoryId=resourceId,
        knowledgeBaseId=resourceId, tags=tags, replaceExisting=replaceExisting,
        documentScope="personal", ownerUserId=ownerUserId, resourceId=resourceId,
        current_user=_actor(mainId, ownerUserId),
    )
    return {"code": 0, "message": "success", "data": result}


class ActionPayload(BaseModel):
    mainId: str
    ownerUserId: str


@router.post("/{resource_id}/relearn")
async def relearn_personal_document(resource_id: str, payload: ActionPayload, service_token: str = Header(default="", alias="X-MOVO-Service-Token")):
    _require_service(service_token)
    resource = await get_db().knowledge_resources.find_one({
        "_id": resource_id, "main_id": payload.mainId,
        "owner_user_id": payload.ownerUserId, "deleted_at": None,
    })
    if not resource:
        raise HTTPException(status_code=404, detail="knowledge_not_found")
    # Prefer the pending/failed replacement. The previous active version remains
    # available until this processing version succeeds and is switched in.
    document_id = str(resource.get("processing_document_id") or resource.get("active_document_id") or "")
    if not document_id:
        raise HTTPException(status_code=409, detail="knowledge_document_unavailable")
    actor = _actor(payload.mainId, payload.ownerUserId)
    document = await get_db().knowledge_documents.find_one({"_id": document_id, "main_id": payload.mainId, "deleted_at": None}) or {}
    preview_error = ""
    if str(document.get("file_ext") or "").lower() in {"doc", "docx", "xls", "xlsx", "ppt", "pptx"} and str(document.get("preview_status") or "") not in {"queued", "running", "succeeded"}:
        try:
            await retry_document_preview(document_id, current_user=actor)
        except HTTPException as exc:
            preview_error = str(exc.detail or "")
    result = await retry_document_parse(document_id, current_user=actor)
    return {"code": 0, "message": "success", "data": {**result, "previewRetryError": preview_error}}


@router.post("/{resource_id}/delete")
async def delete_personal_document(resource_id: str, payload: ActionPayload, service_token: str = Header(default="", alias="X-MOVO-Service-Token")):
    _require_service(service_token)
    resource = await get_db().knowledge_resources.find_one({
        "_id": resource_id, "main_id": payload.mainId,
        "owner_user_id": payload.ownerUserId, "deleted_at": None,
    })
    if not resource:
        raise HTTPException(status_code=404, detail="knowledge_not_found")
    document_ids = [str(value) for value in (resource.get("active_document_id"), resource.get("processing_document_id")) if value]
    for document_id in dict.fromkeys(document_ids):
        await delete_document(document_id, current_user=_actor(payload.mainId, payload.ownerUserId))
    return {"code": 0, "message": "success", "data": {"id": resource_id}}
