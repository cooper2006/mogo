"""Three-scope memory endpoints (feature 017) — D4 target state.

Provides CRUD for the ``personal`` / ``project`` / ``department`` memory layer:
create / list / edit / delete / promote. Scoping and visibility are enforced
server-side via ``resolve_viewer_context`` + ``MemoryStore`` (017 FR-2, no
privilege escalation). There is no runtime ``workspace`` / ``org`` alias.

T030: list shares the admin ``page`` / ``page_size`` contract (with ``limit`` /
``cursor`` kept as a compatible offset), and create / list / edit all return the
same single-record echo via ``_memory_response`` (actual_scope / resolved_from /
scope ids are computed server-side, never read from caller input).
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.memory.scope import (
    DEFAULT_PROJECT_ID,
    MemoryAccessError,
    MemoryScope,
    PROMOTION_STATUS_APPROVED,
    promote_to_department,
    visible_to,
)
from app.memory import promotion as promotion_sm
from app.memory.store import MemoryTooLargeError
from app.memory.tiering import NoopSummarizer, tier_content

router = APIRouter(prefix="/api/v1/memories", tags=["memory"])

_VALID_SCOPES = frozenset(s.value for s in MemoryScope)
_VALID_STATUSES = frozenset({"active", "archived"})
# Window used when scanning the viewer's visible records before server-side
# filtering / pagination. The store's ``list_for_viewer`` keeps its signature;
# we only widen its existing ``top_n`` parameter so page 2+ is reachable.
_LIST_SCAN_LIMIT = 1000
# Client-editable fields only (content / density-tier fields). Authorization
# fields (scope / *_id / owner_id / tenant_id) are resolved server-side and any
# client-supplied value is ignored (017 FR-2 / §9.1).
_EDITABLE_FIELDS = ("content", "l0_summary", "l1_overview", "l2_raw", "tierable")


class MemoryPromotePayload(BaseModel):
    """Body form of ``PATCH /{memory_id}/promote``.

    ``department_id`` here takes precedence over the query parameter; the
    latter is kept for older callers. All fields are optional so a bodyless
    promote still falls back to the viewer's primary department.
    """

    target_scope: str = ""
    department_id: str = ""
    reason: str = ""


class MemoryPromoteRequestPayload(BaseModel):
    """Body form of ``POST /{memory_id}/promote/request`` (T035 user flow).

    A non-admin owner requests promotion of their memory to ``department``. The
    request enters ``pending`` and an admin later approves/rejects it. Only
    ``department_id`` (target) and an optional ``reason`` are accepted; the
    scope is always ``department`` and the requester's identity is server-derived.
    """

    department_id: str = ""
    reason: str = ""


def _resolved_from(memory: Any) -> str:
    """B-9: how the effective scope was resolved.

    Enum: ``explicit`` | ``default`` | ``default_fallback`` | ``sediment``
    (deliberately **no** ``legacy_alias``). Derived from stored, trusted fields
    only — never from a caller-supplied hint.
    """
    if str(memory.source_type or "") == "session":
        return "sediment"
    if str(memory.project_id or "") == DEFAULT_PROJECT_ID:
        # N2 / E-4: the 049 "default" row fell back to personal.
        return "default_fallback"
    if (
        memory.scope == MemoryScope.PERSONAL.value
        and not memory.project_id
        and not memory.department_id
    ):
        return "default"
    return "explicit"


def _scope_echo(memory: Any) -> dict[str, Any]:
    """B-9 response echo: actual scope + provenance + scope ids."""
    return {
        "actual_scope": memory.scope,
        "resolved_from": _resolved_from(memory),
        "project_id": memory.project_id,
        "project_owner_id": memory.project_owner_id,
        "department_id": memory.department_id,
    }


def _memory_response(memory: Any) -> dict[str, Any]:
    """Single-record response shared by create / list / edit (T030 contract)."""
    return {
        "memory_id": memory.memory_id,
        "scope": memory.scope,
        "content": memory.content,
        "l0_summary": memory.l0_summary,
        "l1_overview": memory.l1_overview,
        "tierable": memory.tierable,
        "addr": memory.addr("L0"),
        "source_session_id": memory.source_session_id,
        "source_type": memory.source_type,
        "owner_id": memory.owner_id,
        "created_at": memory.created_at,
        "last_accessed_at": memory.last_accessed_at,
        "promotion_status": str(getattr(memory, "promotion_status", "none") or "none"),
        "invalidated": bool(getattr(memory, "invalidated", False)),
        **_scope_echo(memory),
    }


def _promote_field(payload: Any, key: str) -> str:
    """Read a promote body field from a Pydantic model, a dict, or ``None``."""
    if isinstance(payload, dict):
        return str(payload.get(key, "") or "").strip()
    return str(getattr(payload, key, "") or "").strip()


@router.post("")
async def create_memory(
    payload: dict[str, Any],
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Create a memory (FR-5). Scope defaults to ``personal``.

    ``project`` / ``department`` targets are resolved and validated entirely
    server-side against the viewer context; client-supplied identity fields are
    ignored or rejected.
    """
    from app.memory.store import MemoryStore
    from app.memory.viewer import resolve_viewer_context

    viewer = await resolve_viewer_context(authorization)
    tenant_id = viewer.tenant_id
    user_id = viewer.user_id

    content = str(payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")

    # D4: explicitly requesting a legacy field is a client error, not an alias.
    if "workspace_id" in payload or "org_id" in payload:
        raise HTTPException(status_code=400, detail="scope_invalid")

    scope = str(payload.get("scope") or MemoryScope.PERSONAL.value)
    if scope not in _VALID_SCOPES:
        raise HTTPException(status_code=400, detail="scope_invalid")

    project_id = ""
    project_owner_id = ""
    department_id = ""

    if scope == MemoryScope.PROJECT.value:
        requested_project_id = str(payload.get("project_id") or "").strip()
        if requested_project_id == DEFAULT_PROJECT_ID:
            raise HTTPException(status_code=400, detail="default_project_not_shareable")
        # Server resolves project_owner_id from the viewer's visible keys;
        # a client-supplied project_owner_id is ignored (N1).
        matched_owner = next(
            (
                owner
                for pid, owner in viewer.visible_project_keys
                if pid == requested_project_id
            ),
            "",
        )
        if not requested_project_id or not matched_owner:
            raise HTTPException(status_code=403, detail="project_not_member")
        project_id = requested_project_id
        project_owner_id = matched_owner

    elif scope == MemoryScope.DEPARTMENT.value:
        # FR-4 / G-1: department writes need a full-access admin.
        if not viewer.is_full_access_admin:
            raise HTTPException(
                status_code=403, detail="department_requires_full_access_admin"
            )
        requested_department_id = str(payload.get("department_id") or "").strip()
        if requested_department_id:
            # A requested department is accepted only when visible to the admin.
            if not viewer.department_is_visible(requested_department_id):
                raise HTTPException(status_code=403, detail="department_not_visible")
            department_id = requested_department_id
        else:
            department_id = viewer.primary_department_id
            if not viewer.department_is_visible(department_id):
                raise HTTPException(status_code=403, detail="department_not_visible")

    supplied_l0 = str(payload.get("l0_summary") or "")
    supplied_l1 = str(payload.get("l1_overview") or "")
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
            project_id=project_id,
            project_owner_id=project_owner_id,
            department_id=department_id,
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

    return {"code": 0, "message": "created", "data": _memory_response(memory)}


@router.get("")
async def list_memories(
    *,
    authorization: str = Header(default=""),
    page: int = 1,
    page_size: int = 20,
    status: str = "",
    keyword: str = "",
    scope: str = "",
    limit: int = 0,
    cursor: str = "",
) -> dict[str, Any]:
    """List memories visible to the current viewer (FR-2 / T030).

    Pagination is aligned with the admin surface (``page`` / ``page_size``);
    ``limit`` is accepted as a ``page_size`` alias and ``cursor`` as a simple
    offset over the time-ordered visible set. Visibility is still delegated to
    ``store.list_for_viewer(viewer=viewer)`` (``visible_to``), and all filters
    are applied server-side on that visible set.
    """
    from app.memory.store import MemoryStore
    from app.memory.viewer import resolve_viewer_context

    viewer = await resolve_viewer_context(authorization)
    if scope and scope not in _VALID_SCOPES:
        raise HTTPException(status_code=400, detail="scope_invalid")

    wanted_status = status if status in _VALID_STATUSES else ""
    needle = str(keyword or "").strip().lower()
    # ``limit`` remains a page_size alias for older user-web callers.
    effective_page_size = limit if limit and limit > 0 else page_size
    if effective_page_size <= 0:
        effective_page_size = 20
    if page < 1:
        page = 1

    store = MemoryStore()
    memories = await store.list_for_viewer(viewer=viewer, top_n=_LIST_SCAN_LIMIT)

    filtered: list[Any] = []
    for m in memories:
        if scope and m.scope != scope:
            continue
        m_status = "archived" if bool(getattr(m, "archived", False)) else "active"
        if wanted_status and m_status != wanted_status:
            continue
        if needle:
            haystack = " ".join(
                str(getattr(m, field, "") or "")
                for field in ("content", "l0_summary", "l1_overview")
            ).lower()
            if needle not in haystack:
                continue
        filtered.append(m)

    # Stable time ordering gives ``cursor`` a deterministic offset base. The
    # cursor is intentionally a plain numeric offset, not a complex keyset.
    filtered.sort(
        key=lambda m: (
            getattr(m, "last_accessed_at", 0.0) or getattr(m, "created_at", 0.0) or 0.0
        ),
        reverse=True,
    )
    total = len(filtered)

    if cursor:
        try:
            start = int(cursor)
        except (TypeError, ValueError):
            start = (page - 1) * effective_page_size
    else:
        start = (page - 1) * effective_page_size
    if start < 0:
        start = 0
    page_rows = filtered[start : start + effective_page_size]
    next_start = start + len(page_rows)
    next_cursor = str(next_start) if next_start < total else ""

    items = [_memory_response(m) for m in page_rows]
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": items,
            # Kept for existing callers / tests (T030: admin-aligned ``items``
            # is added alongside it).
            "memories": items,
            "total": total,
            "page": page,
            "page_size": effective_page_size,
            "next_cursor": next_cursor,
        },
    }


@router.patch("/{memory_id}")
async def update_memory(
    memory_id: str,
    payload: dict[str, Any],
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Generic edit endpoint: content / density-tier fields only.

    ``visible_to`` is the single visibility predicate; an invisible record is
    404 with no content leaked. Authorization fields (``scope`` / ``project_id``
    / ``project_owner_id`` / ``department_id`` / ``owner_id`` / ``tenant_id``)
    are resolved server-side and any client-supplied value is ignored. The write
    uses ``store.update_fields()`` incremental ``$set`` so L0/L1/L2,
    provenance, ``archived`` and ``project_owner_id`` survive (D-6).
    """
    from app.memory.store import MemoryStore
    from app.memory.viewer import resolve_viewer_context

    viewer = await resolve_viewer_context(authorization)
    store = MemoryStore()
    memory = await store.get(tenant_id=viewer.tenant_id, memory_id=memory_id)
    if memory is None or not visible_to(memory, viewer):
        raise HTTPException(status_code=404, detail="memory_not_found")

    fields: dict[str, Any] = {}
    for key in _EDITABLE_FIELDS:
        if key not in payload:
            continue
        value = payload[key]
        fields[key] = bool(value) if key == "tierable" else str(value or "")
    fields["updated_at"] = time.time()

    try:
        updated = await store.update_fields(
            tenant_id=viewer.tenant_id, memory_id=memory_id, **fields
        )
    except MemoryTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    if not updated:
        raise HTTPException(status_code=404, detail="memory_not_found")

    fresh = await store.get(tenant_id=viewer.tenant_id, memory_id=memory_id) or memory
    return {"code": 0, "message": "updated", "data": _memory_response(fresh)}


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Delete a memory (FR-5): owner or full-access admin only, else 404/403."""
    from app.memory.store import MemoryStore
    from app.memory.viewer import resolve_viewer_context

    viewer = await resolve_viewer_context(authorization)
    store = MemoryStore()
    memory = await store.get(tenant_id=viewer.tenant_id, memory_id=memory_id)
    # Invisible / absent → 404 (never leak content fields).
    if memory is None or not visible_to(memory, viewer):
        raise HTTPException(status_code=404, detail="memory_not_found")
    if memory.owner_id != viewer.user_id and not viewer.is_full_access_admin:
        raise HTTPException(status_code=403, detail="not_owner")

    ok = await store.delete(
        tenant_id=viewer.tenant_id,
        memory_id=memory_id,
        # An admin may delete a record owned by someone else; the owner filter
        # must therefore use the *stored* owner, not the caller's id.
        owner_id=memory.owner_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="memory_not_found")
    return {"code": 0, "message": "deleted"}


@router.patch("/{memory_id}/promote")
async def promote_memory(
    memory_id: str,
    payload: MemoryPromotePayload | None = None,
    authorization: str = Header(default=""),
    department_id: str = "",
) -> dict[str, Any]:
    """Promote a memory to ``department`` (FR-4 / G-1 / D-6).

    Accepts the target department in the JSON body (preferred) or as a query
    parameter (legacy), falling back to ``viewer.primary_department_id``. Uses
    ``promote_to_department`` for authorization and ``update_fields`` for an
    incremental ``$set`` — L0/L1/L2, provenance, ``archived`` and
    ``project_owner_id`` are preserved (the old ``replace_one`` path wiped them).
    """
    from app.memory.store import MemoryStore
    from app.memory.viewer import resolve_viewer_context

    viewer = await resolve_viewer_context(authorization)
    store = MemoryStore()
    memory = await store.get(tenant_id=viewer.tenant_id, memory_id=memory_id)
    if memory is None or not visible_to(memory, viewer):
        raise HTTPException(status_code=404, detail="memory_not_found")
    if memory.owner_id != viewer.user_id and not viewer.is_full_access_admin:
        raise HTTPException(status_code=403, detail="not_owner")

    # D4: a supplied target_scope must be ``department``; legacy org / workspace
    # (or anything else) is a client error, not a silent alias.
    target_scope = _promote_field(payload, "target_scope")
    if target_scope and target_scope != MemoryScope.DEPARTMENT.value:
        raise HTTPException(status_code=400, detail="scope_invalid")

    # body > query > viewer primary department.
    target_department = (
        _promote_field(payload, "department_id")
        or str(department_id or "").strip()
        or viewer.primary_department_id
    )
    if not viewer.department_is_visible(target_department):
        raise HTTPException(status_code=403, detail="department_not_visible")

    try:
        promoted = promote_to_department(
            memory, viewer=viewer, department_id=target_department
        )
    except MemoryAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    updated = await store.update_fields(
        tenant_id=viewer.tenant_id,
        memory_id=promoted.memory_id,
        scope=promoted.scope,
        department_id=promoted.department_id,
        promotion_status=PROMOTION_STATUS_APPROVED,
        promotion_resolved_by=viewer.user_id,
        promotion_resolved_at=time.time(),
        updated_at=time.time(),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="memory_not_found")
    return {"code": 0, "message": "promoted", "data": {
        "memory_id": promoted.memory_id,
        "scope": promoted.scope,
        "department_id": promoted.department_id,
        "promotion_status": PROMOTION_STATUS_APPROVED,
        "promoted_by": viewer.user_id,
    }}


@router.post("/{memory_id}/promote/request")
async def request_promote_memory(
    memory_id: str,
    payload: MemoryPromoteRequestPayload | None = None,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """T035: a normal user requests promotion to ``department`` (→ ``pending``).

    The caller must own the memory and the target department must be visible to
    them. This does **not** promote immediately — it only opens a ``pending``
    request that a full-access admin approves/rejects via the admin surface. A
    non-admin calling the direct ``/promote`` endpoint still gets 403 (G-1).
    """
    from app.services.feature_audit_bridge import emit_feature_event
    from app.memory.store import MemoryStore
    from app.memory.viewer import resolve_viewer_context

    viewer = await resolve_viewer_context(authorization)
    store = MemoryStore()
    memory = await store.get(tenant_id=viewer.tenant_id, memory_id=memory_id)
    if memory is None or not visible_to(memory, viewer):
        raise HTTPException(status_code=404, detail="memory_not_found")
    if memory.owner_id != viewer.user_id:
        raise HTTPException(status_code=403, detail="not_owner")

    target_department = (
        _promote_field(payload, "department_id")
        or viewer.primary_department_id
    )
    if not viewer.department_is_visible(target_department):
        raise HTTPException(status_code=403, detail="department_not_visible")

    reason = _promote_field(payload, "reason")
    try:
        promotion_sm.request_promotion(
            memory, viewer=viewer, department_id=target_department, reason=reason
        )
    except MemoryAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    updated = await store.update_fields(
        tenant_id=viewer.tenant_id,
        memory_id=memory.memory_id,
        promotion_status=memory.promotion_status,
        pending_department_id=memory.pending_department_id,
        promotion_requested_by=memory.promotion_requested_by,
        promotion_requested_at=memory.promotion_requested_at,
        promotion_reason=memory.promotion_reason,
        updated_at=time.time(),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="memory_not_found")

    try:
        emit_feature_event(
            "017",
            "memory.promotion.requested",
            {
                "memory_id": memory.memory_id,
                "scope": memory.scope,
                "pending_department_id": memory.pending_department_id,
                "reason": reason,
            },
            tenant_id=viewer.tenant_id,
            actor=viewer.user_id,
        )
    except Exception as exc:  # 审计失败不阻断主流程
        from app.infrastructure.observability.config import log_print

        log_print(
            f"[memory.endpoint] promotion.requested audit emit failed "
            f"(memory_id={memory.memory_id}): {exc}",
            flush=True,
        )

    return {"code": 0, "message": "promotion_requested", "data": {
        "memory_id": memory.memory_id,
        "promotion_status": memory.promotion_status,
        "pending_department_id": memory.pending_department_id,
        "requested_by": memory.promotion_requested_by,
    }}


__all__ = ["router"]
