from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.principal import ApiPrincipal, require_end_user_principal
from app.services.skill_packages import SkillPackageError
from app.services.skill_sharing import SkillShareError, SkillShareService


router = APIRouter(dependencies=[Depends(require_end_user_principal)])
service = SkillShareService()


class CreateShareRequest(BaseModel):
    expires_in_days: int | None = Field(default=30, ge=1, le=365, alias="expiresInDays")


class InstallShareRequest(BaseModel):
    replace_existing: bool = Field(default=False, alias="replaceExisting")


def _response(data: object = None) -> dict[str, object]:
    return {"code": 0, "message": "success", "data": data}


def _raise(exc: SkillShareError | SkillPackageError) -> None:
    status = exc.status_code if isinstance(exc, SkillShareError) else 400
    raise HTTPException(status_code=status, detail=exc.detail()) from exc


@router.post("/skills/{skill_id}/shares")
async def create_skill_share(
    skill_id: str,
    payload: CreateShareRequest,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, object]:
    try:
        result = await service.create(
            main_id=principal.main_id,
            owner_user_id=principal.user_id,
            skill_id=skill_id,
            expires_in_days=payload.expires_in_days,
        )
    except (SkillShareError, SkillPackageError) as exc:
        _raise(exc)
    return _response(result)


@router.get("/skill-shares/{token}")
async def preview_skill_share(
    token: str,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, object]:
    try:
        result = await service.preview(
            main_id=principal.main_id, recipient_user_id=principal.user_id, token=token,
        )
    except SkillShareError as exc:
        _raise(exc)
    return _response(result)


@router.post("/skill-shares/{token}/install")
async def install_skill_share(
    token: str,
    payload: InstallShareRequest,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, object]:
    try:
        result = await service.install(
            main_id=principal.main_id,
            recipient_user_id=principal.user_id,
            token=token,
            replace_existing=payload.replace_existing,
        )
    except SkillShareError as exc:
        _raise(exc)
    return _response(result)


@router.delete("/skills/{skill_id}/shares/{share_id}")
async def revoke_skill_share(
    skill_id: str,
    share_id: str,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, object]:
    try:
        await service.revoke(
            main_id=principal.main_id,
            owner_user_id=principal.user_id,
            skill_id=skill_id,
            share_id=share_id,
        )
    except SkillShareError as exc:
        _raise(exc)
    return _response({"shareId": share_id})
