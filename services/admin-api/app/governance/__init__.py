"""Unified six-layer gatekeeper (governance & risk control).

This package implements the six-layer serial gate chain for tool invocations:

    identity -> RBAC -> PII redaction -> approval -> quota -> audit

Any layer may short-circuit the chain; the rejection reason is recorded in the
audit sink. The gate is declarative: layers can be enabled/disabled and reordered
via config, without changing code (see ``config.py``).
"""

from __future__ import annotations

from .gatekeeper import GateContext, GateVerdict, Gatekeeper, gatekeeper

__all__ = [
    "GateContext",
    "GateVerdict",
    "Gatekeeper",
    "gatekeeper",
]
