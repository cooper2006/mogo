"""Three-scope memory endpoints (feature 017).

Provides CRUD for the three-scope memory layer: create / list / delete.
Scoping and visibility are enforced server-side via ``MemoryStore`` +
``scope_filter`` (017 FR-2, no privilege escalation).
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from app.memory.scope import MemoryScope, ORG_PROMOTION_ROLES
from app.memory.store import MemoryStore, MemoryTooLargeError
from app.memory.tiering import NoopSummarizer, tier_content

router = APIRouter(prefix="/api/memories", tags=["memory"])


@router.post("")
async def create_memory(
    payload: dict[str, Any],
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Create a memory (FR-5). Scope defaults to ``personal``; promotion to
    ``org`` requires a ``full_access_admin`` role (FR-4).
    """
    from app.api.endpoints.auth import _resolve_session_user
    from app.memory.store import MemoryStore

    resolved = await _resolve_session_user(authorization)
    tenant_id = str(resolved.get("tenant_id") or "")
    user_id = str(resolved.get("user_id") or "")
    role = str(resolved.get("role") or "")

    content = str(payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")

    scope = str(payload.get("scope") or MemoryScope.PERSONAL.value)
    if scope not in {s.value for s in MemoryScope}:
        raise HTTPException(status_code=400, detail=f"invalid scope: {scope!r}")

    # 017 FR-4: creating at ``org`` scope grants visibility to the whole tenant,
    # so it needs the same authorization as promotion. Without this, any user
    # could write an org-wide memory directly and bypass ``promote_to_org``.
    if scope == MemoryScope.ORG.value and role not in ORG_PROMOTION_ROLES:
        raise HTTPException(
            status_code=403,
            detail="org scope requires full_access_admin",
        )

    # 017 FR-13/FR-15: derive density tiers (write-time summaries if supplied,
    # lazy fallback handled at read time via tier_content).
    supplied_l0 = str(payload.get("l0_summary") or "")
    supplied_l1 = str(payload.get("l1_overview") or "")
    # Write-time summaries are fresh; mark them so the stale path won't overwrite.
    supplied_at = time.time() if supplied_l0 else 0.0
    tier = tier_content(
        content,
        NoopSummarizer(),
        l0_summary=supplied_l0,
        l1_overview=supplied_l1,
        tierable=None if payload.get("tierable") is None else bool(payload.get("tierable")),
        summary_generated_at=supplied_at,
    )

    store = MemoryStore()
    try:
        memory = await store.save(
            content=content,
            owner_id=user_id,
            tenant_id=tenant_id,
            workspace_id=str(payload.get("workspace_id") or ""),
            scope=scope,
            l0_summary=tier.l0_summary,
            l1_overview=tier.l1_overview,
            l2_raw=tier.l2_raw,
            tierable=tier.tierable,
            summary_generated_at=tier.summary_generated_at,
            source_session_id=str(payload.get("source_session_id") or ""),
            source_type=str(payload.get("source_type") or ""),
        )
    except MemoryTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc))

    return {"code": 0, "message": "created", "data": {
        "memory_id": memory.memory_id,
        "scope": memory.scope,
        "content": memory.content,
        "l0_summary": memory.l0_summary,
        "l1_overview": memory.l1_overview,
        "tierable": memory.tierable,
        "addr": memory.addr("L0"),
        "created_at": memory.created_at,
    }}


@router.get("")
async def list_memories(
    *,
    authorization: str = Header(default=""),
    scope: str = "",
) -> dict[str, Any]:
    """List memories visible to the current viewer (FR-2)."""
    from app.api.endpoints.auth import _resolve_session_user
    from app.memory.store import MemoryStore

    resolved = await _resolve_session_user(authorization)
    tenant_id = str(resolved.get("tenant_id") or "")
    viewer_id = str(resolved.get("user_id") or "")
    viewer_role = str(resolved.get("role") or "")

    store = MemoryStore()
    memories = await store.list_for_viewer(
        tenant_id=tenant_id,
        viewer_id=viewer_id,
        viewer_role=viewer_role,
        is_workspace_member=bool(resolved.get("is_workspace_member") or False),
    )
    # Client-side scope filter when requested.
    if scope:
        memories = [m for m in memories if m.scope == scope]
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "memories": [
                {
                    "memory_id": m.memory_id,
                    "scope": m.scope,
                    "content": m.content,
                    "l0_summary": m.l0_summary,
                    "l1_overview": m.l1_overview,
                    "tierable": m.tierable,
                    "addr": m.addr("L0"),
                    "source_session_id": m.source_session_id,
                    "source_type": m.source_type,
                    "owner_id": m.owner_id,
                    "created_at": m.created_at,
                    "last_accessed_at": m.last_accessed_at,
                }
                for m in memories
            ],
            "total": len(memories),
        },
    }


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Delete the caller's own memory (FR-5 ownership check)."""
    from app.api.endpoints.auth import _resolve_session_user
    from app.memory.store import MemoryStore

    resolved = await _resolve_session_user(authorization)
    tenant_id = str(resolved.get("tenant_id") or "")
    user_id = str(resolved.get("user_id") or "")

    store = MemoryStore()
    ok = await store.delete(tenant_id=tenant_id, memory_id=memory_id, owner_id=user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="memory_not_found_or_not_owner")
    return {"code": 0, "message": "deleted"}


@router.patch("/{memory_id}/promote")
async def promote_memory(
    memory_id: str,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Promote a personal/workspace memory to org scope (FR-4, 017 残项修复).

    Requires a ``full_access_admin`` role. The promotion is audited via the
    001 audit stream (``memory.promoted``).
    """
    from app.api.endpoints.auth import _resolve_session_user
    from app.memory.scope import promote_to_org, MemoryAccessError
    from app.memory.store import MemoryStore

    resolved = await _resolve_session_user(authorization)
    tenant_id = str(resolved.get("tenant_id") or "")
    user_id = str(resolved.get("user_id") or "")
    role = str(resolved.get("role") or "")

    store = MemoryStore()
    memory = await store.get(tenant_id=tenant_id, memory_id=memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory_not_found")
    if memory.owner_id != user_id:
        raise HTTPException(status_code=403, detail="not_owner")

    try:
        promoted = promote_to_org(memory, role=role)
    except MemoryAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    await store.save(
        memory_id=promoted.memory_id,
        content=promoted.content,
        owner_id=promoted.owner_id,
        tenant_id=promoted.tenant_id,
        workspace_id=promoted.workspace_id,
        scope=promoted.scope,
    )
    return {"code": 0, "message": "promoted", "data": {
        "memory_id": promoted.memory_id,
        "scope": promoted.scope,
        "promoted_by": user_id,
    }}


__all__ = ["router"]
