"""Admin egress allowlist CRUD + egress audit log query (038).

The chat-api outbound guard (``egress_guard``) enforces the allowlist at the
tool / browser call point; this router is the management surface: per-tenant
CRUD over ``egress_allowlist`` plus a read-only view of the ``egress.allowed`` /
``egress.denied`` audit trail (event names mirror the runtime guard).

Platform-scope entries are world-visible defaults and may only be written by the
platform super-admin (``__platform__``); tenant admins see and manage only their
own tenant entries.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.api.deps import get_authenticated_admin
from app.core.db import get_db
from app.core.tenant_identity import is_platform_tenant_id
from app.services.egress_store import (
    EGRESS_ALLOWLIST_COLLECTION,
    EgressAllowlistStore,
    RuleValidationError,
)

# Mirrors the runtime guard (chat-api egress_guard); kept dependency-free here.
EGRESS_AUDIT_COLLECTION = "enterprise_tool_audit"
EGRESS_ALLOWED_EVENT = "egress.allowed"
EGRESS_DENIED_EVENT = "egress.denied"

router = APIRouter(prefix="/egress", tags=["egress"])


async def get_egress_admin(authorization: str | None = Header(default=None)) -> dict:
    """Any authenticated admin — tenant or platform.

    Unlike ``get_current_admin_user`` this accepts ``__platform__`` so the
    platform super-admin can manage platform-scope entries, but still rejects
    the ambiguous ``default`` identifier (reverse guard, T022).
    """
    user = await get_authenticated_admin(authorization)
    if str(user.get("tenant_id") or "") == "default":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant context is required")
    return user


def _store(current_user: dict[str, Any] = Depends(get_egress_admin)) -> EgressAllowlistStore:
    db = get_db()
    return EgressAllowlistStore(db=db if db is not None else None)


def _is_platform_admin(current_user: dict[str, Any]) -> bool:
    return is_platform_tenant_id(str(current_user.get("tenant_id") or ""))


def _resolve_scope(*, payload: dict[str, Any], current_user: dict[str, Any]) -> tuple[str, str, str]:
    """Return (scope, tenant_id, tool_id); enforces platform write authority."""
    scope = str(payload.get("scope") or "tenant")
    tenant_id = str(payload.get("tenant_id") or "")
    tool_id = str(payload.get("tool_id") or "")
    if scope == "platform":
        if not _is_platform_admin(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only platform administrators may write platform-scope allowlist entries",
            )
        tenant_id = ""
        tool_id = ""
    else:
        if _is_platform_admin(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Platform administrator must scope entries to platform",
            )
        # Non-platform scope is always owned by the calling tenant.
        tenant_id = str(current_user.get("tenant_id") or "default")
    return scope, tenant_id, tool_id


@router.get("/allowlist")
async def list_allowlist(
    scope: str = Query(default=""),
    enabled: Optional[bool] = Query(default=None),
    current_user: dict[str, Any] = Depends(get_egress_admin),
) -> dict[str, Any]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    store = _store(current_user)
    if _is_platform_admin(current_user):
        rows = await store.list()
    else:
        # Tenant view: platform defaults + this tenant's own entries.
        rows = await store.list_visible(tenant_id)
    if not rows and not _is_platform_admin(current_user):
        # Idempotent platform defaults seeding on first tenant use (T014).
        rows = await store.seed_platform_defaults()
        rows = await store.list_visible(tenant_id)
    documents = [r.as_document() for r in rows]
    if scope:
        documents = [d for d in documents if d["scope"] == scope]
    if enabled is not None:
        documents = [d for d in documents if d["enabled"] is enabled]
    return {"items": documents, "total": len(documents)}


@router.get("/allowlist/{entry_id}")
async def get_entry(entry_id: str, current_user: dict[str, Any] = Depends(get_egress_admin)) -> dict[str, Any]:
    store = _store(current_user)
    document = await store.get(entry_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="egress allowlist entry not found")
    return document.as_document()


@router.post("/allowlist", status_code=status.HTTP_201_CREATED)
async def create_entry(
    payload: dict[str, Any], current_user: dict[str, Any] = Depends(get_egress_admin)
) -> dict[str, Any]:
    store = _store(current_user)
    scope, tenant_id, tool_id = _resolve_scope(payload=payload, current_user=current_user)
    try:
        document = await store.create(
            scope=scope,
            match_domain=str(payload.get("match_domain") or ""),
            tenant_id=tenant_id,
            tool_id=tool_id,
            path_prefix=str(payload.get("path_prefix") or ""),
            enabled=bool(payload.get("enabled", True)),
            note=str(payload.get("note") or ""),
        )
    except RuleValidationError as error:
        # Fail-closed on an invalid entry: reject, don't persist.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid egress allowlist entry: {error}")
    except Exception as error:  # noqa: BLE001 — any other shape error also 400
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid egress allowlist entry: {error}")
    return document.as_document()


@router.patch("/allowlist/{entry_id}")
async def update_entry(
    entry_id: str, payload: dict[str, Any], current_user: dict[str, Any] = Depends(get_egress_admin)
) -> dict[str, Any]:
    store = _store(current_user)
    existing = await store.get(entry_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="egress allowlist entry not found")
    if existing.scope == "platform" and not _is_platform_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only platform administrators may modify platform-scope allowlist entries",
        )
    document = await store.update(
        entry_id,
        match_domain=payload.get("match_domain"),
        path_prefix=payload.get("path_prefix"),
        enabled=payload.get("enabled"),
        note=payload.get("note"),
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="egress allowlist entry not found")
    return document.as_document()


@router.delete("/allowlist/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(entry_id: str, current_user: dict[str, Any] = Depends(get_egress_admin)) -> None:
    store = _store(current_user)
    existing = await store.get(entry_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="egress allowlist entry not found")
    if existing.scope == "platform" and not _is_platform_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only platform administrators may remove platform-scope allowlist entries",
        )
    if not await store.delete(entry_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="egress allowlist entry not found")


@router.get("/logs")
async def list_egress_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    event: str = Query(default=""),
    domain: str = Query(default=""),
    current_user: dict[str, Any] = Depends(get_egress_admin),
) -> dict[str, Any]:
    """Read-only view of the runtime egress audit trail for this tenant."""
    tenant_id = str(current_user.get("tenant_id") or "default")
    try:
        db = get_db()
    except Exception:  # noqa: BLE001 — DB 未就绪时返回空视图，不影响调用方
        return {"items": [], "total": 0, "page": page, "page_size": page_size}
    if db is None:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}
    collection = db[EGRESS_AUDIT_COLLECTION]
    query: dict[str, Any] = {
        "tenant_id": tenant_id,
        "event": {"$in": [EGRESS_ALLOWED_EVENT, EGRESS_DENIED_EVENT]},
    }
    if event:
        query["event"] = event
    rows = await collection.find(query).to_list(length=page * page_size + 1)
    if domain:
        rows = [r for r in rows if domain in str(r.get("domain") or _domain_from_details(r))]
    total = len(rows)
    paged = rows[(page - 1) * page_size: page * page_size]
    items = [_to_log_item(row) for row in paged]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _domain_from_details(row: dict[str, Any]) -> str:
    details = row.get("details") or {}
    return str(details.get("domain") or "") if isinstance(details, dict) else ""


def _to_log_item(row: dict[str, Any]) -> dict[str, Any]:
    details = row.get("details")
    if not isinstance(details, dict):
        raw = row.get("details_json") or "{}"
        try:
            import json

            details = json.loads(raw).get("details") if isinstance(raw, str) else {}
        except Exception:  # noqa: BLE001
            details = {}
    return {
        "event": row.get("event"),
        "tenant_id": row.get("tenant_id"),
        "user_id": row.get("user_id"),
        "action_id": row.get("action_id"),
        "occurred_at": row.get("occurred_at"),
        "details": details if isinstance(details, dict) else {},
    }


__all__ = ["router"]
