"""Harness thickness profile + dimension resolution (019 FR-2 / FR-3 / FR-4).

A profile declares the gate mode (thick/thin) for a scope (scene / tenant / tool).
Resolution precedence is **scene > tenant > tool** (more specific wins — clarify
OQ-1), and switching takes effect at the **tool-call level** (clarify OQ-5): each
call resolves the effective profile from its scene + tenant + tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .floor import assert_floor_intact
from .layer_switch import THICK_MODE, resolve_layers

# Dimension precedence: a scene beats a tenant, which beats a tool.
DIMENSION_PRIORITY: dict[str, int] = {"tool": 1, "tenant": 2, "scene": 3}

# Default audit granularity per mode.
THICK_AUDIT_GRANULARITY = "full"
THIN_AUDIT_GRANULARITY = "minimal"


@dataclass
class HarnessProfile:
    """A thickness profile for one (scope, key) pair."""

    scope: str = "scene"            # scene | tenant | tool
    key: str = ""
    mode: str = THICK_MODE
    enabled_layers: Optional[list[str]] = None
    audit_granularity: str = ""
    timeout_seconds: float = 0.0

    def resolved_layers(self) -> list[str]:
        return resolve_layers(self.mode, enabled=self.enabled_layers)

    def resolved_audit_granularity(self) -> str:
        if self.audit_granularity:
            return self.audit_granularity
        return THIN_AUDIT_GRANULARITY if self.mode == "thin" else THICK_AUDIT_GRANULARITY

    def validate(self) -> None:
        assert_floor_intact(enabled_layers=self.resolved_layers(), audit_enabled=True)


@dataclass
class ProfileResolver:
    """Resolves the effective profile for a tool call (dimension precedence)."""

    profiles: list[HarnessProfile] = field(default_factory=list)

    def add(self, profile: HarnessProfile) -> None:
        profile.validate()
        self.profiles.append(profile)

    def _find(self, scope: str, key: str) -> Optional[HarnessProfile]:
        for profile in self.profiles:
            if profile.scope == scope and profile.key == key:
                return profile
        return None

    def resolve(
        self,
        *,
        scene: str = "",
        tenant: str = "",
        tool: str = "",
    ) -> HarnessProfile:
        """Effective profile: scene > tenant > tool, else the thick default (FR-8)."""
        candidates = (
            ("scene", scene),
            ("tenant", tenant),
            ("tool", tool),
        )
        for scope, key in candidates:
            if not key:
                continue
            found = self._find(scope, key)
            if found is not None:
                return found
        return HarnessProfile(scope="default", key="", mode=THICK_MODE)

    def effective_layers(self, *, scene: str = "", tenant: str = "", tool: str = "") -> list[str]:
        return self.resolve(scene=scene, tenant=tenant, tool=tool).resolved_layers()
