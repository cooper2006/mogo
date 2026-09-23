"""Six gate layers + the ``build_layers`` factory (T003).

Each layer implements ``async def evaluate(ctx) -> GateVerdict`` (the ``GateLayer``
protocol from ``gatekeeper.py``). ``build_layers`` assembles the enabled layers in
canonical order based on the resolved ``GateConfig``.
"""

from __future__ import annotations

from ..config import GateConfig
from ..gatekeeper import GateLayer
from . import approval, audit, identity, quota, rbac, redaction

_LAYER_FACTORIES: dict[str, type] = {
    "identity": identity.IdentityLayer,
    "rbac": rbac.RbacLayer,
    "redaction": redaction.RedactionLayer,
    "approval": approval.ApprovalLayer,
    "quota": quota.QuotaLayer,
    "audit": audit.AuditLayer,
}


def build_layers(config: GateConfig) -> list[GateLayer]:
    """Instantiate the enabled layers, in canonical order."""
    layers: list[GateLayer] = []
    for name in config.layers_in_order():
        factory = _LAYER_FACTORIES.get(name)
        if factory is not None:
            layers.append(factory())
    return layers


__all__ = ["build_layers"]
