"""Tenant purge service (T045–T053): irreversible, asynchronous.

A purge only runs for a tenant in ``archived`` status (FR-028, re-checked when
the task starts) and walks three sequential phases:

1. **mongo** — delete every row in the tenant-scoped collections whose
   ``main_id`` matches.
2. **vectors** — call the document-parser service to remove Weaviate chunks
   for this tenant's knowledge documents.
3. **files** — remove local storage directories for knowledge documents and
   admin avatars.

FR-033 semantics: if *any* phase fails the tenant is left ``archived`` with the
failure recorded in ``archive_reason`` and the task marked ``failed``. Only when
all three phases succeed is the tenant row flipped to ``purged`` (the tombstone
that ``cleanup_expired_tombstones`` reaps after 30 days).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from app.core.config import settings
from app.core.db import get_db
from app.services.tenant_registry import TENANT_COLLECTION

logger = logging.getLogger(__name__)

# main_id-partitioned business collections (T045 full enumeration).
# ``tenants`` itself is handled separately at the end of the mongo phase.
#
# NOTE: this list must cover *both* admin-api and chat-api collections — a
# tenant's data lives in both services, and purge is executed by admin-api
# only. Verify with the helper at the bottom of this module
# (``_audit_collection_coverage``) before adding a collection to either
# service, otherwise tenant data survives a purge (SC-005).
TENANT_SCOPED_COLLECTIONS: list[str] = [
    "admin_account_groups",
    "admin_accounts",
    "admin_login_challenges",
    "admin_model_instances",
    "admin_presentation_settings",
    "audit_logs",
    "chat_messages",
    "chat_sessions",
    "desktop_projects",
    "end_users",
    "end_user_capability_overrides",
    "end_user_org_relations",
    "end_user_position_roles",
    "end_user_sessions",
    "execution_logs",
    "external_search_configs",
    "external_tools",
    "knowledge_directories",
    "knowledge_document_chunks",
    "knowledge_documents",
    "knowledge_document_settings",
    "knowledge_resources",
    "organization_skill_releases",
    "organization_shortcut_schemes",
    "organizations",
    "org_quota_policies",
    "org_units",
    "page_collection_settings",
    "personal_knowledge_directories",
    "position_roles",
    "position_role_migrations",
    "position_role_audit_logs",
    "project_memories",
    "resource_comment_reactions",
    "resource_comments",
    "resource_feedback_notifications",
    "resource_grants",
    "resource_reactions",
    "site_profiles",
    "skill_distribution_members",
    "skill_distribution_releases",
    "skill_distributions",
    "skill_packages",
    "skill_releases",
    "skill_share_deliveries",
    "skill_shares",
    "skill_update_notifications",
    "skills",
    "token_usage_logs",
    "user_field_defs",
    "user_field_values",
    "user_identities",
    "user_invites",
    "user_quota_overrides",
    "user_quota_policies",
    "user_skills",
    "user_token_allocation_logs",
]

# Governance-layer collections partitioned by ``tenant_id`` (= main_id).
TENANT_GOVERNANCE_COLLECTIONS: list[str] = [
    "pii_policies",
    "risk_tiers",
    "autonomy_matrix",
    "gatekeeper_rules",
    "gate_events",
    "gate_approvals",
    "permission_grants",
    "approval_events",
    "quota_counters",
    # Written by both services (admin-api ``services/hooks_store.py`` and
    # chat-api ``app/dsh_runtime/hooks/store.py``); partitioned by ``tenant_id``.
    "hook_rules",
]

# Tombstones older than this are deleted on startup (T052 / decision 19).
TOMBSTONE_RETENTION = timedelta(days=30)


class _PurgeTaskStore:
    """In-memory task registry: ``{task_key: {status, progress, error}}``."""

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._main_id_to_task: dict[str, str] = {}

    def create(self, main_id: str, task_id: str) -> None:
        key = f"{main_id}:{task_id}"
        self._tasks[key] = {
            "status": "running",
            "progress": {"mongo": "pending", "vectors": "pending", "files": "pending"},
            "error": "",
        }
        self._main_id_to_task[main_id] = key

    def mark(self, key: str, phase: str, value: str) -> None:
        task = self._tasks.get(key)
        if task:
            task["progress"][phase] = value

    def finish(self, key: str, ok: bool, error: str = "") -> None:
        task = self._tasks.get(key)
        if task:
            task["status"] = "done" if ok else "failed"
            task["error"] = error

    def get(self, key: str) -> dict[str, Any] | None:
        return self._tasks.get(key)

    def get_for_main_id(self, main_id: str, task_id: str = "") -> dict[str, Any]:
        """Resolve the task for a main_id (and optional task_id).

        If ``task_id`` is empty, returns the most recent task created for
        this main_id.
        """
        if task_id:
            key = f"{main_id}:{task_id}"
        else:
            key = self._main_id_to_task.get(main_id, "")
        if not key:
            return None
        task = self._tasks.get(key)
        if task is None:
            return None
        return {
            "taskId": key.split(":", 1)[1] if ":" in key else key,
            "status": task["status"],
            "progress": task["progress"],
            "error": task["error"],
        }


_task_store = _PurgeTaskStore()


async def get_purge_status(main_id: str, task_id: str = "") -> dict[str, Any]:
    """Return the purge progress for a tenant.

    If no task has been started yet, check the tenant registry for a tombstone
    (``status == purged``) and report that. Otherwise fall back to the most
    recent task for this main_id.
    """
    result = _task_store.get_for_main_id(main_id, task_id)
    if result is not None:
        return result
    # No task in memory — check if the tenant row already records a purge.
    db = get_db()
    tenant = await db[TENANT_COLLECTION].find_one({"main_id": main_id}, {"status": 1, "purged_at": 1})
    if tenant and tenant.get("status") == "purged":
        return {
            "taskId": task_id or main_id,
            "status": "done",
            "progress": {"mongo": "done", "vectors": "done", "files": "done"},
            "error": "",
        }
    return {"taskId": task_id or main_id, "status": "unknown", "progress": {}, "error": ""}


# ---------------------------------------------------------------------------
# Phase implementations
# ---------------------------------------------------------------------------


async def _phase_mongo(main_id: str) -> None:
    db = get_db()
    for collection in TENANT_SCOPED_COLLECTIONS:
        result = await db[collection].delete_many({"main_id": main_id})
        if result.deleted_count:
            logger.info("purge %s: deleted %d row(s) from %s", main_id, result.deleted_count, collection)
    for collection in TENANT_GOVERNANCE_COLLECTIONS:
        result = await db[collection].delete_many({"tenant_id": main_id})
        if result.deleted_count:
            logger.info("purge %s: deleted %d governance row(s) from %s", main_id, result.deleted_count, collection)
    # NOTE: the tombstone (``status = purged``) is deliberately NOT written
    # here. FR-033 requires the tenant to stay ``archived`` if any phase fails,
    # so the marker is only set by ``run_purge`` once every phase succeeded.
    # Writing it here would mark a tenant purged whose vector/file cleanup
    # still had a chance to fail — see tests/test_tenant_purge.py.


async def _list_knowledge_document_ids(main_id: str) -> list[str]:
    db = get_db()
    docs: list[str] = []
    async for doc in db["knowledge_documents"].find({"main_id": main_id}, {"document_id": 1}):
        document_id = doc.get("document_id")
        if document_id:
            docs.append(str(document_id))
    return docs


async def _phase_vectors(main_id: str) -> None:
    """Ask the document-parser service to remove this tenant's Weaviate chunks.

    The parser service owns the vector store; this phase only triggers its
    maintenance endpoint. Failures propagate so ``run_purge`` can honour
    FR-033 — a tenant whose vectors survived must not be marked purged.
    """
    import json as _json
    import urllib.request

    document_ids = await _list_knowledge_document_ids(main_id)
    if not document_ids:
        return
    if not settings.document_processing_service_token:
        raise RuntimeError(
            "document_processing_service_token is not configured, so vector "
            f"cleanup for {len(document_ids)} document(s) cannot be performed"
        )

    base_url = settings.document_processing_base_url.rstrip("/")
    failures: list[str] = []
    for document_id in document_ids:
        url = f"{base_url}/vectors/documents/delete"
        body = _json.dumps({"mainId": main_id, "documentId": document_id}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.document_processing_service_token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30.0) as response:  # noqa: S310
                response.read()
        except Exception as exc:
            logger.warning(
                "purge %s: vector delete failed for document %s: %s",
                main_id,
                document_id,
                exc,
            )
            failures.append(f"{document_id}: {exc}")

    if failures:
        raise RuntimeError(f"vector delete failed for {len(failures)}/{len(document_ids)} document(s)")


async def _phase_files(main_id: str) -> None:
    """Remove local storage directories for knowledge documents and avatars.

    Layout (see config):
    - knowledge documents: ``{knowledge_local_storage_dir}/{main_id}/...``
    - admin avatars:       ``{admin_static_dir}/admin-avatars/{safe(main_id)}/``
    OSS-backed storage is left in place (the bucket has its own lifecycle
    policy); only local-disk files are removed here.
    """
    import shutil
    from pathlib import Path

    from app.api.routes.auth import _safe_path_part

    removed = 0
    knowledge_root = Path(settings.knowledge_local_storage_dir) / main_id
    if knowledge_root.exists():
        shutil.rmtree(knowledge_root)
        removed += 1
        logger.info("purge %s: removed knowledge storage directory %s", main_id, knowledge_root)

    avatars_root = Path(settings.admin_static_dir) / "admin-avatars"
    if avatars_root.exists():
        # Derive the directory exactly the way the writer does
        # (``auth.py`` stores avatars under ``_safe_path_part(main_id)``), instead
        # of guessing a ``{main_id}-{uuid}`` shape. A prefix match would be
        # unsafe and a ``f"{main_id}-"`` match never fires because main_id
        # already ends in ``-<hex>`` while the sanitiser strips nothing.
        avatar_dir = avatars_root / _safe_path_part(main_id, "default")
        if avatar_dir.is_dir() and avatar_dir.parent == avatars_root:
            shutil.rmtree(avatar_dir)
            removed += 1
            logger.info("purge %s: removed avatar directory %s", main_id, avatar_dir.name)
    if removed == 0:
        logger.info("purge %s: no local files found to remove", main_id)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def run_purge(main_id: str, task_id: str, actor: str) -> None:
    """Run the full purge pipeline for one tenant (called as a background task)."""
    _task_store.create(main_id, task_id)
    key = f"{main_id}:{task_id}"

    # FR-028: re-check at execution time, not just when the request was
    # accepted. The tenant may have been restored between the API call and this
    # background task actually starting (restore_tenant() flips it to active),
    # and purging an active tenant would destroy live data.
    db = get_db()
    tenant = await db[TENANT_COLLECTION].find_one({"main_id": main_id}, {"status": 1})
    if tenant is None:
        logger.error("purge %s: tenant row not found; aborting", main_id)
        _task_store.finish(key, False, "tenant not found")
        return
    if tenant.get("status") != "archived":
        logger.error(
            "purge %s: refusing to purge a tenant in status %r (only archived tenants may be purged)",
            main_id,
            tenant.get("status"),
        )
        _task_store.finish(key, False, f"tenant is not archived (status={tenant.get('status')!r})")
        return

    errors: list[str] = []

    _task_store.mark(key, "mongo", "running")
    try:
        await _phase_mongo(main_id)
        _task_store.mark(key, "mongo", "done")
    except Exception as exc:
        logger.exception("purge %s: mongo phase failed", main_id)
        errors.append(f"mongo: {exc}")
        _task_store.mark(key, "mongo", "failed")

    _task_store.mark(key, "vectors", "running")
    try:
        await _phase_vectors(main_id)
        _task_store.mark(key, "vectors", "done")
    except Exception as exc:
        logger.exception("purge %s: vectors phase failed", main_id)
        errors.append(f"vectors: {exc}")
        _task_store.mark(key, "vectors", "failed")

    _task_store.mark(key, "files", "running")
    try:
        await _phase_files(main_id)
        _task_store.mark(key, "files", "done")
    except Exception as exc:
        logger.exception("purge %s: files phase failed", main_id)
        errors.append(f"files: {exc}")
        _task_store.mark(key, "files", "failed")

    ok = not errors
    error_text = "; ".join(errors)
    _task_store.finish(key, ok, error_text)
    logger.info("purge %s finished ok=%s errors=%s", main_id, ok, error_text)

    if not ok:
        # FR-033: a partial failure MUST abort and leave the tenant ``archived``
        # with the reason recorded — it must NOT become a tombstone, otherwise
        # the 30-day reaper destroys the only evidence of the failure.
        await _record_purge_failure(main_id, error_text)
        return

    # All phases succeeded: write the tombstone. Normally ``_phase_mongo``
    # already did this; repeat it here so the row is purged even if a later
    # (vectors/files) phase was the one that raced ahead.
    db = get_db()
    await db[TENANT_COLLECTION].update_one(
        {"main_id": main_id, "status": {"$ne": "purged"}},
        {"$set": {"status": "purged", "purged_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}},
    )


async def _record_purge_failure(main_id: str, error_text: str) -> None:
    """FR-033: keep the tenant ``archived`` and record why the purge failed.

    Only transitions rows that have not already become a tombstone, so a
    concurrent success cannot be downgraded back to ``archived``.
    """
    now = datetime.now(timezone.utc)
    db = get_db()
    result = await db[TENANT_COLLECTION].update_one(
        {"main_id": main_id, "status": {"$ne": "purged"}},
        {
            "$set": {
                "status": "archived",
                "archive_reason": f"purge failed: {error_text}"[:500],
                "updated_at": now,
            },
            "$unset": {"purged_at": ""},
        },
    )
    if result.matched_count:
        logger.warning("purge %s: failed, tenant kept archived: %s", main_id, error_text)
    else:
        logger.error(
            "purge %s: failed after the tenant row was already purged; "
            "failure could not be recorded on the tenant: %s",
            main_id,
            error_text,
        )


async def cleanup_expired_tombstones() -> int:
    """Delete tenant rows whose ``purged_at`` is older than the retention window.

    Called from ``on_startup`` so a fresh boot reaps stale tombstones without
    needing a separate scheduler. Returns the number of rows removed.
    """
    db = get_db()
    cutoff = datetime.now(timezone.utc) - TOMBSTONE_RETENTION
    result = await db[TENANT_COLLECTION].delete_many(
        {"status": "purged", "purged_at": {"$lt": cutoff}}
    )
    if result.deleted_count:
        logger.info("cleaned up %d expired tenant tombstone(s)", result.deleted_count)
    return result.deleted_count


async def system_health() -> dict[str, Any]:
    """T051: read-only service health (same shape as /setup/status services)."""
    from app.api.routes.setup import _deployment_services

    services = await _deployment_services()
    return {"services": [s.model_dump() if hasattr(s, "model_dump") else s for s in services]}
