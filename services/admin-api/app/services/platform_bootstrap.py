"""Platform super-admin bootstrap.

The platform super-admin is the single tenant-lifecycle operator. It lives in
the reserved ``__platform__`` tenant_id (decision 1) and is created only by the
first-boot wizard (``POST /api/setup/platform-admin``). Its credentials are
stored in ``admin_accounts`` — there is no environment-variable bootstrap
anymore, so account/password management is entirely database-driven.
"""

from __future__ import annotations

import logging

from app.core.db import get_db
from app.core.tenant_identity import PLATFORM_TENANT_ID
from app.repositories.org_user_repository import (
    ensure_bootstrap_account,
    ensure_group_exists,
    find_account_by_username,
)

logger = logging.getLogger(__name__)

PLATFORM_ADMIN_GROUP_CODE = "platform_admin"
PLATFORM_ADMIN_GROUP_NAME = "平台管理组"
PLATFORM_ADMIN_ROLE_NAME = "平台超级管理员"
PLATFORM_ADMIN_ORG_NAME = "平台控制台"
ACCOUNT_COLLECTION = "admin_accounts"


async def platform_admin_exists() -> bool:
    """True when any account already lives in the reserved platform tenant."""
    db = get_db()
    account = await db[ACCOUNT_COLLECTION].find_one({"tenant_id": PLATFORM_TENANT_ID}, {"_id": 1})
    return account is not None


async def ensure_platform_admin(*, username: str, password: str, display_name: str) -> dict:
    """Idempotently create the platform super-admin account in ``__platform__``."""
    username = username.strip()
    await ensure_group_exists(
        name=PLATFORM_ADMIN_GROUP_NAME,
        code=PLATFORM_ADMIN_GROUP_CODE,
        tenant_id=PLATFORM_TENANT_ID,
        description="平台控制台内置账号组",
    )
    await ensure_bootstrap_account(
        tenant_id=PLATFORM_TENANT_ID,
        username=username,
        password=password,
        display_name=display_name.strip() or username,
        role_name=PLATFORM_ADMIN_ROLE_NAME,
        org_name=PLATFORM_ADMIN_ORG_NAME,
        group_code=PLATFORM_ADMIN_GROUP_CODE,
    )
    return await find_account_by_username(username, PLATFORM_TENANT_ID) or {}


async def bootstrap_platform_admin() -> None:
    """Startup hook: ensure a platform admin exists, otherwise warn.

    The environment-variable bootstrap was removed: the platform super-admin is
    created only through the ``/setup`` wizard and its credentials live in the
    ``admin_accounts`` collection, so account/password management is entirely
    database-driven (no ``ASKAI_ADMIN_PLATFORM_ADMIN_PASSWORD`` anymore).
    """
    if await platform_admin_exists():
        return
    logger.warning(
        "no platform admin found; run the /setup wizard to create the platform "
        "super-admin (ASKAI_ADMIN_PLATFORM_ADMIN_PASSWORD is no longer supported)"
    )
