from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.principal import ApiPrincipal, require_end_user_principal
from app.services.resource_feedback import ResourceFeedbackError, ResourceFeedbackService


router = APIRouter(dependencies=[Depends(require_end_user_principal)])
service = ResourceFeedbackService()


class CommentRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    parent_id: str = Field(default="", alias="parentId", max_length=64)
    release_id: str = Field(default="", alias="releaseId", max_length=64, description="004 FR-4: scope the comment to a skill release")
    release_version: int | None = Field(default=None, alias="releaseVersion", ge=0)


def _raise(exc: ResourceFeedbackError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc


@router.get("/resource-feedback/{resource_type}/{resource_id}")
async def list_feedback(resource_type: str, resource_id: str, cursor: str = Query(default="", max_length=64), limit: int = Query(default=30, ge=1, le=100), release_id: str = Query(default="", alias="releaseId", max_length=64), release_version: int | None = Query(default=None, alias="releaseVersion", ge=0), principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        data = await service.list(tenant_id=principal.tenant_id, user_id=principal.user_id, resource_type=resource_type, resource_id=resource_id, cursor=cursor, limit=limit, release_id=release_id, release_version=release_version)
    except ResourceFeedbackError as exc:
        _raise(exc)
    return {"code": 0, "message": "success", "data": data}


@router.post("/resource-feedback/{resource_type}/{resource_id}/comments")
async def add_comment(resource_type: str, resource_id: str, payload: CommentRequest, principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        data = await service.comment(tenant_id=principal.tenant_id, user_id=principal.user_id, resource_type=resource_type, resource_id=resource_id, content=payload.content, parent_id=payload.parent_id, release_id=payload.release_id, release_version=payload.release_version)
    except ResourceFeedbackError as exc:
        _raise(exc)
    return {"code": 0, "message": "success", "data": data}


@router.delete("/resource-feedback/comments/{comment_id}")
async def delete_comment(comment_id: str, principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        await service.delete_comment(tenant_id=principal.tenant_id, user_id=principal.user_id, comment_id=comment_id)
    except ResourceFeedbackError as exc:
        _raise(exc)
    return {"code": 0, "message": "success", "data": {"id": comment_id}}


@router.post("/resource-feedback/comments/{comment_id}/like")
async def toggle_comment_like(comment_id: str, principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        data = await service.toggle_comment_like(tenant_id=principal.tenant_id, user_id=principal.user_id, comment_id=comment_id)
    except ResourceFeedbackError as exc:
        _raise(exc)
    return {"code": 0, "message": "success", "data": data}


@router.post("/resource-feedback/{resource_type}/{resource_id}/like")
async def toggle_like(resource_type: str, resource_id: str, principal: ApiPrincipal = Depends(require_end_user_principal)):
    try:
        data = await service.toggle_like(tenant_id=principal.tenant_id, user_id=principal.user_id, resource_type=resource_type, resource_id=resource_id)
    except ResourceFeedbackError as exc:
        _raise(exc)
    return {"code": 0, "message": "success", "data": data}


@router.get("/resource-feedback-notifications")
async def list_feedback_notifications(limit: int = Query(default=20, ge=1, le=50), principal: ApiPrincipal = Depends(require_end_user_principal)):
    return {"code": 0, "message": "success", "data": await service.notifications(tenant_id=principal.tenant_id, user_id=principal.user_id, limit=limit)}
