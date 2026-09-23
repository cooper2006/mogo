"""Declarative gate configuration (T002).

The six-layer chain is data-driven: which layers are enabled, their order, and
the audit switch are config, not code. Default is the "thick" mode (all layers);
degradation to a thinner chain must be explicit (FR-10 / FR-8).

Storage: ``gatekeeper_rules`` collection (``kind = "gate_config"``), with a
static default used when no override is present.
"""

from __future__ import annotations

import datetime
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

# NOTE: ``app.core.db`` (and thus the MongoDB driver) is imported lazily inside
# ``load_gate_config`` so that the pure declarative-config logic stays importable
# without a DB driver (keeps unit tests dependency-light).

# Canonical layer order. The chain always short-circuits in this order.
CANONICAL_LAYER_ORDER: tuple[str, ...] = (
    "identity",
    "rbac",
    "redaction",
    "approval",
    "quota",
    "audit",
)

# Layers that may never be disabled (constitution III + 001 FR-4/FR-9):
# identity, RBAC, redaction, audit are the floor; the red-line rule is enforced
# inside the RBAC/approval layers regardless of config.
REQUIRED_LAYERS: frozenset[str] = frozenset({"identity", "rbac", "redaction", "audit"})

GATE_CONFIG_COLLECTION = "gatekeeper_rules"


class GateConfigError(ValueError):
    """Raised when a config tries to disable a required layer."""


@dataclass
class GateConfig:
    """Resolved gate configuration."""

    enabled_layers: list[str] = field(default_factory=lambda: list(CANONICAL_LAYER_ORDER))
    audit_enabled: bool = True
    mode: str = "thick"  # thick | thin
    tenant_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    def layers_in_order(self) -> list[str]:
        """Enabled layers, preserving canonical order."""
        enabled = set(self.enabled_layers)
        return [name for name in CANONICAL_LAYER_ORDER if name in enabled]

    def validate(self) -> None:
        missing = REQUIRED_LAYERS - set(self.enabled_layers)
        if missing:
            raise GateConfigError(
                f"cannot disable required gate layers: {sorted(missing)}"
            )
        if not self.audit_enabled:
            raise GateConfigError("audit cannot be disabled (governance floor)")

    def for_tenant(self, tenant_id: str | None) -> "GateConfig":
        override = self.tenant_overrides.get(tenant_id or "")
        if not override:
            return self
        layers = override.get("enabled_layers", self.enabled_layers)
        return GateConfig(
            enabled_layers=list(layers),
            audit_enabled=bool(override.get("audit_enabled", self.audit_enabled)),
            mode=str(override.get("mode", self.mode)),
            tenant_overrides=self.tenant_overrides,
        )


def default_config() -> GateConfig:
    """Thick mode by default: all six layers enabled."""
    return GateConfig()


def config_from_document(document: dict[str, Any] | None) -> GateConfig:
    if not document:
        return default_config()
    config = GateConfig(
        enabled_layers=list(document.get("enabled_layers", CANONICAL_LAYER_ORDER)),
        audit_enabled=bool(document.get("audit_enabled", True)),
        mode=str(document.get("mode", "thick")),
        tenant_overrides=dict(document.get("tenant_overrides", {})),
    )
    config.validate()
    return config


def load_gate_config() -> GateConfig:
    """Load the gate config from MongoDB, falling back to the thick default.

    Never raises on a missing store: an unavailable config degrades to the
    thick default (fail-safe), never to a thinner chain.
    """
    try:
        from app.core.db import get_db

        db = get_db()
    except Exception:
        return default_config()
    try:
        document = db[GATE_CONFIG_COLLECTION].find_one({"kind": "gate_config"})
    except Exception:
        return default_config()
    try:
        return config_from_document(document)
    except GateConfigError:
        # A misconfigured store must not silently thin the chain.
        return default_config()


def layer_enabled(name: str, config: GateConfig | None = None) -> bool:
    cfg = config or load_gate_config()
    return name in cfg.layers_in_order()


def gate_config_env_override() -> list[str] | None:
    """Optional env override for tests / local runs, e.g. ``GATE_LAYERS=identity,rbac,audit``."""
    raw = os.getenv("GATE_LAYERS", "").strip()
    if not raw:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


async def save_gate_config(config: GateConfig, *, actor: str = "system") -> None:
    """Persist a validated gate config and record the change in the audit sink (T030).

    The config must pass ``validate`` first (required layers + audit floor);
    an invalid config raises before any write happens. The audit entry lands in
    ``gate_events`` so "config changed" is traceable (FR-10).
    """
    config.validate()
    from app.core.db import get_db

    db = get_db()
    document = {
        "kind": "gate_config",
        "enabled_layers": list(config.enabled_layers),
        "audit_enabled": bool(config.audit_enabled),
        "mode": str(config.mode),
        "tenant_overrides": config.tenant_overrides or {},
        "updated_by": actor,
        "updated_at": datetime.datetime.now(datetime.timezone.utc),
    }
    await db[GATE_CONFIG_COLLECTION].update_one({"kind": "gate_config"}, {"$set": document}, upsert=True)

    from .layers.audit import GATE_EVENTS_COLLECTION

    await db[GATE_EVENTS_COLLECTION].insert_one(
        {
            "event_id": uuid.uuid4().hex,
            "occurred_at": document["updated_at"],
            "tenant_id": "",
            "user_id": actor,
            "roles": [],
            "tool": "gate.config.update",
            "risk_level": "",
            "autonomy_level": "",
            "decision": "allow",
            "layer": "config_admin",
            "reason": "gate config updated",
            "detail": {"mode": document["mode"], "enabled_layers": document["enabled_layers"]},
        }
    )
