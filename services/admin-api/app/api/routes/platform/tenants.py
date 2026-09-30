"""Platform tenant management routes (T025–T051).

All routes are mounted under ``/api/platform`` and require the platform
super-admin dependency (``get_current_platform_admin``). See
``contracts/tenants.md`` for the wire format.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.api.deps import get_current_platform_admin
from app.core.db import get_db
from app.core.tenant_identity import PLATFORM_MAIN_ID
from app.repositories.org_user_repository import set_account_password
from app.services import tenant_lifecycle, tenant_purge
from app.services.tenant_provisioning import ProvisionResult, provision_tenant
from app.services.tenant_registry import TENANT_COLLECTION

logger = logging.getLogger(__name__)
router = APIRouter(tags=["platform"])

__all__ = ["router"]


def _actor(platform_admin: dict) -> str:
    return str(platform_admin.get("username") or PLATFORM_MAIN_ID)


# ---------------------------------------------------------------------------
# Tenant CRUD
# ---------------------------------------------------------------------------


@router.post("/tenants", response_model=ProvisionResult)
async def create_tenant(
    payload: dict[str, Any],
    platform_admin: dict = Depends(get_current_platform_admin),
):
    """T026: create a tenant from the platform console.

    The full provisioning pipeline is identical to the setup wizard;
    ``created_by`` records the acting platform admin username.
    """
    org_name = str(payload.get("orgName") or payload.get("org_name") or "").strip()
    admin_username = str(payload.get("adminUsername") or payload.get("admin_username") or "").strip()
    admin_password = str(payload.get("adminPassword") or payload.get("admin_password") or "")
    admin_display_name = str(payload.get("adminDisplayName") or payload.get("admin_display_name") or "系统管理员")

    if not org_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="orgName is required")
    if not admin_username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="adminUsername is required")
    if len(admin_password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="adminPassword must have at least 6 characters")

    employee = payload.get("employee")
    model = payload.get("model")
    additional_models = payload.get("additionalModels") or payload.get("additional_models")
    external_search = payload.get("externalSearch") or payload.get("external_search")
    quota = payload.get("quota")

    result = await provision_tenant(
        org_name=org_name,
        admin_username=admin_username,
        admin_password=admin_password,
        admin_display_name=admin_display_name,
        employee_username=(employee or {}).get("username") if employee else None,
        employee_password=(employee or {}).get("password") if employee else None,
        employee_name=(employee or {}).get("name") if employee else None,
        model=model,
        additional_models=additional_models,
        external_search=external_search,
        quota=quota,
        created_by=f"platform-admin:{_actor(platform_admin)}",
    )
    return result


@router.get("/tenants")
async def list_tenants(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    keyword: str = Query(""),
    status_filter: str = Query("", alias="status"),
    platform_admin: dict = Depends(get_current_platform_admin),
):
    """T027: list tenants (lifecycle fields only, no business metrics).

    Purged tenants are excluded by default; pass ``status=purged`` explicitly
    to include them (the 1-month tombstone window, decision 19).
    """
    del platform_admin
    db = get_db()
    query: dict[str, Any] = {}
    if keyword:
        escaped = keyword.replace("\\", "\\\\").replace("$", "\\$").replace(".", "\\.")
        query["name"] = {"$regex": escaped, "$options": "i"}
    if status_filter:
        query["status"] = status_filter
    else:
        query["status"] = {"$nin": ["purged"]}

    total = await db[TENANT_COLLECTION].count_documents(query)
    skip = (page - 1) * page_size
    cursor = db[TENANT_COLLECTION].find(query).sort("created_at", -1).skip(skip).limit(page_size)
    items = []
    async for tenant in cursor:
        items.append(await tenant_lifecycle.tenant_view(tenant))
    return {"items": items, "total": total}


@router.get("/tenants/{main_id}")
async def get_tenant(
    main_id: str,
    platform_admin: dict = Depends(get_current_platform_admin),
):
    """T027: lifecycle detail for a single tenant."""
    del platform_admin
    tenant = await tenant_lifecycle._get_tenant(main_id)
    return await tenant_lifecycle.tenant_view(tenant)


@router.patch("/tenants/{main_id}")
async def patch_tenant(
    main_id: str,
    payload: dict[str, Any],
    platform_admin: dict = Depends(get_current_platform_admin),
):
    """T030: update name / status (active <-> disabled) / memberLimit.

    Archived and purged tenants cannot be re-enabled here — use the dedicated
    ``/restore`` and ``/purge`` routes instead.

    Each field is independent: a payload that omits ``memberLimit`` must leave
    the existing limit alone. Do not default it to the ``"null"`` sentinel —
    that clears the limit on every rename (see ``update_tenant``).
    """
    member_limit = payload["memberLimit"] if "memberLimit" in payload else payload.get("member_limit")
    return await tenant_lifecycle.update_tenant(
        main_id,
        actor=_actor(platform_admin),
        name=payload.get("name"),
        status_target=payload.get("status"),
        member_limit=member_limit,
    )


# ---------------------------------------------------------------------------
# Tenant admin maintenance
# ---------------------------------------------------------------------------


@router.post("/tenants/{main_id}/admin/reset-password")
async def reset_tenant_admin_password(
    main_id: str,
    payload: dict[str, Any],
    platform_admin: dict = Depends(get_current_platform_admin),
):
    """T031: reset the tenant's own admin password (no forced change on next login)."""
    tenant = await tenant_lifecycle._get_tenant(main_id)
    username = str(tenant.get("admin_username") or "").strip()
    new_password = str(payload.get("newPassword") or payload.get("new_password") or "")
    if not username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant has no admin username")
    if len(new_password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="newPassword must have at least 6 characters")

    await set_account_password(username, new_password, str(tenant.get("main_id")))
    await tenant_lifecycle._record_audit(
        str(tenant.get("main_id")),
        _actor(platform_admin),
        "reset-password",
        username,
        "success",
    )
    return {"success": True}


# ---------------------------------------------------------------------------
# Lifecycle: archive / restore / purge
# ---------------------------------------------------------------------------


@router.delete("/tenants/{main_id}")
async def archive_tenant_route(
    main_id: str,
    payload: dict[str, Any] | None = None,
    platform_admin: dict = Depends(get_current_platform_admin),
):
    """T039: soft-archive a tenant (data stays intact, login is blocked,
    licensing count drops, decision 18)."""
    reason = str((payload or {}).get("reason") or "")
    return await tenant_lifecycle.archive_tenant(main_id, actor=_actor(platform_admin), reason=reason)


@router.post("/tenants/{main_id}/restore")
async def restore_tenant_route(
    main_id: str,
    platform_admin: dict = Depends(get_current_platform_admin),
):
    """T041: restore an archived tenant back to active (data intact)."""
    return await tenant_lifecycle.restore_tenant(main_id, actor=_actor(platform_admin))


@router.post("/tenants/{main_id}/purge")
async def purge_tenant_route(
    main_id: str,
    payload: dict[str, Any],
    background: BackgroundTasks,
    platform_admin: dict = Depends(get_current_platform_admin),
):
    """T045–T050: irreversibly delete a tenant (archived only).

    ``confirmName`` must exactly match the tenant's current name, otherwise 400.
    Returns immediately with a task id; poll ``GET /tenants/{main_id}/purge-status``
    for progress (mongo / vectors / files phases).
    """
    tenant = await tenant_lifecycle._get_tenant(main_id)
    confirm_name = str(payload.get("confirmName") or payload.get("confirm_name") or "")
    if confirm_name != str(tenant.get("name") or ""):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirmName does not match tenant name")
    if tenant_lifecycle._status(tenant) != "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only archived tenants can be purged")

    task_id = str(uuid.uuid4())
    background.add_task(
        tenant_purge.run_purge,
        main_id=str(tenant.get("main_id")),
        task_id=task_id,
        actor=_actor(platform_admin),
    )
    return {"taskId": task_id, "status": "running"}


@router.get("/tenants/{main_id}/purge-status")
async def purge_tenant_status_route(
    main_id: str,
    platform_admin: dict = Depends(get_current_platform_admin),
):
    """T046–T047: poll purge progress (mongo / vectors / files phases)."""
    del platform_admin
    return await tenant_purge.get_purge_status(main_id)


# ---------------------------------------------------------------------------
# Platform console utilities
# ---------------------------------------------------------------------------


@router.get("/me")
async def platform_me(platform_admin: dict = Depends(get_current_platform_admin)):
    """Minimal platform-admin identity for the console UI."""
    return {
        "username": str(platform_admin.get("username") or ""),
        "displayName": str(platform_admin.get("display_name") or platform_admin.get("username") or ""),
        "mainId": PLATFORM_MAIN_ID,
    }


@router.get("/system/health")
async def system_health(platform_admin: dict = Depends(get_current_platform_admin)):
    """T051: read-only service health (same shape as /setup/status services)."""
    del platform_admin
    return await tenant_purge.system_health()
