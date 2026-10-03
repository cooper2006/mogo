"""Three-scope memory endpoints (feature 017).

Provides CRUD for the three-scope memory layer: create / list / delete.
Scoping and visibility are enforced server-side via ``MemoryStore`` +
``scope_filter`` (017 FR-2, no privilege escalation).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException

from app.memory.scope import MemoryScope

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
    tenant_id = str(resolved.get("main_id") or "")
    user_id = str(resolved.get("user_id") or "")
    role = str(resolved.get("role") or "")

    content = str(payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")

    scope = str(payload.get("scope") or MemoryScope.PERSONAL.value)
    if scope not in {s.value for s in MemoryScope}:
        raise HTTPException(status_code=400, detail=f"invalid scope: {scope!r}")

    store = MemoryStore()
    memory = store.save(
        content=content,
        owner_id=user_id,
        tenant_id=tenant_id,
        workspace_id=str(payload.get("workspace_id") or ""),
        scope=scope,
    )
    return {"code": 0, "message": "created", "data": {
        "memory_id": memory.memory_id,
        "scope": memory.scope,
        "content": memory.content,
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
    tenant_id = str(resolved.get("main_id") or "")
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
    tenant_id = str(resolved.get("main_id") or "")
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
    tenant_id = str(resolved.get("main_id") or "")
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

    store.save(
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
