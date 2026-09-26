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

    def __post_init__(self) -> None:
        if self.scope not in SCOPE_VISIBILITY:
            raise ValueError(f"unknown memory scope: {self.scope!r}")

    def visibility(self) -> str:
        return SCOPE_VISIBILITY[self.scope]


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
    except Exception:
        # 审计失败绝不影响主流程。
        pass
