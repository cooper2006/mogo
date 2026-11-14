"""RBAC permission-code model (T009).

Permission codes use the ``<resource>:<action>[:<target>]`` form with three-level
isolation (tenant / org / user). Unknown codes are fail-closed.

Position roles (``position_roles`` collection, feature 006) are treated as
*preset groups* of permission codes: ``expand_role_to_codes(role)`` maps a role
document to the set of codes it grants, so the coarse-grained role model and the
fine-grained code model coexist (FR-6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

# Position-role key for the full-access administrator, aligned with feature 006
# (``app.position_roles.constants.FULL_ACCESS_ROLE_KEY``). Kept as a local
# constant so this pure-logic module stays free of DB-driver imports.
FULL_ACCESS_ROLE_KEY = "full_access_admin"

# Coarse agent-capability keys (006) -> the code actions they imply.
# This is the bridge between the existing position-role capability model and the
# fine-grained <resource>:<action> codes introduced by 001.
CAPABILITY_TO_CODES: dict[str, tuple[str, ...]] = {
    "content_generation": ("content:generate",),
    "image_generation": ("image:generate",),
    "code_generation": ("code:execute",),
    "browser_automation": ("browser:automate",),
    "internal_knowledge": ("knowledge:read",),
}

# Wildcard granted to the full-access administrator role.
WILDCARD_CODE = "*"


@dataclass(frozen=True)
class PermissionCode:
    """A parsed ``<resource>:<action>[:<target>]`` permission code."""

    resource: str
    action: str
    target: Optional[str] = None

    @classmethod
    def parse(cls, raw: str) -> "PermissionCode":
        text = (raw or "").strip()
        if not text:
            raise ValueError("permission code must not be empty")
        parts = text.split(":")
        if len(parts) < 2:
            raise ValueError(f"invalid permission code: {raw!r}")
        resource, action = parts[0], parts[1]
        target = ":".join(parts[2:]) if len(parts) > 2 else None
        if not resource or not action:
            raise ValueError(f"invalid permission code: {raw!r}")
        return cls(resource=resource, action=action, target=target or None)

    def __str__(self) -> str:  # pragma: no cover - trivial
        parts = [self.resource, self.action]
        if self.target:
            parts.append(self.target)
        return ":".join(parts)


def parse_codes(raw_codes: Iterable[str]) -> set[str]:
    """Normalize a list of raw codes; invalid codes are dropped (fail-closed later)."""
    normalized: set[str] = set()
    for raw in raw_codes:
        try:
            normalized.add(str(PermissionCode.parse(raw)))
        except ValueError:
            continue
    return normalized


def expand_role_to_codes(role: dict[str, Any]) -> set[str]:
    """Expand a position-role document into the set of permission codes it grants.

    * Full-access admin (``FULL_ACCESS_ROLE_KEY``) -> wildcard ``*``.
    * Otherwise: explicit ``permission_codes`` plus the codes implied by the
      coarse capability flags carried by the role.

    The role document uses ``system_key`` for system roles (e.g. the full-access
    admin) and ``capabilities`` (a dict of coarse flags) — both are honored.
    """
    if not role:
        return set()

    marker = role.get("system_key") or role.get("role_key") or role.get("key")
    if marker == FULL_ACCESS_ROLE_KEY:
        return {WILDCARD_CODE}

    codes: set[str] = set(parse_codes(role.get("permission_codes", []) or []))

    capabilities = role.get("capabilities") or role.get("agent_capabilities") or {}
    if isinstance(capabilities, dict):
        for key, enabled in capabilities.items():
            if enabled:
                codes.update(CAPABILITY_TO_CODES.get(key, ()))
    return codes


def has_permission(granted: set[str], required: str) -> bool:
    """Whether ``granted`` satisfies ``required``.

    Rules:
    * wildcard ``*`` grants everything;
    * an exact match grants;
    * ``<resource>:<action>`` (no target) grants a targeted request;
    * ``<resource>:*`` grants any action on the resource.
    Unknown / malformed required codes never match (fail-closed).
    """
    if not required:
        return False
    if WILDCARD_CODE in granted:
        return True
    try:
        need = PermissionCode.parse(required)
    except ValueError:
        return False
    for raw in granted:
        try:
            have = PermissionCode.parse(raw)
        except ValueError:
            continue
        if have.resource != need.resource:
            continue
        if have.action != need.action and have.action != "*":
            continue
        if need.target and have.target and have.target != need.target:
            continue
        return True
    return False


def required_code_for_tool(tool: str, action: str = "execute", target: str | None = None) -> str:
    """Build the required permission code for invoking a tool."""
    resource = (tool or "").strip() or "tool"
    code = f"{resource}:{action}"
    if target:
        code = f"{code}:{target}"
    return code
