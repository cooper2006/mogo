from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.principal import ApiPrincipal, require_end_user_principal
from app.services.skill_sharing.distribution import SkillDistributionService
from app.services.skill_sharing.service import SkillShareError


router = APIRouter(dependencies=[Depends(require_end_user_principal)])
service = SkillDistributionService()

class InstallUpdateRequest(BaseModel):
    confirm_replace: bool = Field(default=False, alias="confirmReplace")


@router.get("/skill-updates")
async def list_skill_updates(
    limit: int = Query(default=50, ge=1, le=50),
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, object]:
    result = await service.list_updates(
        main_id=principal.main_id, recipient_user_id=principal.user_id, limit=limit,
    )
    return {"code": 0, "message": "success", "data": result}


@router.post("/skill-updates/{notification_id}/install")
async def install_skill_update(
    notification_id: str,
    payload: InstallUpdateRequest,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, object]:
    try:
        result = await service.install_update(
            main_id=principal.main_id,
            recipient_user_id=principal.user_id,
            notification_id=notification_id,
            confirm_replace=payload.confirm_replace,
        )
    except SkillShareError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    return {"code": 0, "message": "success", "data": result}
