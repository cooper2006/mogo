"""Memory scope model + visibility (017 v3 / D4 目标态).

Scopes
------
* ``personal``   — visible only to its owner;
* ``project``    — visible to the project owner and 049 ``member_user_ids``;
* ``department`` — visible to the owner's department and **all descendants**.

D4 (user decision 2026-11-06): ``workspace`` / ``org`` were renamed in a single
atomic switch. There is deliberately **no** alias, ``normalize_scope``, dual
write, or field-level fallback here. Old values are converted only by the
offline migration script (``scripts/migrate_017_scopes.py``); at runtime they
are rejected / fail closed.

Security invariants
-------------------
* N1: a ``project`` memory carries ``project_owner_id``. ``projects._id`` is
  *not* unique inside a tenant (unique index is
  ``{tenant_id, user_id, workspace_id}``), so visibility must compare the
  ``(project_id, project_owner_id)`` pair.
* N2: the 049 tenant-wide fallback row ``_id="default"`` must never carry a
  project memory; 049's product exemption is intentionally not inherited.
* B-7: unknown scope, cross-tenant, missing owner id and archived records are
  all invisible.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from app.memory.tiering import SUMMARY_REFRESH_DAYS_DEFAULT

# Role allowed to authorize promotion to the department scope (006 admin).
DEPARTMENT_PROMOTION_ROLES = frozenset({"full_access_admin"})

#: 049 tenant-wide fallback project (N2). Never a valid memory scope target.
DEFAULT_PROJECT_ID = "default"

# ── Promotion approval state machine (T035) ───────────────────────────────
# A normal user *requests* promotion of their memory to ``department``; it
# enters ``pending`` and a full-access admin *approves* (promotes) or *rejects*.
# ``none`` is the default (no request ever made / direct admin promote).
PROMOTION_STATUS_NONE = "none"
PROMOTION_STATUS_PENDING = "pending"
PROMOTION_STATUS_APPROVED = "approved"
PROMOTION_STATUS_REJECTED = "rejected"
PROMOTION_STATUSES = frozenset(
    {PROMOTION_STATUS_NONE, PROMOTION_STATUS_PENDING, PROMOTION_STATUS_APPROVED, PROMOTION_STATUS_REJECTED}
)


class MemoryScope(str, Enum):
    PERSONAL = "personal"
    PROJECT = "project"
    DEPARTMENT = "department"


class Visibility(str, Enum):
    OWNER = "owner"                          # personal: only the owner
    PROJECT_MEMBERS = "project_members"      # project: owner + member_user_ids
    DEPARTMENT_SUBTREE = "department_subtree"  # department: self + descendants


SCOPE_VISIBILITY: dict[str, str] = {
    MemoryScope.PERSONAL.value: Visibility.OWNER.value,
    MemoryScope.PROJECT.value: Visibility.PROJECT_MEMBERS.value,
    MemoryScope.DEPARTMENT.value: Visibility.DEPARTMENT_SUBTREE.value,
}


class MemoryAccessError(PermissionError):
    """Raised when a memory operation would exceed the caller's scope."""


@dataclass
class Memory:
    """A single memory record at one scope.

    ``project_owner_id`` is appended (rather than inserted) so existing
    positional constructors keep working through the D4 rename.
    """

    content: str = ""
    scope: str = MemoryScope.PERSONAL.value
    owner_id: str = ""
    project_id: str = ""            # was workspace_id
    tenant_id: str = "default"
    department_id: str = ""         # was org_id
    created_at: float = 0.0
    last_accessed_at: float = 0.0
    memory_id: str = ""
    archived: bool = False  # FR-8: stamped when the decay sweep archives it.
    # --- 017 FR-13 density tiers (L0/L1/L2) ---
    l0_summary: str = ""       # one-line summary (relevance pre-filter)
    l1_overview: str = ""      # key points / structure (retrieval direction)
    l2_raw: str = ""           # raw detail (== content when tierable)
    tierable: bool = True      # False → not summarizable (binary/opaque)
    summary_generated_at: float = 0.0
    summary_refresh_days: int = SUMMARY_REFRESH_DAYS_DEFAULT
    # --- 017 FR-19 provenance (session sedimentation) ---
    source_session_id: str = ""
    source_type: str = ""      # "" | "session"
    # --- N1: disambiguates duplicate projects._id values within a tenant ---
    project_owner_id: str = ""
    # --- Promotion approval state machine (T035) ---
    promotion_status: str = PROMOTION_STATUS_NONE
    pending_department_id: str = ""
    promotion_requested_by: str = ""
    promotion_requested_at: float = 0.0
    promotion_reason: str = ""
    promotion_resolved_by: str = ""
    promotion_resolved_at: float = 0.0
    # --- T037 offboarding / deletion explicit invalidation (H-3 / H-6) ---
    # When True the memory is explicitly taken out of active retrieval: a normal
    # viewer can no longer see it, and it exits RAG default retrieval. Admin
    # governance may still list it (flagged) for audit / restore.
    invalidated: bool = False
    invalidated_at: float = 0.0
    invalidated_reason: str = ""

    def __post_init__(self) -> None:
        if self.scope not in SCOPE_VISIBILITY:
            raise ValueError(f"unknown memory scope: {self.scope!r}")

    def visibility(self) -> str:
        return SCOPE_VISIBILITY[self.scope]

    def addr(self, tier: str = "L0") -> str:
        """Resolve this memory's ``mogo://memory/...`` address (FR-18)."""
        from app.memory.address import MemoryAddress

        return MemoryAddress(
            scope=self.scope, owner_id=self.owner_id, memory_id=self.memory_id, tier=tier
        ).uri()


def resolve_default_scope(
    *, multi_user_session: bool = False, has_project_context: bool = False
) -> str:
    """D2: a usable project context yields ``project``; otherwise ``personal``.

    ``multi_user_session`` is kept in the signature because the 009 sediment
    seam passes it; without a real (non-``default``, resolvable) project context
    even a co-presence session falls back to ``personal`` (N2 / E-4).
    """
    return (
        MemoryScope.PROJECT.value
        if has_project_context
        else MemoryScope.PERSONAL.value
    )


def _field(memory: Memory | Mapping[str, Any], name: str) -> Any:
    if isinstance(memory, Mapping):
        return memory.get(name)
    return getattr(memory, name, None)


def visible_to(memory: Memory | Mapping[str, Any], viewer: Any) -> bool:
    """The **single** visibility predicate for 017 (B-4 / T013).

    ``viewer`` must be a server-built :class:`app.memory.viewer.MemoryViewerContext`.
    The old scattered keyword arguments (``viewer_id`` / ``viewer_role`` /
    ``is_workspace_member`` / ``viewer_org_id``) are gone with D4: accepting them
    again would re-open the P0 identity hole B1 closed.
    """
    from app.memory.viewer import MemoryViewerContext

    if not isinstance(viewer, MemoryViewerContext) or not viewer.is_valid:
        return False

    # Cross-tenant fail-closed (B-7).
    if str(_field(memory, "tenant_id") or "") != viewer.tenant_id:
        return False
    if bool(_field(memory, "archived")):
        return False
    # T037 (H-3): explicitly invalidated memories (offboarding / deletion) are
    # invisible to every normal viewer — they exit active RAG retrieval too.
    if bool(_field(memory, "invalidated")):
        return False

    scope = str(_field(memory, "scope") or "")
    if scope not in SCOPE_VISIBILITY:
        return False

    # B-7 / N1 / N2: structural integrity is checked **before** the admin
    # shortcut. A malformed record (missing owner, missing project_owner_id,
    # the tenant-wide "default" row, or a missing department id) stays
    # invisible even to a full-access admin; the migration archives it and the
    # governance surface reads it through a separate, audited path.
    if scope == MemoryScope.PERSONAL.value:
        if not str(_field(memory, "owner_id") or ""):
            return False
    elif scope == MemoryScope.PROJECT.value:
        project_id = str(_field(memory, "project_id") or "")
        project_owner_id = str(_field(memory, "project_owner_id") or "")
        if not project_id or not project_owner_id:
            return False
        if project_id == DEFAULT_PROJECT_ID:
            return False
    elif scope == MemoryScope.DEPARTMENT.value:
        if not str(_field(memory, "department_id") or ""):
            return False

    # 006 full-access admins govern every *valid, well-formed, unarchived*
    # scope inside their own tenant.
    if viewer.is_full_access_admin:
        return True

    if scope == MemoryScope.PERSONAL.value:
        return str(_field(memory, "owner_id") or "") == viewer.user_id

    if scope == MemoryScope.PROJECT.value:
        project_id = str(_field(memory, "project_id") or "")
        project_owner_id = str(_field(memory, "project_owner_id") or "")
        return (project_id, project_owner_id) in viewer.visible_project_keys

    if scope == MemoryScope.DEPARTMENT.value:
        department_id = str(_field(memory, "department_id") or "")
        return department_id in viewer.visible_department_ids

    return False


def can_promote_to_department(viewer: Any) -> bool:
    """G-1: only a 006 full-access admin may promote to ``department``."""
    return bool(getattr(viewer, "is_full_access_admin", False))


def promote_to_department(memory: Memory, *, viewer: Any, department_id: str) -> Memory:
    """Promote a memory to ``department`` (G-1 / G-2).

    The target department must be inside the viewer's visible department set,
    so an admin cannot inject a memory into an unrelated department.
    """
    if not can_promote_to_department(viewer):
        raise MemoryAccessError("full_access_admin required to promote to department")
    visible_departments = getattr(viewer, "visible_department_ids", frozenset())
    if not department_id or department_id not in visible_departments:
        raise MemoryAccessError(
            f"department {department_id!r} is not visible to the caller"
        )
    memory.scope = MemoryScope.DEPARTMENT.value
    memory.department_id = department_id
    _audit_memory_promoted(memory, viewer)
    return memory


def _audit_memory_promoted(memory: Memory, viewer: Any) -> None:
    try:
        from app.services.feature_audit_bridge import emit_feature_event

        emit_feature_event(
            "017",
            "memory.promoted",
            {
                "memory_id": getattr(memory, "memory_id", None),
                "scope": memory.scope,
                "department_id": memory.department_id,
                "role_keys": sorted(getattr(viewer, "role_keys", ()) or ()),
            },
            tenant_id=getattr(viewer, "tenant_id", ""),
            actor=getattr(viewer, "user_id", ""),
        )
    except Exception as exc:
        # 审计失败绝不影响主流程，但必须留痕：静默吞掉会让「审计桥未接线」
        # 与「审计已通过」在日志上无法区分。
        from app.infrastructure.observability.config import log_print

        log_print(
            f"[memory.scope] memory.promoted audit emit failed "
            f"(memory_id={getattr(memory, 'memory_id', None)}): {exc}",
            flush=True,
        )


__all__ = [
    "DEFAULT_PROJECT_ID",
    "DEPARTMENT_PROMOTION_ROLES",
    "Memory",
    "MemoryAccessError",
    "MemoryScope",
    "SCOPE_VISIBILITY",
    "Visibility",
    "can_promote_to_department",
    "promote_to_department",
    "resolve_default_scope",
    "visible_to",
]
