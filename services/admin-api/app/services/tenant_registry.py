"""Platform-level tenant registry — the ``tenants`` collection.

This is the source of truth for tenant *lifecycle* at the platform layer, kept
separate from the per-tenant ``organizations`` record (which only exists inside a
tenant). ``provision_tenant`` registers a record here on success; ``backfill``
reconciles tenants that predate this collection.

See ``specs/020-platform-multi-tenancy`` for the full contract.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import ReturnDocument

from app.core.db import get_db
from app.core.tenant_identity import DEFAULT_MAIN_ID, PLATFORM_MAIN_ID

logger = logging.getLogger(__name__)

TENANT_COLLECTION = "tenants"

# Identifiers that are not real tenants and must never be registered.
RESERVED_MAIN_IDS = (PLATFORM_MAIN_ID, DEFAULT_MAIN_ID, "", None)


async def is_tenant_active(main_id: str) -> bool:
    """True when the tenant may accept new members / logins (FR-024).

    Only ``active`` passes for a tenant that has a registry row. A tenant with
    *no* row is grandfathered in: a deployment that has not run the 020
    migration yet has an empty ``tenants`` collection, and failing closed there
    would lock every employee out. This mirrors
    ``chat-api/app/services/end_user_tenant_access._selectable_tenant_main_ids``
    — both sides must agree, otherwise one service lets in what the other
    rejects.
    """
    value = str(main_id or "").strip()
    if not value:
        return False
    db = get_db()
    row = await db[TENANT_COLLECTION].find_one({"main_id": value}, {"status": 1})
    if row is None:
        return True
    return str(row.get("status") or "") == "active"


async def ensure_indexes() -> None:
    db = get_db()
    await db[TENANT_COLLECTION].create_index(
        [("main_id", 1)],
        unique=True,
        name="tenant_main_id_unique",
    )
    await db[TENANT_COLLECTION].create_index(
        [("status", 1), ("created_at", -1)],
        name="tenant_status_created",
    )


async def ensure_tenant_record(
    *,
    main_id: str,
    name: str,
    edition: str = "community",
    admin_username: str = "",
    member_limit: int | None = None,
    created_by: str = "setup-wizard",
) -> dict[str, Any]:
    """Idempotently upsert a tenant registry row keyed by ``main_id``.

    ``status`` / ``created_by`` / ``created_at`` are only set on insert, so a
    re-provision or the backfill never clobbers an existing lifecycle state.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    doc = await db[TENANT_COLLECTION].find_one_and_update(
        {"main_id": main_id},
        {
            "$set": {
                # Phase 1 dual-write: canonical tenant_id + legacy main_id.
                "tenant_id": main_id,
                "main_id": main_id,
                "name": name,
                "edition": edition,
                "admin_username": admin_username,
                "member_limit": member_limit,
                "updated_at": now,
            },
            "$setOnInsert": {
                "_id": uuid4().hex,
                "status": "active",
                "created_by": created_by,
                "created_at": now,
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return doc


async def backfill_tenants_from_accounts() -> int:
    """幂等回填：把既有 ``admin_accounts`` 里的 ``main_id`` 登记到 ``tenants``。

    排除保留标识（``__platform__`` / ``default`` / 空）。可重复运行：已存在的
    ``main_id`` 不会重复登记，也不覆盖其生命周期状态。

    Returns the number of newly registered tenants.
    """
    db = get_db()

    existing_ids = {
        row["main_id"]
        async for row in db[TENANT_COLLECTION].find({}, {"main_id": 1})
        if row.get("main_id")
    }

    distinct_ids = await db["admin_accounts"].distinct("main_id")

    registered = 0
    for main_id in distinct_ids:
        if main_id in RESERVED_MAIN_IDS or main_id in existing_ids:
            continue

        admin = (
            await db["admin_accounts"].find_one(
                {"main_id": main_id, "is_protected": True}, {"username": 1}
            )
            or await db["admin_accounts"].find_one({"main_id": main_id}, {"username": 1})
        )
        admin_username = admin.get("username", "") if admin else ""

        org = await db["organizations"].find_one({"main_id": main_id}, {"org_name": 1, "edition": 1})
        name = (org or {}).get("org_name") or main_id
        edition = (org or {}).get("edition") or "community"

        await ensure_tenant_record(
            main_id=main_id,
            name=name,
            edition=edition,
            admin_username=admin_username,
            created_by="migration",
        )
        registered += 1
        logger.info("backfilled tenant %s (%s) from accounts", main_id, name)

    if registered:
        logger.info("tenant backfill registered %d tenant(s)", registered)
    return registered
