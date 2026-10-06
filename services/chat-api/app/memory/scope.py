"""Memory scope model + visibility (017 FR-1 / FR-2 / FR-3 / FR-4).

Scopes
------
* ``personal``  — visible only to its owner;
* ``workspace`` — visible to members of that workspace;
* ``org``       — visible to the whole organization.

Default scope is chosen by session type (clarify OQ-1): a single-user session
defaults to ``personal``; a multi-user (co-presence) session defaults to
``workspace``. Promotion to ``org`` requires authorization (FR-4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.memory.tiering import SUMMARY_REFRESH_DAYS_DEFAULT

# Role allowed to authorize promotion to the org scope (006 full-access admin).
ORG_PROMOTION_ROLES = frozenset({"full_access_admin"})


class MemoryScope(str, Enum):
    PERSONAL = "personal"
    WORKSPACE = "workspace"
    ORG = "org"


class Visibility(str, Enum):
    OWNER = "owner"          # personal: only the owner
    MEMBERS = "members"      # workspace: its members
    ORGANIZATION = "organization"  # org: everyone in the org


SCOPE_VISIBILITY: dict[str, str] = {
    MemoryScope.PERSONAL.value: Visibility.OWNER.value,
    MemoryScope.WORKSPACE.value: Visibility.MEMBERS.value,
    MemoryScope.ORG.value: Visibility.ORGANIZATION.value,
}


class MemoryAccessError(PermissionError):
    """Raised when a memory operation would exceed the caller's scope."""


@dataclass
class Memory:
    """A single memory record at one scope."""

    content: str = ""
    scope: str = MemoryScope.PERSONAL.value
    owner_id: str = ""
    workspace_id: str = ""
    tenant_id: str = "default"
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


def resolve_default_scope(*, multi_user_session: bool) -> str:
    """Default scope for a session: multi-user -> workspace, else personal."""
    return MemoryScope.WORKSPACE.value if multi_user_session else MemoryScope.PERSONAL.value


def visible_to(
    memory: Memory,
    *,
    viewer_id: str,
    viewer_role: str = "",
    is_workspace_member: bool = False,
) -> bool:
    """Whether ``viewer_id`` may read ``memory`` (FR-2, no privilege escalation).

    * full-access admins may read any scope within the tenant;
    * otherwise visibility follows the scope: owner / member / org.
    """
    if viewer_role in ORG_PROMOTION_ROLES:
        return True
    if memory.scope == MemoryScope.PERSONAL.value:
        return viewer_id == memory.owner_id
    if memory.scope == MemoryScope.WORKSPACE.value:
        return is_workspace_member and viewer_id != ""
    if memory.scope == MemoryScope.ORG.value:
        return viewer_id != ""  # any member of the same tenant
    return False


def can_promote_to_org(*, role: str) -> bool:
    """Whether ``role`` may authorize promotion of a memory to the org scope (FR-4)."""
    return role in ORG_PROMOTION_ROLES


def promote_to_org(memory: Memory, *, role: str) -> Memory:
    """Promote a memory to the org scope, requiring an authorized role (FR-4).

    The promotion is audited by the caller (the authorization decision is made
    here; the audit record is written at the integration layer).
    """
    if not can_promote_to_org(role=role):
        raise MemoryAccessError(f"role {role!r} may not promote memory to the org scope")
    memory.scope = MemoryScope.ORG.value
    # T999: memory promotion → 001 audit stream (017 memory.promoted).
    _audit_memory_promoted(memory, role)
    return memory


def _audit_memory_promoted(memory: Memory, role: str) -> None:
    try:
        from app.services.feature_audit_bridge import emit_feature_event

        emit_feature_event(
            "017",
            "memory.promoted",
            {
                "memory_id": getattr(memory, "memory_id", None),
                "scope": memory.scope,
                "role": role,
            },
        )
    except Exception as exc:
        # 审计失败绝不影响主流程，但必须留痕：静默吞掉会让"审计桥未接线"
        # 与"审计已通过"在日志上无法区分。
        from app.infrastructure.observability.config import log_print

        log_print(
            f"[memory.scope] memory.promoted audit emit failed "
            f"(memory_id={getattr(memory, 'memory_id', None)}): {exc}",
            flush=True,
        )
        pass
