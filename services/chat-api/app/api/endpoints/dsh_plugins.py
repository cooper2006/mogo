"""Authenticated enterprise and personal DSH plugin control plane."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.principal import ApiPrincipal, require_api_principal
from app.dsh_runtime.plugin_management.installer import DshPluginInstaller, PluginInstallError
from app.dsh_runtime.plugin_management.repository import PluginInstallationRepository
from app.dsh_runtime.plugin_management.source_policy import is_safe_personal_source
from app.dsh_runtime.plugin_management.archive_store import delete_archive, save_archive, MAX_ARCHIVE_BYTES
from app.core.db import get_db
from app.utils.uploads import read_upload_with_limit
from app.product.extensions import get_product_extension
from app.product.resource_access import filter_allowed_resource_ids


router = APIRouter(prefix="/dsh-plugins", tags=["dsh-plugins"])
repository = PluginInstallationRepository()


class InstallRequest(BaseModel):
    spec: str = Field(min_length=1, max_length=500)


class EnabledRequest(BaseModel):
    enabled: bool


def _owner(principal: ApiPrincipal, scope: str) -> str:
    if scope == "organization":
        if principal.kind != "admin_service":
            raise HTTPException(status_code=403, detail="organization_plugin_admin_required")
        return ""
    if scope == "personal" and principal.kind == "end_user":
        return principal.user_id
    raise HTTPException(status_code=403, detail="personal_plugin_user_required")


def _result(data):
    return {"code": 0, "message": "success", "data": data}


@router.get("/{scope}")
async def list_plugins(scope: str, principal: ApiPrincipal = Depends(require_api_principal)):
    owner = _owner(principal, scope)
    plugins = await repository.list(principal.tenant_id, owner)
    if owner:
        organization = [plugin for plugin in plugins if plugin["scope"] == "organization"]
        allowed = await filter_allowed_resource_ids(
            "plugin", main_id=principal.tenant_id, user_id=owner,
            resource_ids=(plugin["id"] for plugin in organization),
        )
        denied_names = {plugin["name"] for plugin in organization if plugin["id"] not in allowed}
        plugins = [plugin for plugin in plugins if plugin["name"] not in denied_names and (
            plugin["scope"] == "personal" or plugin["id"] in allowed
        )]
    return _result(plugins)


async def _initialize_organization_access(main_id: str, plugin: dict) -> None:
    policy = get_product_extension().resource_access_policy
    initialize = getattr(policy, "initialize_plugin", None)
    if callable(initialize):
        await initialize(main_id=main_id, plugin_id=plugin["id"])


async def _existing_organization_plugin(tenant_id: str, name: str) -> bool:
    return bool(await get_db().dsh_plugin_installations.find_one({
        "tenant_id": tenant_id, "owner_user_id": "", "engine": "dsh", "name": name,
    }, {"_id": 1}))


async def _check_personal_name(principal: ApiPrincipal, owner: str, name: str) -> None:
    if not owner:
        return
    row = await get_db().dsh_plugin_installations.find_one({
        "tenant_id": principal.tenant_id, "owner_user_id": "", "engine": "dsh", "name": name,
    }, {"_id": 1})
    if row:
        allowed = await filter_allowed_resource_ids(
            "plugin", main_id=principal.tenant_id, user_id=owner,
            resource_ids=(str(row["_id"]),),
        )
        if str(row["_id"]) not in allowed:
            raise HTTPException(status_code=403, detail="personal_plugin_conflicts_with_restricted_enterprise_plugin")


async def _save_inspected_plugin(principal: ApiPrincipal, owner: str, package: dict) -> dict:
    await _check_personal_name(principal, owner, package["name"])
    existed = await _existing_organization_plugin(principal.tenant_id, package["name"]) if not owner else True
    plugin = await repository.save(tenant_id=principal.tenant_id, user_id=owner, **package)
    if not owner and not existed:
        try:
            await _initialize_organization_access(principal.tenant_id, plugin)
        except Exception:
            # An installation without its initial audience would inherit legacy
            # all-employee access, so remove the incomplete record.
            await repository.remove(tenant_id=principal.tenant_id, user_id="", plugin_id=plugin["id"])
            raise
    return plugin


@router.post("/{scope}/install")
async def install_plugin(
    scope: str, body: InstallRequest,
    principal: ApiPrincipal = Depends(require_api_principal),
):
    owner = _owner(principal, scope)
    if owner and not is_safe_personal_source(body.spec):
        raise HTTPException(status_code=400, detail="personal_plugin_source_must_be_public")
    try:
        package = await DshPluginInstaller().inspect_and_install(body.spec)
    except PluginInstallError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _result(await _save_inspected_plugin(principal, owner, package))


@router.post("/{scope}/upload")
async def upload_plugin(
    scope: str, file: UploadFile = File(...),
    principal: ApiPrincipal = Depends(require_api_principal),
):
    owner = _owner(principal, scope)
    filename = (file.filename or "").lower()
    if not filename.endswith((".tgz", ".tar.gz")):
        raise HTTPException(status_code=400, detail="plugin_archive_must_be_tgz")
    content = await read_upload_with_limit(file, max_bytes=MAX_ARCHIVE_BYTES, label="Plugin archive")
    if not content.startswith(b"\x1f\x8b"):
        raise HTTPException(status_code=400, detail="plugin_archive_must_be_gzip")
    archive_id, digest = await save_archive(get_db(), content, main_id=principal.tenant_id)
    try:
        package = await DshPluginInstaller().inspect_and_install(
            "uploaded-plugin", archive_id=archive_id, archive_digest=digest,
        )
        return _result(await _save_inspected_plugin(principal, owner, package))
    except PluginInstallError as exc:
        await delete_archive(get_db(), archive_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await delete_archive(get_db(), archive_id)
        raise


@router.post("/{scope}/{plugin_id}/verify")
async def verify_plugin(
    scope: str, plugin_id: str, principal: ApiPrincipal = Depends(require_api_principal),
):
    owner = _owner(principal, scope)
    row = await repository.get(tenant_id=principal.tenant_id, user_id=owner, plugin_id=plugin_id)
    if row is None:
        raise HTTPException(status_code=404, detail="plugin_not_found")
    try:
        package = await DshPluginInstaller().inspect_and_install(
            str(row["spec"]),
            archive_id=str(row.get("archive_id") or ""),
            archive_digest=str(row.get("archive_digest") or ""),
        )
    except PluginInstallError as exc:
        availability = {"status": "failed", "reason": str(exc), "checks": {"invocation": False}}
        updated = await repository.update_assessment(
            tenant_id=principal.tenant_id, user_id=owner, plugin_id=plugin_id,
            availability=availability, tool_names=list(row.get("tool_names") or []),
        )
        return _result(updated)
    updated = await repository.update_assessment(
        tenant_id=principal.tenant_id, user_id=owner, plugin_id=plugin_id,
        availability=package["availability"], tool_names=package["tool_names"],
        registry=package.get("registry", ""),
    )
    return _result(updated)


@router.patch("/{scope}/{plugin_id}/enabled")
async def set_plugin_enabled(
    scope: str, plugin_id: str, body: EnabledRequest,
    principal: ApiPrincipal = Depends(require_api_principal),
):
    owner = _owner(principal, scope)
    existing = await repository.get(tenant_id=principal.tenant_id, user_id=owner, plugin_id=plugin_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="plugin_not_found")
    if body.enabled and (existing.get("availability") or {}).get("status") not in {"session_exposed", "verified"}:
        raise HTTPException(status_code=409, detail="plugin_failed_mogo_availability_check")
    row = await repository.set_enabled(
        tenant_id=principal.tenant_id, user_id=owner,
        plugin_id=plugin_id, enabled=body.enabled,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="plugin_not_found")
    return _result(row)


@router.delete("/{scope}/{plugin_id}")
async def remove_plugin(
    scope: str, plugin_id: str,
    principal: ApiPrincipal = Depends(require_api_principal),
):
    owner = _owner(principal, scope)
    if not await repository.remove(
        tenant_id=principal.tenant_id, user_id=owner, plugin_id=plugin_id,
    ):
        raise HTTPException(status_code=404, detail="plugin_not_found")
    policy = get_product_extension().resource_access_policy
    delete = getattr(policy, "delete_plugin", None)
    if not owner and callable(delete):
        await delete(main_id=principal.tenant_id, plugin_id=plugin_id)
    return _result({"removed": True})
