"""Six-layer gatekeeper orchestration.

``Gatekeeper.evaluate`` runs the enabled gate layers in declared order and
short-circuits on the first rejection. The layer chain is driven by
``config.GateConfig`` so layers may be enabled/disabled without code changes.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

from .config import GateConfig, load_gate_config


class GateDecision(str, Enum):
    """Per-layer (and overall) gate verdict."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


# Denial reasons map to HTTP status codes at the API boundary (FR-1):
#   identity / RBAC / red-line  -> 403
#   approval pending            -> 409 (+ approval token)
#   quota exceeded              -> 429
DENIAL_STATUS = {
    "identity": 403,
    "rbac": 403,
    "redaction": 403,
    "approval": 409,
    "quota": 429,
    "audit": 500,
}


@dataclass
class GateContext:
    """Immutable-ish call context passed through every layer.

    A layer may annotate ``annotations`` (e.g. the audit layer records the final
    verdict) but must not change the caller identity or the tool name.
    """

    tool: str
    tenant_id: str = ""
    user_id: str = ""
    roles: list[str] = field(default_factory=list)
    risk_level: Optional[str] = None          # R0..R4
    autonomy_level: Optional[str] = None      # L1..L5
    request: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)
    scope: str = "tool"                       # tool | session | tenant
    session_id: str = ""
    annotations: dict[str, Any] = field(default_factory=dict)

    def actor(self) -> str:
        return self.user_id or self.tenant_id or "anonymous"


@dataclass
class GateVerdict:
    """Outcome of a single layer (and, aggregated, of the whole chain)."""

    decision: GateDecision
    layer: str
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.decision is GateDecision.ALLOW

    @property
    def status_code(self) -> int:
        return DENIAL_STATUS.get(self.layer, 403)


@runtime_checkable
class GateLayer(Protocol):
    """Uniform layer contract (T003)."""

    name: str

    async def evaluate(self, ctx: GateContext) -> GateVerdict:  # pragma: no cover - protocol
        ...


class Gatekeeper:
    """Runs the enabled six-layer chain in order, short-circuiting on deny."""

    def __init__(self, config: GateConfig | None = None) -> None:
        self._config = config

    @property
    def config(self) -> GateConfig:
        if self._config is None:
            self._config = load_gate_config()
        return self._config

    def _resolve_layers(self) -> list[GateLayer]:
        from .layers import build_layers

        return build_layers(self.config)

    async def evaluate(self, tool: str, ctx: GateContext | None = None) -> GateVerdict:
        """Evaluate ``tool`` against the enabled chain.

        Returns the first non-allow verdict, or an allow verdict if every layer
        passes. The audit layer (last) always runs so that both pass and reject
        events are recorded (FR-9).
        """
        context = ctx if ctx is not None else GateContext(tool=tool)
        if not context.tool:
            context.tool = tool

        layers = self._resolve_layers()
        # The audit layer must be set aside *before* running the chain: because it
        # sits last, a mid-chain rejection would otherwise return before we ever
        # reach it, and the reject event would never be recorded (FR-9).
        audit_layer: GateLayer | None = None
        chain: list[GateLayer] = []
        for layer in layers:
            if layer.name == "audit":
                audit_layer = layer
            else:
                chain.append(layer)

        for layer in chain:
            verdict = await layer.evaluate(context)
            if verdict.decision is not GateDecision.ALLOW:
                await self._record(audit_layer, context, verdict)
                return verdict

        final = GateVerdict(decision=GateDecision.ALLOW, layer="gatekeeper", reason="all layers passed")
        await self._record(audit_layer, context, final)
        return final

    async def _record(self, audit_layer: GateLayer | None, ctx: GateContext, verdict: GateVerdict) -> None:
        if audit_layer is None:
            return
        ctx.annotations["verdict"] = verdict
        await audit_layer.evaluate(ctx)  # audit layer inspects ctx.annotations["verdict"]


# Module-level default instance (config loaded lazily).
gatekeeper = Gatekeeper()
