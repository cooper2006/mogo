from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.principal import ApiPrincipal, require_api_principal, require_end_user_principal
from app.services.skill_packages import SkillPackageError, SkillPackageInstaller, validate_skill_package
from app.services.skill_packages.validator import MAX_ARCHIVE_BYTES
from app.services.skill_packages.upgrade import SkillPackageUpgradeInspector
from app.services.skill_sharing.distribution import SkillDistributionService
from app.utils.uploads import read_upload_with_limit


router = APIRouter()
installer = SkillPackageInstaller()
upgrade_inspector = SkillPackageUpgradeInspector()


def _response(data: dict[str, Any]) -> dict[str, Any]:
    return {"code": 0, "message": "success", "data": data}


async def _validated_upload(file: UploadFile):
    filename = str(file.filename or "").strip()
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail={
            "code": "zip_required", "message": "请选择 ZIP 格式的 Skill 安装包", "file": filename,
        })
    content = await read_upload_with_limit(file, max_bytes=MAX_ARCHIVE_BYTES, label="Skill ZIP")
    try:
        return validate_skill_package(content)
    except SkillPackageError as exc:
        raise HTTPException(status_code=400, detail=exc.detail()) from exc


@router.post("/skills/install-zip")
async def install_personal_skill_zip(
    file: UploadFile = File(...),
    confirm_replace: bool = Form(default=False, alias="confirmReplace"),
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, Any]:
    package = await _validated_upload(file)
    upgrade = await upgrade_inspector.inspect(
        package, scope="personal", main_id=principal.main_id, user_id=principal.user_id,
    )
    if upgrade_inspector.requires_confirmation(upgrade) and not confirm_replace:
        raise HTTPException(status_code=409, detail={
            "code": "skill_upgrade_confirmation_required",
            "message": "Confirm before replacing the installed Skill",
            "upgrade": upgrade,
        })
    result = await installer.install(
        package,
        scope="personal",
        main_id=principal.main_id,
        user_id=principal.user_id,
        package_source={"kind": "local_zip", "fileName": str(file.filename or "")},
    )
    if upgrade_inspector.requires_confirmation(upgrade):
        await SkillDistributionService().publish_from_skill(
            main_id=principal.main_id,
            owner_user_id=principal.user_id,
            source_skill_id=str(result.get("id") or ""),
            version=str(result.get("version") or ""),
        )
    return _response({**result, "upgrade": upgrade})


@router.post("/organization-skills/install-zip")
async def install_organization_skill_zip(
    file: UploadFile = File(...),
    confirm_replace: bool = Form(default=False, alias="confirmReplace"),
    principal: ApiPrincipal = Depends(require_api_principal),
) -> dict[str, Any]:
    if principal.kind != "admin_service":
        raise HTTPException(status_code=403, detail={
            "code": "organization_install_forbidden",
            "message": "只有企业管理后台可以安装企业 Skill",
        })
    package = await _validated_upload(file)
    upgrade = await upgrade_inspector.inspect(package, scope="organization", main_id=principal.main_id)
    if upgrade_inspector.requires_confirmation(upgrade) and not confirm_replace:
        raise HTTPException(status_code=409, detail={
            "code": "skill_upgrade_confirmation_required",
            "message": "Confirm before replacing the installed Skill",
            "upgrade": upgrade,
        })
    result = await installer.install(
        package,
        scope="organization",
        main_id=principal.main_id,
        package_source={"kind": "local_zip", "fileName": str(file.filename or "")},
    )
    return _response({**result, "upgrade": upgrade})
