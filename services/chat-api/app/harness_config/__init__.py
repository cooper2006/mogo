"""Harness elastic config (feature 019) — thick/thin gate-layer switching.

019 does **not** change the semantics of the 001 six-layer gate; it is the switch
layer that decides *which layers are enabled* per scene / tenant / tool.

* thick mode  — all six layers enabled (the default);
* thin mode   — approval (layer 4) + quota (layer 5) may be dropped, but identity,
  RBAC, redaction, audit and the R4 red line are never droppable.

This package holds the dependency-light core (profile / layer switch / floor), so
it is unit-testable without the DSH runtime or a database.
"""

from __future__ import annotations

from .layer_switch import CANONICAL_LAYERS, DROPPABLE_LAYERS, REQUIRED_LAYERS, resolve_layers
from .floor import FloorViolation, assert_floor_intact
from .gate_adapter import GatePlan, build_gate_plan
from .profile import HarnessProfile, ProfileResolver

__all__ = [
    "CANONICAL_LAYERS",
    "DROPPABLE_LAYERS",
    "REQUIRED_LAYERS",
    "resolve_layers",
    "FloorViolation",
    "assert_floor_intact",
    "HarnessProfile",
    "ProfileResolver",
    "GatePlan",
    "build_gate_plan",
]
