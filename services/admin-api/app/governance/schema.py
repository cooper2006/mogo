"""Collection setup for the governance module (T007).

Creates the collections and indexes used by the gatekeeper. All storage lives in
the existing MongoDB instance (no new storage engine, per clarify OQ-2).

Collections
-----------
gatekeeper_rules   declarative gate config / per-layer rules (kind = "gate_config")
risk_tiers         R0-R4 tool risk registration
autonomy_matrix    the 25-cell AUTONOMY_MATRIX[L][R]
pii_policies       global defaults + tenant overrides
quota_counters     three-dimension counters (tenant / user / tool)
gate_events        audit trail of every gate evaluation
"""

from __future__ import annotations

from typing import Any

from .config import GATE_CONFIG_COLLECTION, default_config
from .layers.audit import GATE_EVENTS_COLLECTION

# NOTE: ``app.core.db`` is imported lazily inside ``ensure_indexes`` so that the
# canonical matrix / default policy constants stay importable without a DB driver.

RISK_TIERS_COLLECTION = "risk_tiers"
AUTONOMY_MATRIX_COLLECTION = "autonomy_matrix"
PII_POLICIES_COLLECTION = "pii_policies"
QUOTA_COUNTERS_COLLECTION = "quota_counters"

# The canonical 25-cell matrix (L1-L5 x R0-R4), see spec 001 "25 格 AUTONOMY_MATRIX".
AUTONOMY_MATRIX: dict[str, dict[str, str]] = {
    "L1": {"R0": "allow", "R1": "allow", "R2": "allow", "R3": "require_approval", "R4": "deny"},
    "L2": {"R0": "allow", "R1": "allow", "R2": "allow", "R3": "require_approval", "R4": "deny"},
    "L3": {"R0": "allow", "R1": "allow", "R2": "require_approval", "R3": "require_approval", "R4": "deny"},
    "L4": {"R0": "allow", "R1": "allow", "R2": "require_approval", "R3": "require_approval", "R4": "deny"},
    "L5": {"R0": "allow", "R1": "allow", "R2": "allow", "R3": "require_approval", "R4": "deny"},
}

# Global default PII policy (clarify OQ-3).
DEFAULT_PII_POLICY: dict[str, str] = {
    "private_key": "remove",
    "id_card": "hash",
    "bank_card": "mask",
    "phone": "mask",
    "email": "abstract",
}


async def ensure_indexes() -> None:
    """Idempotently create collections / indexes and seed defaults."""
    from app.core.db import get_db

    db = get_db()

    await db[GATE_CONFIG_COLLECTION].create_index("kind", unique=True, name="gate_config_kind")
    await db[RISK_TIERS_COLLECTION].create_index([("tenant_id", 1), ("tool", 1)], name="risk_tier_tenant_tool")
    await db[AUTONOMY_MATRIX_COLLECTION].create_index("cell", unique=True, name="autonomy_matrix_cell")
    await db[PII_POLICIES_COLLECTION].create_index([("tenant_id", 1), ("pii_type", 1)], name="pii_policy_tenant_type")
    await db[QUOTA_COUNTERS_COLLECTION].create_index(
        [("tenant_id", 1), ("dimension", 1), ("subject", 1), ("window", 1)],
        name="quota_counter_key",
    )
    await db[GATE_EVENTS_COLLECTION].create_index(
        [("tenant_id", 1), ("occurred_at", -1)], name="gate_events_tenant_time"
    )

    await _seed_defaults(db)


async def _seed_defaults(db: Any) -> None:
    """Seed the gate config, matrix cells, and default PII policy if absent."""
    if await db[GATE_CONFIG_COLLECTION].count_documents({"kind": "gate_config"}) == 0:
        config = default_config()
        await db[GATE_CONFIG_COLLECTION].insert_one(
            {
                "kind": "gate_config",
                "enabled_layers": config.enabled_layers,
                "audit_enabled": config.audit_enabled,
                "mode": config.mode,
                "tenant_overrides": {},
            }
        )

    if await db[AUTONOMY_MATRIX_COLLECTION].count_documents({}) == 0:
        documents = [
            {"cell": f"{level}:{risk}", "level": level, "risk": risk, "decision": decision}
            for level, risks in AUTONOMY_MATRIX.items()
            for risk, decision in risks.items()
        ]
        if documents:
            await db[AUTONOMY_MATRIX_COLLECTION].insert_many(documents)

    if await db[PII_POLICIES_COLLECTION].count_documents({"tenant_id": ""}) == 0:
        documents = [
            {"tenant_id": "", "pii_type": pii_type, "strategy": strategy}
            for pii_type, strategy in DEFAULT_PII_POLICY.items()
        ]
        if documents:
            await db[PII_POLICIES_COLLECTION].insert_many(documents)
