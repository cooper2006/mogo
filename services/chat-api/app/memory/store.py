"""In-memory + MongoDB-backed memory store (017 US1 / FR-5).

Memories are keyed by ``(tenant_id, memory_id)`` and tagged with a scope
(``personal`` / ``project`` / ``department``). The store itself is intentionally
simple — the scope/visibility logic lives in ``scope.py`` and the RAG
integration in ``retrieval.py``.

D4: ``workspace_id`` / ``org_id`` are gone. A project memory carries
``project_id`` + ``project_owner_id`` (N1), a department memory carries
``department_id``. There is no runtime alias or field-level fallback; old rows
are converted offline by ``scripts/migrate_017_scopes.py``.
"""

from __future__ import annotations
from app.infrastructure.observability.config import log_print

import uuid
from typing import Any, Optional

from app.core.config import get_settings
from app.core.db import get_db
from app.core.tenant import resolve_tenant_id
from app.memory.lifecycle import touch
from app.memory.scope import Memory, MemoryScope
from app.memory.tiering import SUMMARY_REFRESH_DAYS_DEFAULT, tier_content
from app.memory.viewer import MemoryViewerContext

COLLECTION = "memories"


class MemoryTooLargeError(ValueError):
    """Raised when non-tierable content exceeds the FR-16 hard byte limit."""


def _configured_refresh_days() -> int:
    """FR-15 staleness window, taken from configuration (falls back to default).

    ``MEMORY_SUMMARY_REFRESH_DAYS`` used to be a dead setting: operators could
    set it and nothing read it, so the hard-coded ``30`` always won (R3 audit,
    2026-10-06). This is now the single resolution point.
    """
    try:
        value = int(get_settings().MEMORY_SUMMARY_REFRESH_DAYS)
    except Exception as exc:
        log_print(f"[memory.store._configured_refresh_days] suppressed {type(exc).__name__}: {exc}", flush=True)
        return SUMMARY_REFRESH_DAYS_DEFAULT
    return value if value > 0 else SUMMARY_REFRESH_DAYS_DEFAULT


def _now_seconds() -> float:
    import time
    return time.time()


def _row_to_memory(row: dict[str, Any]) -> Memory:
    memory = Memory(
        memory_id=str(row.get("memory_id") or row.get("_id") or ""),
        content=str(row.get("content") or ""),
        scope=str(row.get("scope") or MemoryScope.PERSONAL.value),
        owner_id=str(row.get("owner_id") or ""),
        project_id=str(row.get("project_id") or ""),
        tenant_id=str(row.get("tenant_id") or "default"),
        department_id=str(row.get("department_id") or ""),
        created_at=float(row.get("created_at") or 0.0),
        last_accessed_at=float(row.get("last_accessed_at") or 0.0),
        l0_summary=str(row.get("l0_summary") or ""),
        l1_overview=str(row.get("l1_overview") or ""),
        l2_raw=str(row.get("l2_raw") or row.get("content") or ""),
        tierable=bool(row.get("tierable", True)),
        summary_generated_at=float(row.get("summary_generated_at") or 0.0),
        summary_refresh_days=int(row.get("summary_refresh_days") or _configured_refresh_days()),
        source_session_id=str(row.get("source_session_id") or ""),
        source_type=str(row.get("source_type") or ""),
        project_owner_id=str(row.get("project_owner_id") or ""),
    )
    memory.archived = bool(row.get("archived") or False)
    return memory


def _lazy_complete_tiers(memory: Memory) -> None:
    """T022 read-time lazy fallback slot (FR-15).

    No production LLM summarizer is injected at this layer, so ``tier_content``
    is invoked with ``summarizer=None`` (a safe no-op that keeps the read-time
    path wired and observable). Write-time ``NoopSessionSummarizer`` already
    guarantees L0 is non-empty for sedimented memories; a real summarizer can
    be threaded in here without changing the call sites.
    """
    result = tier_content(
        memory.content,
        None,
        l0_summary=memory.l0_summary,
        l1_overview=memory.l1_overview,
        tierable=memory.tierable,
        summary_generated_at=memory.summary_generated_at,
        refresh_days=memory.summary_refresh_days,
    )
    memory.l0_summary = result.l0_summary
    memory.l1_overview = result.l1_overview
    memory.l2_raw = result.l2_raw
    memory.tierable = result.tierable
    memory.summary_generated_at = result.summary_generated_at


class MemoryStore:
    """Simple MongoDB-backed store for the three-scope memory layer."""

    async def save(
        self,
        *,
        content: str,
        owner_id: str,
        tenant_id: str,
        project_id: str = "",
        project_owner_id: str = "",
        department_id: str = "",
        scope: str = MemoryScope.PERSONAL.value,
        memory_id: str = "",
        l0_summary: str = "",
        l1_overview: str = "",
        l2_raw: str = "",
        tierable: bool = True,
        summary_generated_at: float = 0.0,
        summary_refresh_days: int = 0,
        source_session_id: str = "",
        source_type: str = "",
    ) -> Memory:
        """Upsert a memory record (create path). Returns the saved ``Memory``.

        Density tiers (FR-13) are persisted alongside the raw content. Non-
        tierable content that exceeds the FR-16 hard limit is rejected rather
        than silently truncated.

        This is the **create** path only: ``replace_one(..., upsert=True)``
        replaces the whole document. Incremental promotion / edits must use
        :meth:`update_fields` instead (D-6).
        """
        mem_id = str(memory_id or uuid.uuid4().hex)
        now = _now_seconds()
        summary_refresh_days = summary_refresh_days or _configured_refresh_days()
        hard_max = int(get_settings().MEMORY_L2_HARD_MAX_BYTES)
        content_bytes = len(content.encode("utf-8", errors="replace"))
        if not tierable and content_bytes > hard_max:
            raise MemoryTooLargeError(
                f"memory of {content_bytes} bytes is not tierable and exceeds the "
                f"hard limit of {hard_max} bytes; refuse to persist"
            )
        db = get_db()
        if db is None:
            return Memory(
                memory_id=mem_id,
                content=content,
                scope=scope,
                owner_id=owner_id,
                project_id=project_id,
                tenant_id=tenant_id,
                department_id=department_id,
                created_at=now,
                last_accessed_at=now,
                l0_summary=l0_summary,
                l1_overview=l1_overview,
                l2_raw=l2_raw or content,
                tierable=tierable,
                summary_generated_at=summary_generated_at,
                summary_refresh_days=summary_refresh_days,
                source_session_id=source_session_id,
                source_type=source_type,
                project_owner_id=project_owner_id,
            )
        tenant_id = resolve_tenant_id(tenant_id)
        doc: dict[str, Any] = {
            "memory_id": mem_id,
            "content": content,
            "scope": scope,
            "owner_id": owner_id,
            "project_id": project_id,
            "project_owner_id": project_owner_id,
            "tenant_id": tenant_id,
            "department_id": department_id,
            "created_at": now,
            "last_accessed_at": now,
            "l0_summary": l0_summary,
            "l1_overview": l1_overview,
            "l2_raw": l2_raw or content,
            "tierable": tierable,
            "summary_generated_at": summary_generated_at,
            "summary_refresh_days": summary_refresh_days,
            "source_session_id": source_session_id,
            "source_type": source_type,
        }
        await db[COLLECTION].replace_one(
            {"memory_id": mem_id, "tenant_id": tenant_id},
            doc,
            upsert=True,
        )
        return _row_to_memory(doc)

    async def update_fields(
        self, *, tenant_id: str, memory_id: str, **fields: Any
    ) -> bool:
        """D-6: incremental ``$set`` update, never a full-document replace.

        Used by promote (and any partial edit) so L0/L1/L2, provenance,
        ``archived`` and ``project_owner_id`` survive. The query is always
        tenant-scoped. Returns True when a document was matched.
        """
        if not fields:
            return False
        tenant_id = resolve_tenant_id(tenant_id)
        db = get_db()
        if db is None:
            return False
        result = await db[COLLECTION].update_one(
            {"memory_id": memory_id, "tenant_id": tenant_id},
            {"$set": fields},
        )
        return bool(getattr(result, "matched_count", 0))

    async def list_for_viewer(
        self,
        *,
        viewer: MemoryViewerContext,
        top_n: int = 20,
    ) -> list[Memory]:
        """Return memories visible to ``viewer`` (tenant-bounded, FR-2).

        Visibility is delegated to ``scope_filter``/``visible_to`` with the
        server-built ``MemoryViewerContext``; no scattered identity kwargs.
        """
        from app.memory.retrieval import scope_filter

        tenant_id = resolve_tenant_id(viewer.tenant_id)
        db = get_db()
        if db is None or not viewer.is_valid:
            return []
        rows = await db[COLLECTION].find({"tenant_id": tenant_id}).to_list(length=500)
        memories = [_row_to_memory(r) for r in rows]
        filtered = scope_filter(memories, viewer=viewer)
        # Sort: department > project > personal, then recency.
        weight = {
            MemoryScope.DEPARTMENT.value: 3,
            MemoryScope.PROJECT.value: 2,
            MemoryScope.PERSONAL.value: 1,
        }
        filtered.sort(
            key=lambda m: (weight.get(m.scope, 0), m.last_accessed_at or 0),
            reverse=True,
        )
        result = filtered[:top_n]

        # H-2: accessing a memory resets its decay timer. lifecycle exposes
        # ``touch(last_accessed_at, now)`` as a module function (MemoryLifecycle
        # is a policy dataclass, not a touch() owner). Best effort: a failure
        # here is logged only and must not block the read.
        if result:
            now = _now_seconds()
            for memory in result:
                try:
                    memory.last_accessed_at = touch(memory.last_accessed_at, now)
                    await self.update_fields(
                        tenant_id=tenant_id,
                        memory_id=memory.memory_id,
                        last_accessed_at=memory.last_accessed_at,
                    )
                except Exception as exc:
                    log_print(
                        f"[memory.store] H-2 touch failed "
                        f"(memory_id={memory.memory_id}): {exc}",
                        flush=True,
                    )

        # T022: read-time lazy tier fallback slot for records missing L0.
        missing_l0 = [m for m in result if not m.l0_summary and m.tierable]
        if missing_l0:
            log_print(
                f"[memory.store] T022 lazy tier backfill: {len(missing_l0)} "
                f"memories missing L0 (read-time summarizer not injected; "
                f"tier_content slot invoked)",
                flush=True,
            )
            for memory in missing_l0:
                _lazy_complete_tiers(memory)
        return result

    async def get(self, *, tenant_id: str, memory_id: str) -> Optional[Memory]:
        """Fetch a single memory by id within a tenant. Returns None if absent."""
        tenant_id = resolve_tenant_id(tenant_id)
        db = get_db()
        if db is None:
            return None
        row = await db[COLLECTION].find_one({"memory_id": memory_id, "tenant_id": tenant_id})
        return _row_to_memory(row) if row else None

    async def delete(self, *, tenant_id: str, memory_id: str, owner_id: str) -> bool:
        """Delete a memory; returns True when one document was removed."""
        tenant_id = resolve_tenant_id(tenant_id)
        db = get_db()
        if db is None:
            return False
        result = await db[COLLECTION].delete_one({
            "memory_id": memory_id,
            "tenant_id": tenant_id,
            "owner_id": owner_id,
        })
        return result.deleted_count > 0


__all__ = ["COLLECTION", "MemoryStore", "MemoryTooLargeError"]
