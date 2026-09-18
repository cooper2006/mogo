from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.endpoints.skill_shares import _raise, _response
from app.api.principal import ApiPrincipal, require_end_user_principal
from app.services.skill_packages import SkillPackageError
from app.services.skill_sharing.direct_service import DirectSkillShareService
from app.services.skill_sharing.member_directory import SkillShareMemberDirectory
from app.services.skill_sharing.service import SkillShareError
from app.services.skill_sharing.distribution import SkillDistributionService
from app.services.resource_feedback import ResourceFeedbackService


router = APIRouter(dependencies=[Depends(require_end_user_principal)])
service = DirectSkillShareService()
directory = SkillShareMemberDirectory()


class DirectShareRequest(BaseModel):
    recipient_user_ids: list[str] = Field(min_length=1, max_length=100, alias="recipientUserIds")


class AcceptShareRequest(BaseModel):
    replace_existing: bool = Field(default=False, alias="replaceExisting")


@router.get("/skill-share-directory")
async def search_share_members(
    keyword: str = Query(default="", max_length=80),
    cursor: str = Query(default="", max_length=128),
    limit: int = Query(default=20, ge=1, le=50),
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, object]:
    result = await directory.search(
        main_id=principal.main_id,
        requester_user_id=principal.user_id,
        keyword=keyword,
        cursor=cursor,
        limit=limit,
    )
    return _response(result)


@router.post("/skills/{skill_id}/share-with-users")
async def share_skill_with_users(
    skill_id: str,
    payload: DirectShareRequest,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, object]:
    try:
        result = await service.create(
            main_id=principal.main_id,
            owner_user_id=principal.user_id,
            skill_id=skill_id,
            recipient_user_ids=payload.recipient_user_ids,
        )
    except (SkillShareError, SkillPackageError) as exc:
        _raise(exc)
    return _response(result)


@router.get("/skill-share-inbox")
async def list_skill_share_inbox(
    cursor: str = Query(default="", max_length=128),
    limit: int = Query(default=20, ge=1, le=50),
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, object]:
    try:
        result = await service.inbox(
            main_id=principal.main_id,
            recipient_user_id=principal.user_id,
            cursor=cursor,
            limit=limit,
        )
    except SkillShareError as exc:
        _raise(exc)
    return _response(result)


@router.get("/skill-share-inbox/count")
async def count_skill_share_inbox(
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, object]:
    count = await service.pending_count(
        main_id=principal.main_id,
        recipient_user_id=principal.user_id,
    )
    updates = await SkillDistributionService().list_updates(
        main_id=principal.main_id, recipient_user_id=principal.user_id, limit=1,
    )
    feedback = await ResourceFeedbackService().unread_count(
        main_id=principal.main_id, user_id=principal.user_id,
        resource_types=["skill_distribution", "organization_skill"],
    )
    return _response({
        "pendingCount": count + int(updates.get("pendingCount") or 0) + feedback,
        "sharedCount": count,
        "updateCount": int(updates.get("pendingCount") or 0),
        "feedbackCount": feedback,
    })


@router.post("/skill-share-inbox/{delivery_id}/accept")
async def accept_shared_skill(
    delivery_id: str,
    payload: AcceptShareRequest,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, object]:
    try:
        result = await service.accept(
            main_id=principal.main_id,
            recipient_user_id=principal.user_id,
            delivery_id=delivery_id,
            replace_existing=payload.replace_existing,
        )
    except SkillShareError as exc:
        _raise(exc)
    return _response(result)


@router.post("/skill-share-inbox/{delivery_id}/decline")
async def decline_shared_skill(
    delivery_id: str,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, object]:
    try:
        await service.decline(
            main_id=principal.main_id,
            recipient_user_id=principal.user_id,
            delivery_id=delivery_id,
        )
    except SkillShareError as exc:
        _raise(exc)
    return _response({"deliveryId": delivery_id})
