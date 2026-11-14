"""Tenant provisioning — the single entry point for creating a tenant.

Extracted from ``app/api/routes/setup.py::setup_initialize()`` so that both the
first-boot wizard (phase A) and the platform console (phase B) share one code
path. This module is intentionally behaviour-preserving: every step below is a
verbatim move from the original inline flow.

``employee`` / ``model`` / ``additional_models`` / ``external_search`` / ``quota``
are all optional (omitted blocks are skipped without connectivity checks) so the
same entry point serves both the first-boot wizard and the platform console.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from pymongo.errors import DuplicateKeyError

from app.core.db import get_db
from app.core.security import hash_password
from app.position_roles.repository import PositionRoleRepository
from app.product.extensions import get_admin_product_extension
from app.repositories.directory_repository import (
    DEPARTMENT_COLLECTION,
    USER_COLLECTION,
    USER_ORG_REL_COLLECTION,
    ensure_root_department,
)
from app.repositories.org_user_repository import (
    ensure_bootstrap_account,
    ensure_group_exists,
    find_account_by_username,
)
from app.services.setup_cleanup import cleanup_failed_setup
from app.services.setup_external_search import save_setup_search
from app.services.setup_knowledge import configure_setup_knowledge_models
from app.services.setup_model import create_setup_model
from app.services.setup_quota import configure_setup_quotas
from app.services.tenant_registry import ensure_tenant_record

# NOTE: imported lazily at module scope purely for the SC-007 audit hook;
# ``tenant_lifecycle`` does not import this module, so there is no cycle.
from app.services import tenant_lifecycle


@dataclass
class ProvisionResult:
    tenant_id: str
    org_name: str
    model_instance_id: str | None = None
    additional_model_instance_ids: list[str] = field(default_factory=list)


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned or "org"


async def _next_tenant_id(org_name: str) -> str:
    db = get_db()
    base = _slug(org_name)[:12]
    for _ in range(12):
        candidate = f"{base}-{secrets.token_hex(12)}"
        exists = await db["admin_accounts"].find_one({"tenant_id": candidate}, {"_id": 1})
        if not exists:
            return candidate
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="tenant_id generation failed")


async def provision_tenant(
    *,
    org_name: str,
    admin_username: str,
    admin_password: str,
    admin_display_name: str,
    employee_username: str | None = None,
    employee_password: str | None = None,
    employee_name: str | None = None,
    model: dict[str, Any] | None = None,
    additional_models: list[dict[str, Any]] | None = None,
    external_search: dict[str, Any] | None = None,
    quota: dict[str, Any] | None = None,
    embedding_dimension: int | None = None,
    created_by: str = "",
) -> ProvisionResult:
    """Create a tenant: admin account, root department, organization, roles and optional configuration.

    The bootstrap admin (``admin_username``) is always created. Everything else is
    optional and skipped — **without any connectivity check** — when omitted:

    * ``employee_*`` — a sample regular user / org owner.
    * ``model`` + ``additional_models`` — the chat/embedding models and the
      knowledge-base configuration that depends on them.
    * ``external_search`` — external search provider.
    * ``quota`` — token quota policy (``{"total_tokens", "default_user_tokens",
      "period", "timezone"}``); ``None`` means no quota policy is configured.

    ``created_by`` records the provisioning source (e.g. ``setup-wizard`` or the
    platform admin username). It is currently informational only.
    """
    additional_models = list(additional_models or [])
    tenant_id = await _next_tenant_id(org_name)
    org_name = org_name.strip()
    now = datetime.now(timezone.utc)

    try:
        await ensure_group_exists(
            name="系统管理员",
            code="system_admin",
            tenant_id=tenant_id,
            description="系统内置账号组",
        )
        await ensure_bootstrap_account(
            tenant_id=tenant_id,
            username=admin_username.strip(),
            password=admin_password,
            display_name=admin_display_name.strip(),
            role_name="租户管理员",
            org_name=org_name,
            group_code="system_admin",
        )

        await ensure_root_department(tenant_id)
        db = get_db()
        root = await db[DEPARTMENT_COLLECTION].find_one({"tenant_id": tenant_id, "code": "root"})
        if not root:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="root department init failed")
        root_id = str(root["_id"])

        # The bootstrap admin always exists; it becomes the org owner when no
        # separate employee user is supplied.
        admin_account = await find_account_by_username(admin_username.strip(), tenant_id)
        if admin_account is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="bootstrap admin account not found after creation",
            )
        owner_user_id = str(admin_account["_id"])

        if employee_username and employee_password and employee_name:
            password_hash, password_salt = hash_password(employee_password)
            try:
                result = await db[USER_COLLECTION].insert_one(
                    {
                        "tenant_id": tenant_id,
                        "name": employee_name.strip(),
                        "mobile": "",
                        "email": "",
                        "status": "active",
                        "source": "local",
                        "source_user_id": "",
                        "primary_org_id": root_id,
                        "login_name": employee_username.strip(),
                        "password_hash": password_hash,
                        "password_salt": password_salt,
                        "org_name": org_name,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
            except DuplicateKeyError as exc:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="员工登录名已存在") from exc
            owner_user_id = str(result.inserted_id)

        product_extension = get_admin_product_extension()
        organization_defaults = dict(product_extension.organization_defaults)
        total_tokens = (quota or {}).get("total_tokens") if quota else None
        if product_extension.edition == "community" and total_tokens is not None:
            organization_defaults["total_points"] = max(int(total_tokens or 0), 0)
        # T034 / decision 12: quota=None or total_tokens=0 means "unlimited".
        points_unlimited = (total_tokens is None) or (int(total_tokens or 0) == 0)
        await db["organizations"].update_one(
            {"tenant_id": tenant_id},
            {
                "$set": {
                    "tenant_id": tenant_id,
                    "org_name": org_name,
                    "owner_user_id": owner_user_id,
                    **organization_defaults,
                    "points_unlimited": points_unlimited,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        await db[USER_ORG_REL_COLLECTION].insert_one(
            {
                "tenant_id": tenant_id,
                "user_id": owner_user_id,
                "org_id": root_id,
                "is_primary": True,
                "created_at": now,
                "updated_at": now,
            }
        )

        position_roles = PositionRoleRepository(db)
        await position_roles.ensure_indexes()
        full_access_role = await position_roles.ensure_full_access_role(tenant_id)
        await position_roles.assign_role(
            tenant_id,
            owner_user_id,
            str(full_access_role["_id"]),
            primary=True,
            actor=admin_username.strip(),
        )
        await position_roles.complete_migration(tenant_id, admin_username.strip())

        if quota is not None:
            await configure_setup_quotas(
                tenant_id=tenant_id,
                total_tokens=quota.get("total_tokens") or 0,
                default_user_tokens=quota.get("default_user_tokens") or 0,
                period=quota.get("period") or "monthly",
                timezone_name=quota.get("timezone") or "Asia/Shanghai",
                operator=admin_username.strip(),
            )

        model_instance_id: str | None = None
        additional_model_ids: list[str] = []
        if model is not None:
            model_instance_id = await create_setup_model(model, tenant_id)
            additional_model_ids = [await create_setup_model(item, tenant_id) for item in additional_models]
            await configure_setup_knowledge_models(
                tenant_id=tenant_id,
                configured_models=list(zip(additional_models, additional_model_ids)),
                operator=admin_username.strip(),
                embedding_dimension=embedding_dimension,
            )

        if external_search is not None:
            await save_setup_search(external_search, tenant_id)

        # Register in the platform registry last: a failure above triggers
        # cleanup_failed_setup, which now also removes the tenants record.
        await ensure_tenant_record(
            tenant_id=tenant_id,
            name=org_name,
            edition=product_extension.edition,
            admin_username=admin_username.strip(),
            created_by=created_by or "setup-wizard",
        )
    except Exception as exc:
        # SC-007: record the failure FIRST. ``cleanup_failed_setup`` deletes the
        # tenant row, so the audit log is the only remaining evidence that this
        # provisioning attempt ever happened; if cleanup itself throws, the
        # audit must already be written.
        await tenant_lifecycle.record_tenant_audit(
            tenant_id,
            created_by or "setup-wizard",
            "create",
            org_name,
            "failure",
            {"error": str(exc)[:500]},
        )
        await cleanup_failed_setup(tenant_id)
        raise

    # SC-007: every lifecycle operation is auditable (create / rename /
    # enable-disable / archive / restore / purge / reset-password).
    await tenant_lifecycle.record_tenant_audit(
        tenant_id,
        created_by or "setup-wizard",
        "create",
        org_name,
        "success",
        {"admin_username": admin_username.strip()},
    )

    return ProvisionResult(
        tenant_id=tenant_id,
        org_name=org_name,
        model_instance_id=model_instance_id,
        additional_model_instance_ids=additional_model_ids,
    )
