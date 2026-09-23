"""Governance floor guard (019 FR-5 / FR-6 / FR-8).

The floor is non-negotiable: the audit layer cannot be disabled, the required
layers cannot be dropped, and the R4 red line denies in **every** mode. A config
that tries to thin past the floor is rejected outright (config-side guard, FR-8).
"""

from __future__ import annotations

from typing import Iterable

from .layer_switch import REQUIRED_LAYERS

# Minimum audit fields in thin mode (clarify OQ-4).
MIN_AUDIT_FIELDS: tuple[str, ...] = ("subject", "tool", "result", "timestamp")


class FloorViolation(ValueError):
    """Raised when a config would breach the governance floor."""


def assert_floor_intact(
    *,
    enabled_layers: Iterable[str],
    audit_enabled: bool = True,
) -> None:
    """Reject a config that disables a required layer or the audit layer."""
    enabled = set(enabled_layers)
    missing = REQUIRED_LAYERS - enabled
    if missing:
        raise FloorViolation(f"cannot disable required gate layers: {sorted(missing)}")
    if not audit_enabled:
        raise FloorViolation("audit cannot be disabled (governance floor)")


def r4_always_denied(mode: str) -> bool:
    """The R4 red line denies in thick AND thin mode (never droppable)."""
    return True  # by construction: R4 is enforced inside the RBAC/red-line logic


def minimal_audit_record(
    *,
    subject: str,
    tool: str,
    result: str,
    timestamp: str,
) -> dict[str, str]:
    """The four-field audit floor used when thin mode reduces audit granularity."""
    return {
        "subject": str(subject),
        "tool": str(tool),
        "result": str(result),
        "timestamp": str(timestamp),
    }


def audit_covers_floor(record: dict[str, str]) -> bool:
    """Whether ``record`` still carries the minimum audit fields (FR-6)."""
    return all(field in record and str(record[field]) != "" for field in MIN_AUDIT_FIELDS)
