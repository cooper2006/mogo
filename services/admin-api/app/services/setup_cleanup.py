from __future__ import annotations

import re

from app.core.db import get_db
from app.core.tenant_identity import is_reserved_main_id

# T053: only the collections the setup/provisioning pipeline actually writes.
# Kept deliberately separate from the purge path (app/services/tenant_purge.py)
# which sweeps every main_id-partitioned collection.
#
# "departments" was renamed to "org_units" (directory_repository.DEPARTMENT_COLLECTION);
# the old name is kept in the tuple so any legacy rows are removed too.
SETUP_SCOPED_COLLECTIONS = (
    "admin_account_groups",
    "admin_accounts",
    "admin_model_instances",
    "org_units",
    "end_users",
    "end_user_org_relations",
    "end_user_position_roles",
    "position_roles",
    "position_role_migrations",
    "position_role_audit_logs",
    "org_quota_policies",
    "user_quota_policies",
    "user_token_allocation_logs",
    "external_search_configs",
    "knowledge_document_settings",
    "organizations",
    "tenants",
)

# A freshly generated main_id looks like ``slug-hex`` (slug >= 1 char, 24 hex chars).
_MAIN_ID_SHAPE = re.compile(r"^[a-z0-9]+-[0-9a-f]{24}$")


def _assert_cleanup_target(main_id: str) -> None:
    """T053: refuse anything that is not a freshly generated tenant id.

    The old check (``len(main_id) >= 20``) accepted reserved identifiers like
    ``default`` / ``__platform__`` if padded — that must not be possible here
    because setup cleanup must never touch the platform tenant.
    """
    normalized = str(main_id or "").strip()
    if not normalized:
        raise ValueError("refusing to clean an empty tenant id")
    if is_reserved_main_id(normalized):
        raise ValueError("refusing to clean a reserved tenant identifier")
    if not _MAIN_ID_SHAPE.match(normalized):
        raise ValueError("refusing to clean a tenant id that does not match the freshly-generated shape")


async def cleanup_failed_setup(main_id: str) -> None:
    """Compensate a failed first-time setup for its newly generated tenant only."""
    _assert_cleanup_target(main_id)
    db = get_db()
    for collection_name in SETUP_SCOPED_COLLECTIONS:
        await db[collection_name].delete_many({"main_id": main_id})
