"""Server-side viewer context for 017 memory (B1 / DEP-1).

Background
----------
``app.services.end_user_session.resolve_session_user`` returns exactly::

    {"session": <doc>, "user": <end_users doc>, "tenant_id": str, "org_id": str}

The 017 endpoints used to read ``user_id`` / ``role`` /
``is_workspace_member`` from that dict.  None of those keys exist, so every
request resolved to ``viewer_id=""`` / ``role=""`` /
``is_workspace_member=False``.  Consequences:

* personal memories were written with ``owner_id=""`` and became readable by
  **every** logged-in user of the tenant (``"" == ""`` in ``visible_to``);
* workspace memories were never visible;
* org-scoped writes and promotions always returned 403.

This module is the single server-side construction point for the viewer
context.  Callers must not supply identity fields from the request body, and
must not read ``role`` / ``is_workspace_member`` from the auth dict.

B1 boundary (identity only)
---------------------------
Scope names (``workspace`` / ``org``) and ``Memory`` field names are
deliberately left untouched: D4 requires the ``project`` / ``department``
rename to be a single atomic switch, see
``specs/017-three-scope-memory/design-2026-11-05-project-department-scopes.md``.
``visible_workspace_ids`` is an interim source for the membership flag,
derived from 049's ``projects.member_user_ids``; B2 replaces it with
``visible_project_keys`` (``(project_id, owner_id)`` tuples, N1).  The
``"default"`` project is excluded on purpose (N2) -- it must never grant
tenant-wide memory visibility.

Fail-closed: a missing identity field or a failed lookup yields an empty
context / empty collection, never a permissive default.  No lookup failure is
allowed to disable visibility checks.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Optional

from app.core.tenant import add_tenant_scope, resolve_tenant_id

#: 006 preset role. ``position_roles.system_key`` for the built-in admin role;
#: ``end_user_position_roles.role_id`` is also accepted as a key because older
#: assignments may not have a resolvable ``position_roles`` row.
FULL_ACCESS_ROLE_KEY = "full_access_admin"

#: 049 grants this row tenant-wide visibility as a *project list* fallback.
#: 017 deliberately does not inherit that exemption (N2 / P6).
DEFAULT_PROJECT_ID = "default"

USER_COLLECTION = "end_users"
USER_ROLE_COLLECTION = "end_user_position_roles"
ROLE_COLLECTION = "position_roles"
PROJECT_COLLECTION = "projects"


def _log(message: str) -> None:
    try:
        from app.infrastructure.observability.config import log_print

        log_print(message, flush=True)
    except Exception:
        pass


@dataclass(frozen=True)
class MemoryViewerContext:
    """Immutable, server-resolved identity used by every 017 entry point."""

    tenant_id: str = ""
    user_id: str = ""
    role_keys: frozenset[str] = frozenset()
    viewer_org_id: str = ""
    visible_workspace_ids: frozenset[str] = frozenset()

    @property
    def is_valid(self) -> bool:
        return bool(self.tenant_id and self.user_id)

    @property
    def is_full_access_admin(self) -> bool:
        return FULL_ACCESS_ROLE_KEY in self.role_keys

    @property
    def role(self) -> str:
        """Legacy single-role view for ``ORG_PROMOTION_ROLES`` checks."""
        return FULL_ACCESS_ROLE_KEY if self.is_full_access_admin else ""

    @property
    def is_workspace_member(self) -> bool:
        return bool(self.visible_workspace_ids)

    def as_visibility_kwargs(self) -> dict[str, Any]:
        """Keyword args shared by store / retrieval / 021 router.

        Keeping one source of truth here is what prevents the ``viewer_org_id``
        omission that previously made org memories unreachable in RAG.
        """
        return {
            "viewer_id": self.user_id,
            "viewer_role": self.role,
            "is_workspace_member": self.is_workspace_member,
            "viewer_org_id": self.viewer_org_id,
        }


def build_viewer_context(
    resolved: Mapping[str, Any],
    *,
    role_keys: Iterable[str] = (),
    visible_workspace_ids: Iterable[str] = (),
    viewer_org_id: str = "",
) -> MemoryViewerContext:
    """Pure builder over the **real** ``resolve_session_user`` return shape.

    Deliberately does *not* fall back to ``resolved["user_id"]``: that key is
    not part of the auth contract, and tolerating it is exactly what let the
    endpoint tests pass with fabricated fixtures (DEP-1 / G1).
    """
    user_doc = resolved.get("user")
    if not isinstance(user_doc, Mapping):
        user_doc = {}
    user_id = str(user_doc.get("_id") or "")

    tenant_id = str(resolved.get("tenant_id") or "")
    if tenant_id:
        tenant_id = resolve_tenant_id(tenant_id)

    org_id = str(
        viewer_org_id
        or resolved.get("org_id")
        or user_doc.get("primary_org_id")
        or ""
    )
    return MemoryViewerContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role_keys=frozenset(str(key) for key in role_keys if key),
        viewer_org_id=org_id,
        visible_workspace_ids=frozenset(
            str(pid)
            for pid in visible_workspace_ids
            if pid and str(pid) != DEFAULT_PROJECT_ID
        ),
    )


async def load_role_keys(db: Any, tenant_id: str, user_id: str) -> frozenset[str]:
    """Resolve 006 role keys: ``end_user_position_roles`` → ``position_roles``."""
    if db is None or not tenant_id or not user_id:
        return frozenset()
    try:
        assignments = await db[USER_ROLE_COLLECTION].find(
            add_tenant_scope({"user_id": user_id}, tenant_id)
        ).to_list(length=100)
        role_ids = [
            str(row.get("role_id") or "")
            for row in assignments
            if row.get("role_id")
        ]
        keys = set(role_ids)
        if role_ids:
            roles = await db[ROLE_COLLECTION].find(
                add_tenant_scope(
                    {"_id": {"$in": role_ids}, "status": "active"}, tenant_id
                )
            ).to_list(length=100)
            for row in roles:
                system_key = str(row.get("system_key") or "")
                if system_key:
                    keys.add(system_key)
        return frozenset(key for key in keys if key)
    except Exception as exc:
        _log(f"[memory.viewer] load_role_keys failed (user={user_id}): {exc}")
        return frozenset()


async def load_primary_org_id(db: Any, tenant_id: str, user_id: str) -> str:
    """Read ``end_users.primary_org_id`` for callers without an auth token."""
    if db is None or not tenant_id or not user_id:
        return ""
    try:
        from app.core.ids import to_backend_id

        row = await db[USER_COLLECTION].find_one(
            add_tenant_scope(
                {"_id": to_backend_id(user_id), "status": "active"}, tenant_id
            )
        )
        return str(row.get("primary_org_id") or "") if row else ""
    except Exception as exc:
        _log(f"[memory.viewer] load_primary_org_id failed (user={user_id}): {exc}")
        return ""


async def load_visible_workspace_ids(
    db: Any, tenant_id: str, user_id: str
) -> frozenset[str]:
    """Projects I own or was invited to (049 contract), minus ``default``.

    Excludes ``archived`` rows and the 049 tenant-wide ``"default"`` fallback
    (N2).  B2 will replace this with ``visible_project_keys`` that also carry
    ``project_owner_id`` to disambiguate duplicate ``_id`` values (N1).
    """
    if db is None or not tenant_id or not user_id:
        return frozenset()
    try:
        query = add_tenant_scope({}, tenant_id)
        query.update(
            {
                "status": {"$ne": "archived"},
                "$or": [{"user_id": user_id}, {"member_user_ids": user_id}],
            }
        )
        rows = await db[PROJECT_COLLECTION].find(query, {"_id": 1}).to_list(length=500)
        return frozenset(
            str(row["_id"])
            for row in rows
            if row.get("_id") and str(row["_id"]) != DEFAULT_PROJECT_ID
        )
    except Exception as exc:
        _log(f"[memory.viewer] load_visible_workspace_ids failed (user={user_id}): {exc}")
        return frozenset()


async def _load_identity_details(
    db: Any, tenant_id: str, user_id: str, *, fallback_org_id: str = ""
) -> tuple[frozenset[str], frozenset[str], str]:
    role_keys = await load_role_keys(db, tenant_id, user_id)
    workspace_ids = await load_visible_workspace_ids(db, tenant_id, user_id)
    org_id = fallback_org_id or await load_primary_org_id(db, tenant_id, user_id)
    return role_keys, workspace_ids, org_id


def _resolve_db(db: Optional[Any]) -> Any:
    if db is not None:
        return db
    try:
        from app.core.db import get_db

        return get_db()
    except Exception as exc:
        _log(f"[memory.viewer] get_db failed: {exc}")
        return None


async def resolve_viewer_context(
    authorization: str, *, db: Optional[Any] = None
) -> MemoryViewerContext:
    """Build the viewer context for an HTTP request (the only auth entry)."""
    from fastapi import HTTPException

    from app.api.endpoints.auth import _resolve_session_user

    resolved = await _resolve_session_user(authorization)
    base = build_viewer_context(resolved)
    if not base.is_valid:
        # Fail closed: an unresolvable identity must never reach visible_to.
        raise HTTPException(status_code=401, detail="invalid_viewer_context")

    role_keys, workspace_ids, org_id = await _load_identity_details(
        _resolve_db(db),
        base.tenant_id,
        base.user_id,
        fallback_org_id=base.viewer_org_id,
    )
    return replace(
        base,
        role_keys=role_keys,
        visible_workspace_ids=workspace_ids,
        viewer_org_id=org_id,
    )


async def resolve_viewer_from_identity(
    *, tenant_id: str, user_id: str, db: Optional[Any] = None
) -> MemoryViewerContext:
    """Build the viewer context from trusted ids (RAG runtime, no token).

    ``CapabilityExecutionContext.tenant_id/user_id`` are populated from
    ToolGatewayClaims, not from the model, so they are trusted.  Everything
    else is resolved server-side here.
    """
    base = build_viewer_context(
        {"tenant_id": tenant_id, "user": {"_id": user_id}}
    )
    if not base.is_valid:
        return base
    role_keys, workspace_ids, org_id = await _load_identity_details(
        _resolve_db(db), base.tenant_id, base.user_id
    )
    return replace(
        base,
        role_keys=role_keys,
        visible_workspace_ids=workspace_ids,
        viewer_org_id=org_id,
    )


__all__ = [
    "FULL_ACCESS_ROLE_KEY",
    "DEFAULT_PROJECT_ID",
    "MemoryViewerContext",
    "build_viewer_context",
    "load_role_keys",
    "load_primary_org_id",
    "load_visible_workspace_ids",
    "resolve_viewer_context",
    "resolve_viewer_from_identity",
]
