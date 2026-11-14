"""Resolve a session's project context into the 017 N1 tuple (E-2 / T021).

046 unified the project dimension: ``chat_sessions`` carries ``project_id``
(with ``workspace_id`` retained as a legacy session value source). 017 must
not just copy that id into a memory — ``projects._id`` is not unique inside a
tenant (the unique index is ``{tenant_id, user_id, workspace_id}``), so the
memory also needs the project's creator (``projects.user_id``) to form the
``(project_id, project_owner_id)`` visibility key (N1).

The 049 tenant-wide ``"default"`` row is rejected outright (N2); callers then
fall back to ``personal`` rather than writing a tenant-visible project memory.
Ambiguous (multiple rows) or missing projects also resolve to empty rather
than picking a row — a guessed owner would leak memories across users.
"""

from __future__ import annotations

from typing import Any

from app.core.tenant import add_tenant_scope
from app.memory.scope import DEFAULT_PROJECT_ID

PROJECT_COLLECTION = "projects"


def session_project_id(session_doc: dict[str, Any]) -> str:
    """046 session value-source priority for the project id.

    This is a *value source* priority, not a D4 field-fallback read: the
    memory document itself only ever stores ``project_id``.
    """
    return str(
        session_doc.get("project_id")
        or session_doc.get("workspace_id")
        or ""
    ).strip()


async def resolve_project_context(
    db: Any, *, tenant_id: str, session_doc: dict[str, Any]
) -> tuple[str, str]:
    """Return ``(project_id, project_owner_id)``; empty on any ambiguity.

    Fail-closed by design: no project row, no ``user_id``, the ``default``
    fallback row, or more than one row with the same ``_id`` all yield
    ``("", "")`` so the caller sedimentates to ``personal`` instead.
    """
    project_id = session_project_id(session_doc)
    if not project_id or project_id == DEFAULT_PROJECT_ID or db is None:
        return "", ""
    try:
        rows = await db[PROJECT_COLLECTION].find(
            add_tenant_scope({"_id": project_id}, tenant_id),
            {"_id": 1, "user_id": 1, "status": 1},
        ).to_list(length=None)
    except Exception as exc:
        from app.infrastructure.observability.config import log_print

        log_print(
            f"[memory.project_context] project lookup failed "
            f"(project_id={project_id}): {exc}",
            flush=True,
        )
        return "", ""
    if len(rows) != 1:
        return "", ""
    row = rows[0]
    if str(row.get("status") or "active") == "archived":
        return "", ""
    owner_id = str(row.get("user_id") or "")
    if not owner_id:
        return "", ""
    return project_id, owner_id


__all__ = ["PROJECT_COLLECTION", "resolve_project_context", "session_project_id"]
