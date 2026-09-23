"""Adapter from harness thickness profiles to the 001 gate chain (019 T014).

019 decides **which layers run**; 001 defines what each layer *does*. This module
bridges the two:

* the enabled layer set comes from the resolved profile (thick/thin);
* the transition period mounts ``approval_runtime`` + ``audit`` directly when the
  001 gatekeeper is not yet wired (clarify OQ-3);
* the audit floor is preserved in thin mode (never dropped).

The adapter is pure logic (no imports of the gatekeeper implementation), so it can
be unit-tested and swapped for the real chain once 001 lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .floor import assert_floor_intact
from .layer_switch import CANONICAL_LAYERS, REQUIRED_LAYERS

# Whether the 001 gatekeeper is available yet (transition flag, clarify OQ-3).
GATEKEEPER_READY = "gatekeeper"
TRANSITION = "transition"

# Layer names that map 1:1 onto 001's chain.
GATE_LAYER_NAMES: tuple[str, ...] = CANONICAL_LAYERS


class GateAdapterError(ValueError):
    """Raised when a profile cannot be mapped onto the gate chain."""


@dataclass
class GatePlan:
    """The concrete plan for running a tool call under a thickness profile."""

    mode: str
    layers: list[str]
    backend: str                       # gatekeeper | transition
    audit_granularity: str
    skipped_layers: list[str] = field(default_factory=list)
    timeout_seconds: float = 0.0

    @property
    def is_thin(self) -> bool:
        return self.mode == "thin"

    def audit_enabled(self) -> bool:
        return "audit" in self.layers


def build_gate_plan(
    *,
    mode: str,
    enabled_layers: Iterable[str] | None = None,
    audit_granularity: str = "",
    timeout_seconds: float = 0.0,
    backend: str = TRANSITION,
) -> GatePlan:
    """Map a thickness profile onto a concrete gate plan (FR-3 / FR-4 / FR-5).

    Rejects any plan that would breach the floor (required layers missing or the
    audit layer dropped) — the config-side guard (FR-8).
    """
    from .layer_switch import resolve_layers

    layers = resolve_layers(mode, enabled=list(enabled_layers) if enabled_layers is not None else None)
    assert_floor_intact(enabled_layers=layers, audit_enabled=True)

    if backend not in (GATEKEEPER_READY, TRANSITION):
        raise GateAdapterError(f"unknown gate backend: {backend!r}")

    skipped = [name for name in CANONICAL_LAYERS if name not in layers]
    granularity = audit_granularity or ("minimal" if mode == "thin" else "full")
    return GatePlan(
        mode=mode,
        layers=layers,
        backend=backend,
        audit_granularity=granularity,
        skipped_layers=skipped,
        timeout_seconds=float(timeout_seconds),
    )


def backend_for(gatekeeper_available: bool) -> str:
    """Transition-period backend selection (clarify OQ-3).

    019 runs standalone on ``approval_runtime``/``audit`` until the 001 gatekeeper
    is available, then switches to it without blocking.
    """
    return GATEKEEPER_READY if gatekeeper_available else TRANSITION


def describe_plan(plan: GatePlan) -> dict[str, object]:
    """A JSON-friendly description of a gate plan (for audit / diagnostics)."""
    return {
        "mode": plan.mode,
        "backend": plan.backend,
        "layers": list(plan.layers),
        "skippedLayers": list(plan.skipped_layers),
        "auditGranularity": plan.audit_granularity,
        "auditEnabled": plan.audit_enabled(),
        "timeoutSeconds": plan.timeout_seconds,
    }
