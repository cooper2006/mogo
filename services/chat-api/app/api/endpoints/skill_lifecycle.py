from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.endpoints.skills import _admin_shape_skill
from app.api.principal import ApiPrincipal, require_end_user_principal
from app.services.skill_lifecycle import SkillLifecycleError, SkillLifecycleService
from app.services.skill_sharing.distribution import SkillDistributionService
from app.services.skills import user_skill_service


router = APIRouter(dependencies=[Depends(require_end_user_principal)])
service = SkillLifecycleService()


class PublishSkillRequest(BaseModel):
    version: str = Field(default="", max_length=32)
    release_notes: str = Field(default="", max_length=2000, alias="releaseNotes")


def _raise(exc: SkillLifecycleError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc


@router.post("/skills/{skill_id}/publish")
async def publish_skill(
    skill_id: str,
    payload: PublishSkillRequest,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, object]:
    try:
        row, release = await service.publish(
            main_id=principal.main_id,
            user_id=principal.user_id,
            skill_id=skill_id,
            version=payload.version,
            release_notes=payload.release_notes,
        )
    except SkillLifecycleError as exc:
        _raise(exc)
    serialized = await user_skill_service.get_skill(principal.user_id, skill_id, main_id=principal.main_id)
    await SkillDistributionService().publish_from_skill(
        main_id=principal.main_id,
        owner_user_id=principal.user_id,
        source_skill_id=skill_id,
        release_id=str(release["_id"]),
        version=str(release["version"]),
        release_notes=str(release.get("release_notes") or ""),
    )
    return {
        "code": 0,
        "message": "success",
        "data": {"skill": _admin_shape_skill(serialized or row), "release": service.release_view(release)},
    }


@router.get("/skills/{skill_id}/releases")
async def list_skill_releases(
    skill_id: str,
    limit: int = Query(default=20, ge=1, le=50),
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, object]:
    try:
        items = await service.list_releases(
            main_id=principal.main_id, user_id=principal.user_id, skill_id=skill_id, limit=limit,
        )
    except SkillLifecycleError as exc:
        _raise(exc)
    return {"code": 0, "message": "success", "data": {"items": items}}
