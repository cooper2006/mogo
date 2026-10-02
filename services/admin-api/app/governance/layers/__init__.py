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
    """Instantiate the enabled layers, in canonical order.

    The quota layer is wired to 020's real token-budget check so it is not a
    pass-through in production (001 originally declared a ``quota_limits`` model
    that was never built — see ``layers/quota.py``).
    """
    layers: list[GateLayer] = []
    for name in config.layers_in_order():
        factory = _LAYER_FACTORIES.get(name)
        if factory is None:
            continue
        if name == "quota":
            layers.append(factory(credit_checker=quota.default_credit_checker))
        else:
            layers.append(factory())
    return layers


__all__ = ["build_layers"]
