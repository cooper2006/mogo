"""Server-side viewer context for 017 memory (v3 / A-1 target state).

Background
----------
``app.services.end_user_session.resolve_session_user`` returns exactly::

    {"session": <doc>, "user": <end_users doc>, "tenant_id": str, "org_id": str}

B1 fixed the P0 hole where endpoints read non-existent ``user_id`` / ``role`` /
``is_workspace_member`` keys from that dict. B2 completes the target state:

* project visibility is a set of ``(project_id, project_owner_id)`` pairs
  (**N1**: ``projects._id`` is not unique inside a tenant);
* department visibility is the user's own departments plus **all descendants**
  (**D3**), never ancestors;
* the 049 tenant-wide ``"default"`` row is excluded (**N2**).

Every 017 entry point must obtain its context here. Callers never supply
identity fields from the request body, and no lookup failure may widen the
result — everything is fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Optional

from app.core.tenant import add_tenant_scope, resolve_tenant_id
from app.memory.scope import DEFAULT_PROJECT_ID

#: 006 preset role. ``position_roles.system_key`` for the built-in admin role;
#: ``end_user_position_roles.role_id`` is also accepted as a key because older
#: assignments may not have a resolvable ``position_roles`` row.
FULL_ACCESS_ROLE_KEY = "full_access_admin"

USER_COLLECTION = "end_users"
USER_ROLE_COLLECTION = "end_user_position_roles"
ROLE_COLLECTION = "position_roles"
PROJECT_COLLECTION = "projects"
ORG_UNIT_COLLECTION = "org_units"
USER_ORG_REL_COLLECTION = "end_user_org_relations"

ProjectKey = tuple[str, str]  # (project_id, project_owner_id)


def _log(message: str) -> None:
    try:
        from app.infrastructure.observability.config import log_print

        log_print(message, flush=True)
    except Exception:
        pass


@dataclass(frozen=True)
class MemoryViewerContext:
    """Immutable, server-resolved identity used by every 017 entry point.

    A-1 fields only: no ``viewer_org_id`` / ``visible_workspace_ids`` /
    ``is_workspace_member`` / single ``role`` view — those were B1 interim
    shims removed by D4.
    """

    tenant_id: str = ""
    user_id: str = ""
    role_keys: frozenset[str] = frozenset()
    primary_department_id: str = ""
    visible_department_ids: frozenset[str] = frozenset()
    visible_project_keys: frozenset[ProjectKey] = frozenset()
    active_project_id: str = ""
    session_participants: frozenset[str] = frozenset()

    @property
    def is_valid(self) -> bool:
        return bool(self.tenant_id and self.user_id)

    @property
    def is_full_access_admin(self) -> bool:
        return FULL_ACCESS_ROLE_KEY in self.role_keys

    def project_is_visible(self, project_id: str, project_owner_id: str) -> bool:
        """N1/N2 helper used by write paths to validate a target project."""
        if not project_id or not project_owner_id:
            return False
        if project_id == DEFAULT_PROJECT_ID:
            return False
        return (project_id, project_owner_id) in self.visible_project_keys

    def department_is_visible(self, department_id: str) -> bool:
        return bool(department_id) and department_id in self.visible_department_ids


def build_viewer_context(
    resolved: Mapping[str, Any],
    *,
    role_keys: Iterable[str] = (),
    visible_project_keys: Iterable[ProjectKey] = (),
    visible_department_ids: Iterable[str] = (),
    primary_department_id: str = "",
    active_project_id: str = "",
    session_participants: Iterable[str] = (),
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

    # auth's org_id is end_users.primary_org_id -- a *seed* for the department
    # set, never the set itself (D3 requires descendant expansion).
    primary = str(
        primary_department_id
        or resolved.get("org_id")
        or user_doc.get("primary_org_id")
        or ""
    )

    keys: set[ProjectKey] = set()
    for item in visible_project_keys:
        if isinstance(item, (tuple, list)) and len(item) == 2:
            pid, owner = str(item[0] or ""), str(item[1] or "")
            if pid and owner and pid != DEFAULT_PROJECT_ID:
                keys.add((pid, owner))

    return MemoryViewerContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role_keys=frozenset(str(key) for key in role_keys if key),
        primary_department_id=primary,
        visible_department_ids=frozenset(
            str(did) for did in visible_department_ids if did
        ),
        visible_project_keys=frozenset(keys),
        active_project_id=str(active_project_id or ""),
        session_participants=frozenset(
            str(uid) for uid in session_participants if uid
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


async def load_visible_project_keys(
    db: Any, tenant_id: str, user_id: str
) -> frozenset[ProjectKey]:
    """C-1 / N1: projects I own or was invited to, as ``(_id, owner)`` pairs.

    Only ``projects.member_user_ids`` + ``projects.user_id`` are consulted
    (049 contract). ``"default"`` and archived rows are excluded; rows without
    an owner cannot be disambiguated and are dropped fail-closed.
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
        rows = await db[PROJECT_COLLECTION].find(
            query, {"_id": 1, "user_id": 1}
        ).to_list(length=500)
        return frozenset(
            (str(row["_id"]), str(row.get("user_id") or ""))
            for row in rows
            if row.get("_id")
            and row.get("user_id")
            and str(row["_id"]) != DEFAULT_PROJECT_ID
        )
    except Exception as exc:
        _log(f"[memory.viewer] load_visible_project_keys failed (user={user_id}): {exc}")
        return frozenset()


async def load_direct_department_ids(
    db: Any, tenant_id: str, user_id: str, *, fallback_primary_org_id: str = ""
) -> tuple[frozenset[str], str]:
    """A-4 / N3: departments the user directly belongs to.

    ``end_user_org_relations`` is queried **without** a ``status`` filter:
    three writers never set that field, and 030's filtered read is why users
    fell out of their department scopes. 049 ``member-candidates`` already
    validated this unfiltered form. The primary department comes from
    ``end_users.primary_org_id`` or an ``is_primary`` relation.
    """
    if db is None or not tenant_id or not user_id:
        return frozenset(), fallback_primary_org_id
    direct: set[str] = set()
    primary = fallback_primary_org_id
    try:
        rows = await db[USER_ORG_REL_COLLECTION].find(
            add_tenant_scope({"user_id": user_id}, tenant_id)
        ).to_list(length=200)
        for row in rows:
            dept_id = str(row.get("org_id") or "")
            if dept_id:
                direct.add(dept_id)
            if row.get("is_primary") and dept_id and not primary:
                primary = dept_id
    except Exception as exc:
        _log(f"[memory.viewer] load_direct_department_ids failed (user={user_id}): {exc}")
    if not primary:
        primary = await load_primary_org_id(db, tenant_id, user_id)
    if primary:
        direct.add(primary)
    return frozenset(direct), primary


async def load_visible_department_ids(
    db: Any, tenant_id: str, user_id: str, *, fallback_primary_org_id: str = ""
) -> tuple[frozenset[str], str]:
    """D3: direct departments + **all descendants**, never ancestors.

    ``org_units.path_ids`` holds ancestor ids, so ``path_ids ∈ direct`` selects
    the descendant rows. Everything is tenant-scoped; a lookup failure returns
    only the direct set (never a permissive default).
    """
    direct, primary = await load_direct_department_ids(
        db, tenant_id, user_id, fallback_primary_org_id=fallback_primary_org_id
    )
    if not direct:
        return frozenset(), primary
    if db is None:
        return direct, primary
    try:
        rows = await db[ORG_UNIT_COLLECTION].find(
            add_tenant_scope({"path_ids": {"$in": sorted(direct)}}, tenant_id),
            {"_id": 1},
        ).to_list(length=5000)
        descendants = {
            str(row["_id"]) for row in rows if row.get("_id")
        }
    except Exception as exc:
        _log(f"[memory.viewer] descendant expansion failed (user={user_id}): {exc}")
        descendants = set()
    return frozenset(direct | descendants), primary


async def _load_identity_details(
    db: Any, tenant_id: str, user_id: str, *, fallback_org_id: str = ""
) -> tuple[frozenset[str], frozenset[ProjectKey], frozenset[str], str]:
    role_keys = await load_role_keys(db, tenant_id, user_id)
    project_keys = await load_visible_project_keys(db, tenant_id, user_id)
    department_ids, primary = await load_visible_department_ids(
        db, tenant_id, user_id, fallback_primary_org_id=fallback_org_id
    )
    return role_keys, project_keys, department_ids, primary


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
    authorization: str,
    *,
    db: Optional[Any] = None,
    active_project_id: str = "",
    session_participants: Iterable[str] = (),
) -> MemoryViewerContext:
    """Build the viewer context for an HTTP request (the only auth entry)."""
    from fastapi import HTTPException

    from app.api.endpoints.auth import _resolve_session_user

    resolved = await _resolve_session_user(authorization)
    base = build_viewer_context(
        resolved,
        active_project_id=active_project_id,
        session_participants=session_participants,
    )
    if not base.is_valid:
        # Fail closed: an unresolvable identity must never reach visible_to.
        raise HTTPException(status_code=401, detail="invalid_viewer_context")

    role_keys, project_keys, department_ids, primary = await _load_identity_details(
        _resolve_db(db),
        base.tenant_id,
        base.user_id,
        fallback_org_id=base.primary_department_id,
    )
    return replace(
        base,
        role_keys=role_keys,
        visible_project_keys=project_keys,
        visible_department_ids=department_ids,
        primary_department_id=primary,
    )


async def resolve_viewer_from_identity(
    *,
    tenant_id: str,
    user_id: str,
    db: Optional[Any] = None,
    active_project_id: str = "",
    session_participants: Iterable[str] = (),
) -> MemoryViewerContext:
    """Build the viewer context from trusted ids (RAG runtime, no token).

    ``CapabilityExecutionContext.tenant_id/user_id`` are populated from
    ToolGatewayClaims, not from the model, so they are trusted. Everything
    else is resolved server-side here.
    """
    base = build_viewer_context(
        {"tenant_id": tenant_id, "user": {"_id": user_id}},
        active_project_id=active_project_id,
        session_participants=session_participants,
    )
    if not base.is_valid:
        return base
    role_keys, project_keys, department_ids, primary = await _load_identity_details(
        _resolve_db(db), base.tenant_id, base.user_id
    )
    return replace(
        base,
        role_keys=role_keys,
        visible_project_keys=project_keys,
        visible_department_ids=department_ids,
        primary_department_id=primary,
    )


__all__ = [
    "DEFAULT_PROJECT_ID",
    "FULL_ACCESS_ROLE_KEY",
    "MemoryViewerContext",
    "ProjectKey",
    "build_viewer_context",
    "load_direct_department_ids",
    "load_primary_org_id",
    "load_role_keys",
    "load_visible_department_ids",
    "load_visible_project_keys",
    "resolve_viewer_context",
    "resolve_viewer_from_identity",
]
