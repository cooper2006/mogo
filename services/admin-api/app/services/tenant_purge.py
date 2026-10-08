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
# only. Cross-check it against the collection constants used by
# ``app.services.setup_cleanup.SETUP_SCOPED_COLLECTIONS``
# (``services/chat-api/app/**``) before adding a collection to either service,
# otherwise tenant data survives a purge (SC-005).
TENANT_SCOPED_COLLECTIONS: list[str] = [
    "admin_account_groups",
    "admin_accounts",
    "admin_login_challenges",
    # QF-350~354: refresh tokens, recovery tokens, and active sessions
    # are all partitioned by main_id and must be purged with the tenant.
    "admin_refresh_tokens",
    "admin_recovery_tokens",
    "admin_sessions",
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
    "session_snapshots",
    # 002 FR-8: reversible secret placeholders for session snapshots. Persisted in
    # chat-api (services/session_versioning/snapshot.py) and the most sensitive data
    # a tenant can hold — purging a tenant MUST remove it (001 audit, 2026-10-03).
    "session_secret_refs",
    # 011 ①: content-fingerprinted experience fragments (tenant-partitioned,
    # upsert by fingerprint). Tenant purge must wipe accumulated cross-pass state.
    "experience_fragments",
    # 011 ②: generated skill drafts + MR flags written for 004 consumption.
    "skill_drafts",
    # 017: three-scope memory records (tenant-partitioned, scope-filtered reads).
    "memories",
    # 019: harness thickness profiles (tenant-partitioned via main_id).
    "harness_profiles",
    "site_profiles",
    # 013: IM channel <-> MOGO session bindings, partitioned by tenant_id
    # (chat-api PersistedSessionBindingRegistry, FR-10 persistence).
    "im_channels",
    "im_session_bindings",
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
    "user_shortcut_preferences",
    "user_skills",
    "user_token_allocation_logs",
    # 020 FR-032: cross-replica purge progress (main_id + task_id keyed).
    "tenant_purge_progress",
]

# Governance-layer collections partitioned by ``tenant_id`` (= main_id).
TENANT_GOVERNANCE_COLLECTIONS: list[str] = [
    "agent_kernel_bindings",
    "business_entity_index",
    "pii_policies",
    "risk_tiers",
    "autonomy_matrix",
    "enterprise_authoritative_deliveries",
    "gatekeeper_rules",
    "gate_events",
    "gate_approvals",
    "permission_grants",
    "approval_events",
    "presentation_generation_jobs",
    "quota_counters",
    "runtime_profile_versions",
    "runtime_profile_audit",
    # Written by both services (admin-api ``services/hooks_store.py`` and
    # chat-api ``app/dsh_runtime/hooks/store.py``); partitioned by ``tenant_id``.
    "hook_rules",
    # chat-api projected tool outcomes (011 reader source); partitioned by tenant_id.
    "kernel_event_projections",
    # 011 low-adoption store, tenant-partitioned by (tenant_id, skill_key);
    # the 016 market side reads ``marked_low_quality`` from here.
    "skill_adoption",
    # 016 effect-score daily buckets, partitioned by (main_id, skill_key, date);
    # written by chat-api (skill execution) and read by admin-api's scanner.
    "skill_quality_metrics",
    # OQ-6 correction source: product-edit events written by chat-api's
    # ``POST /documents/save-blueprint``; partitioned by tenant_id.
    "skill_product_edit_events",
    # chat-api tool execution receipts (OQ-6 success source); partitioned by tenant_id.
    "enterprise_action_receipts",
]

# Collections with **no** tenant key of their own, purged by resolving their
# parent rows (see ``_purge_key_only_collections``).
#
# ``session_shares`` (chat-api ``services/session_versioning/share.py``)
# persists only ``share_id`` / ``session_id`` / ``snapshot_id`` — the
# ``main_id`` is assembled into the HTTP response, never stored. It is matched
# through ``chat_sessions.main_id``, so it must be swept BEFORE the scoped pass
# deletes those sessions. Fixing this properly means stamping the tenant on
# write (a schema change); cascading here keeps the purge complete meanwhile.
#
# ``session_snapshots`` is *not* in this list: ``dsh_session_versioning.py``
# sets ``document["tenant_id"] = main_id`` before insert, so it is purged by the
# normal ``TENANT_SCOPED_COLLECTIONS`` sweep.
TENANT_ORPHANED_COLLECTIONS: list[str] = [
    "session_shares",
    # 016 canary rollouts: keyed by ``skill_id`` with a ``target_tenants``
    # array (no scalar tenant key), so a plain keyed sweep cannot match it.
    "skill_rollouts",
]

# Tombstones older than this are deleted on startup (T052 / decision 19).
TOMBSTONE_RETENTION = timedelta(days=30)


class _PurgeTaskStore:
    """Purge task registry: Mongo-backed (cross-replica) + in-memory fallback.

    FR-032 (020 residual): progress is now persisted to the
    ``tenant_purge_progress`` collection so a status query from a *different*
    admin-api replica still sees in-flight and completed purges. The in-memory
    map is kept as a fast local cache and as an offline fallback: when Mongo is
    unavailable, progress is still tracked in-process and queries honestly
    degrade to "unknown" instead of fabricating state.
    """

    # Enough to keep recent history for every tenant in a large deployment
    # without letting the dict grow unbounded in a long-lived process.
    _MAX_TASKS = 512

    PURGE_PROGRESS_COLLECTION = "tenant_purge_progress"

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._main_id_to_task: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Mongo persistence (best-effort; memory cache is always updated first)
    # ------------------------------------------------------------------

    async def _upsert(self, tenant_id: str, task_id: str, task: dict[str, Any]) -> None:
        key = f"{tenant_id}:{task_id}"
        try:
            db = get_db()
            now = datetime.now(timezone.utc)
            doc = {
                "tenant_id": tenant_id,
                "task_id": task_id,
                "status": task["status"],
                "progress": task["progress"],
                "error": task.get("error", ""),
                "updated_at": now,
            }
            if "started_at" not in task:
                doc["started_at"] = now
            await db[self.PURGE_PROGRESS_COLLECTION].update_one(
                {"tenant_id": tenant_id, "task_id": task_id},
                {"$set": doc, "$setOnInsert": {"started_at": now}},
                upsert=True,
            )
        except Exception:
            # DB unavailable: degrade to in-memory only (never fabricate a
            # completed state; get_purge_status will report what it truly has).
            logger.warning("purge_progress %s: mongo upsert failed; in-memory only", key)

    # ------------------------------------------------------------------
    # Registry operations
    # ------------------------------------------------------------------

    def create(self, tenant_id: str, task_id: str) -> None:
        key = f"{tenant_id}:{task_id}"
        while len(self._tasks) >= self._MAX_TASKS:
            # dicts preserve insertion order, so the first key is the oldest.
            oldest = next(iter(self._tasks), None)
            if oldest is None:  # pragma: no cover - unreachable, guards the loop
                break
            self._evict(oldest)
        while len(self._main_id_to_task) >= self._MAX_TASKS:
            oldest_main = next(iter(self._main_id_to_task), None)
            if oldest_main is None:  # pragma: no cover - unreachable
                break
            self._main_id_to_task.pop(oldest_main, None)
        self._tasks[key] = {
            "status": "running",
            "progress": {"mongo": "pending", "vectors": "pending", "files": "pending"},
            "error": "",
            "started_at": datetime.now(timezone.utc),
        }
        self._main_id_to_task[tenant_id] = key

    def _evict(self, key: str) -> None:
        """Drop one task, also clearing any index entry that points at it.

        Without this the index would keep referencing a task that no longer
        exists, and ``get_for_main_id`` would report ``unknown`` for a tenant
        whose purge we simply forgot about.
        """
        self._tasks.pop(key, None)
        stale = [m for m, k in self._main_id_to_task.items() if k == key]
        for tenant_id in stale:
            self._main_id_to_task.pop(tenant_id, None)

    def mark(self, key: str, phase: str, value: str) -> None:
        task = self._tasks.get(key)
        if task:
            task["progress"][phase] = value

    async def mark_persisted(self, tenant_id: str, task_id: str, phase: str, value: str) -> None:
        """Mark a phase and persist to Mongo (FR-032 cross-replica)."""
        key = f"{tenant_id}:{task_id}"
        task = self._tasks.get(key)
        if task:
            task["progress"][phase] = value
        await self._upsert(tenant_id, task_id, task or {"status": "running", "progress": {phase: value}})

    def finish(self, key: str, ok: bool, error: str = "") -> None:
        task = self._tasks.get(key)
        if task:
            task["status"] = "done" if ok else "failed"
            task["error"] = error

    async def finish_persisted(self, tenant_id: str, task_id: str, ok: bool, error: str = "") -> None:
        """Finish a task and persist the final state to Mongo (FR-032)."""
        key = f"{tenant_id}:{task_id}"
        task = self._tasks.get(key)
        if task:
            task["status"] = "done" if ok else "failed"
            task["error"] = error
        await self._upsert(tenant_id, task_id, task or {"status": "done" if ok else "failed", "progress": {}, "error": error})

    def get(self, key: str) -> dict[str, Any] | None:
        return self._tasks.get(key)

    def get_for_main_id(self, tenant_id: str, task_id: str = "") -> dict[str, Any] | None:
        """Resolve the in-memory task for a main_id (and optional task_id)."""
        if task_id:
            key = f"{tenant_id}:{task_id}"
        else:
            key = self._main_id_to_task.get(tenant_id, "")
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

    async def get_persisted(self, tenant_id: str, task_id: str = "") -> dict[str, Any] | None:
        """Read the last persisted purge progress from Mongo (FR-032).

        When ``task_id`` is empty, returns the most recently updated document
        for this main_id. Returns None when Mongo is unavailable or no
        document exists — callers fall back to the tenant tombstone.
        """
        try:
            db = get_db()
        except Exception:
            return None
        try:
            coll = db[self.PURGE_PROGRESS_COLLECTION]
            if task_id:
                doc = await coll.find_one({"tenant_id": tenant_id, "task_id": task_id})
            else:
                doc = await coll.find(
                    {"tenant_id": tenant_id}
                ).sort("updated_at", -1).to_list(length=1)
                doc = doc[0] if doc else None
        except Exception:
            return None
        if doc is None:
            return None
        return {
            "taskId": str(doc.get("task_id") or task_id),
            "status": doc.get("status", "unknown"),
            "progress": dict(doc.get("progress") or {}),
            "error": doc.get("error", ""),
        }


_task_store = _PurgeTaskStore()


async def get_purge_status(tenant_id: str, task_id: str = "") -> dict[str, Any]:
    """Return the purge progress for a tenant.

    Resolution order (FR-032): in-memory cache (this replica, in-flight) →
    Mongo ``tenant_purge_progress`` (any replica) → tenant tombstone.
    """
    result = _task_store.get_for_main_id(tenant_id, task_id)
    if result is not None:
        return result
    # No task in this process — check Mongo (another replica may be mid-purge
    # or finished a purge this replica never saw).
    persisted = await _task_store.get_persisted(tenant_id, task_id)
    if persisted is not None:
        return persisted
    # No task anywhere — check if the tenant row already records a purge.
    db = get_db()
    tenant = await db[TENANT_COLLECTION].find_one({"tenant_id": tenant_id}, {"status": 1, "purged_at": 1})
    if tenant and tenant.get("status") == "purged":
        return {
            "taskId": task_id or tenant_id,
            "status": "done",
            "progress": {"mongo": "done", "vectors": "done", "files": "done"},
            "error": "",
        }
    return {"taskId": task_id or tenant_id, "status": "unknown", "progress": {}, "error": ""}


# ---------------------------------------------------------------------------
# Phase implementations
# ---------------------------------------------------------------------------


async def _phase_mongo(tenant_id: str) -> None:
    db = get_db()
    # Key-only collections are resolved through the tenant's sessions, so they
    # must be swept BEFORE the scoped pass deletes ``chat_sessions``.
    await _purge_key_only_collections(db, tenant_id)
    for collection in TENANT_SCOPED_COLLECTIONS:
        result = await db[collection].delete_many({"tenant_id": tenant_id})
        if result.deleted_count:
            logger.info("purge %s: deleted %d row(s) from %s", tenant_id, result.deleted_count, collection)
    for collection in TENANT_GOVERNANCE_COLLECTIONS:
        result = await db[collection].delete_many({"tenant_id": tenant_id})
        if result.deleted_count:
            logger.info("purge %s: deleted %d governance row(s) from %s", tenant_id, result.deleted_count, collection)
    # NOTE: the tombstone (``status = purged``) is deliberately NOT written
    # here. FR-033 requires the tenant to stay ``archived`` if any phase fails,
    # so the marker is only set by ``run_purge`` once every phase succeeded.
    # Writing it here would mark a tenant purged whose vector/file cleanup
    # still had a chance to fail — see tests/test_tenant_purge.py.


async def _purge_key_only_collections(db: Any, tenant_id: str) -> None:
    """Delete from collections that carry no tenant key of their own.

    These rows cannot be matched by ``main_id`` directly, so they are resolved
    through the tenant's own rows first. This must run **before** the scoped
    sweep: it reads ``chat_sessions`` to enumerate children, and the sweep
    deletes those rows.

    ``session_shares`` is the case in point — ``ShareStore`` persists only
    ``share_id`` / ``session_id`` / ``snapshot_id`` (the ``main_id`` is
    assembled into the HTTP response, never stored). Left alone, a purged
    tenant's share tokens would survive indefinitely with no way to attribute
    or revoke them.
    """
    if not TENANT_ORPHANED_COLLECTIONS:
        return

    session_ids = await db["chat_sessions"].distinct("_id", {"tenant_id": tenant_id})
    if not session_ids:
        return
    for collection in TENANT_ORPHANED_COLLECTIONS:
        result = await db[collection].delete_many({"session_id": {"$in": list(session_ids)}})
        if result.deleted_count:
            logger.info(
                "purge %s: deleted %d orphan row(s) from %s (via %d session(s))",
                tenant_id,
                result.deleted_count,
                collection,
                len(session_ids),
            )


async def _list_knowledge_document_ids(tenant_id: str) -> list[str]:
    db = get_db()
    docs: list[str] = []
    async for doc in db["knowledge_documents"].find({"tenant_id": tenant_id}, {"document_id": 1}):
        document_id = doc.get("document_id")
        if document_id:
            docs.append(str(document_id))
    return docs


async def _phase_vectors(tenant_id: str) -> None:
    """Ask the document-parser service to remove this tenant's Weaviate chunks.

    The parser service owns the vector store; this phase only triggers its
    maintenance endpoint. Failures propagate so ``run_purge`` can honour
    FR-033 — a tenant whose vectors survived must not be marked purged.
    """
    import json as _json
    import urllib.request

    document_ids = await _list_knowledge_document_ids(tenant_id)
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
        body = _json.dumps({"mainId": tenant_id, "documentId": document_id}).encode("utf-8")
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
                tenant_id,
                document_id,
                exc,
            )
            failures.append(f"{document_id}: {exc}")

    if failures:
        raise RuntimeError(f"vector delete failed for {len(failures)}/{len(document_ids)} document(s)")


async def _phase_files(tenant_id: str) -> None:
    """Remove local storage directories for knowledge documents and avatars.

    Layout (see config):
    - knowledge documents: ``{knowledge_local_storage_dir}/{tenant_id}/...``
    - admin avatars:       ``{admin_static_dir}/admin-avatars/{safe(main_id)}/``
    OSS-backed storage is left in place (the bucket has its own lifecycle
    policy); only local-disk files are removed here.
    """
    import shutil
    from pathlib import Path

    from app.api.routes.auth import _safe_path_part

    removed = 0
    knowledge_root = Path(settings.knowledge_local_storage_dir) / tenant_id
    if knowledge_root.exists():
        shutil.rmtree(knowledge_root)
        removed += 1
        logger.info("purge %s: removed knowledge storage directory %s", tenant_id, knowledge_root)

    avatars_root = Path(settings.admin_static_dir) / "admin-avatars"
    if avatars_root.exists():
        # Derive the directory exactly the way the writer does
        # (``auth.py`` stores avatars under ``_safe_path_part(main_id)``), instead
        # of guessing a ``{tenant_id}-{uuid}`` shape. A prefix match would be
        # unsafe and a ``f"{tenant_id}-"`` match never fires because main_id
        # already ends in ``-<hex>`` while the sanitiser strips nothing.
        avatar_dir = avatars_root / _safe_path_part(tenant_id, "default")
        if avatar_dir.is_dir() and avatar_dir.parent == avatars_root:
            shutil.rmtree(avatar_dir)
            removed += 1
            logger.info("purge %s: removed avatar directory %s", tenant_id, avatar_dir.name)
    if removed == 0:
        logger.info("purge %s: no local files found to remove", tenant_id)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def run_purge(tenant_id: str, task_id: str, actor: str) -> None:
    """Run the full purge pipeline for one tenant (called as a background task)."""
    _task_store.create(tenant_id, task_id)

    # FR-028: re-check at execution time, not just when the request was
    # accepted. The tenant may have been restored between the API call and this
    # background task actually starting (restore_tenant() flips it to active),
    # and purging an active tenant would destroy live data.
    db = get_db()
    tenant = await db[TENANT_COLLECTION].find_one({"tenant_id": tenant_id}, {"status": 1})
    if tenant is None:
        logger.error("purge %s: tenant row not found; aborting", tenant_id)
        await _task_store.finish_persisted(tenant_id, task_id, False, "tenant not found")
        return
    if tenant.get("status") != "archived":
        logger.error(
            "purge %s: refusing to purge a tenant in status %r (only archived tenants may be purged)",
            tenant_id,
            tenant.get("status"),
        )
        await _task_store.finish_persisted(
            tenant_id, task_id, False, f"tenant is not archived (status={tenant.get('status')!r})"
        )
        return

    errors: list[str] = []

    await _task_store.mark_persisted(tenant_id, task_id, "mongo", "running")
    try:
        await _phase_mongo(tenant_id)
        await _task_store.mark_persisted(tenant_id, task_id, "mongo", "done")
    except Exception as exc:
        logger.exception("purge %s: mongo phase failed", tenant_id)
        errors.append(f"mongo: {exc}")
        await _task_store.mark_persisted(tenant_id, task_id, "mongo", "failed")

    await _task_store.mark_persisted(tenant_id, task_id, "vectors", "running")
    try:
        await _phase_vectors(tenant_id)
        await _task_store.mark_persisted(tenant_id, task_id, "vectors", "done")
    except Exception as exc:
        logger.exception("purge %s: vectors phase failed", tenant_id)
        errors.append(f"vectors: {exc}")
        await _task_store.mark_persisted(tenant_id, task_id, "vectors", "failed")

    await _task_store.mark_persisted(tenant_id, task_id, "files", "running")
    try:
        await _phase_files(tenant_id)
        await _task_store.mark_persisted(tenant_id, task_id, "files", "done")
    except Exception as exc:
        logger.exception("purge %s: files phase failed", tenant_id)
        errors.append(f"files: {exc}")
        await _task_store.mark_persisted(tenant_id, task_id, "files", "failed")

    ok = not errors
    error_text = "; ".join(errors)
    await _task_store.finish_persisted(tenant_id, task_id, ok, error_text)
    logger.info("purge %s finished ok=%s errors=%s", tenant_id, ok, error_text)

    if not ok:
        # FR-033: a partial failure MUST abort and leave the tenant ``archived``
        # with the reason recorded — it must NOT become a tombstone, otherwise
        # the 30-day reaper destroys the only evidence of the failure.
        await _record_purge_failure(tenant_id, error_text)
        # SC-007: the failed purge is a lifecycle operation and must be
        # traceable even though the tenant survives as ``archived``.
        await _audit_purge(tenant_id, actor, "failure", {"error": error_text[:500]})
        return

    # SC-007: the successful purge is the last lifecycle operation for this
    # tenant; the row itself becomes a tombstone, so the audit log is the only
    # remaining evidence that the purge happened.
    await _audit_purge(tenant_id, actor, "success")

    # All phases succeeded: write the tombstone. Normally ``_phase_mongo``
    # already did this; repeat it here so the row is purged even if a later
    # (vectors/files) phase was the one that raced ahead.
    db = get_db()
    await db[TENANT_COLLECTION].update_one(
        {"tenant_id": tenant_id, "status": {"$ne": "purged"}},
        {"$set": {"status": "purged", "purged_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}},
    )


async def _audit_purge(tenant_id: str, actor: str, result: str, detail: dict[str, Any] | None = None) -> None:
    """SC-007: record the purge as a lifecycle operation.

    ``tenant_lifecycle`` is imported lazily — it pulls in the audit repository,
    and importing it at module scope would couple the purge module to it.
    """
    from app.services import tenant_lifecycle

    await tenant_lifecycle.record_tenant_audit(
        tenant_id, actor, "purge", tenant_id, result, detail
    )


async def _record_purge_failure(tenant_id: str, error_text: str) -> None:
    """FR-033: keep the tenant ``archived`` and record why the purge failed.

    Only transitions rows that have not already become a tombstone, so a
    concurrent success cannot be downgraded back to ``archived``.
    """
    now = datetime.now(timezone.utc)
    db = get_db()
    result = await db[TENANT_COLLECTION].update_one(
        {"tenant_id": tenant_id, "status": {"$ne": "purged"}},
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
        logger.warning("purge %s: failed, tenant kept archived: %s", tenant_id, error_text)
    else:
        logger.error(
            "purge %s: failed after the tenant row was already purged; "
            "failure could not be recorded on the tenant: %s",
            tenant_id,
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
