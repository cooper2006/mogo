"""Tool risk-tier registration + autonomy-matrix lookup (T015 / T016).

Risk tiers (``risk_tiers`` collection) register each tool's R0-R4 level with an
optional tenant override; the autonomy matrix (``autonomy_matrix`` collection,
seeded from ``schema.AUTONOMY_MATRIX``) maps ``[L][R]`` to the gate decision
(allow / require_approval / deny).

The matrix is data, not code: admins maintain it through the CRUD endpoints in
``api/routes`` (T018), and the approval layer consults it (US2). The R4 red line
is enforced at two places so it can never be overridden:

* ``schema.AUTONOMY_MATRIX`` seeds R4 = deny for every autonomy level;
* :func:`matrix_decision` hard-fails any stored cell that claims R4 is not deny
  (fail-closed), even if a misconfigured document slipped into the collection.

Lookups degrade to safe defaults when the store is unavailable:

* unknown tool -> ``R0`` (read-only default; no approval burden on unknowns);
* missing matrix cell -> the canonical constant from ``schema``.
"""

from __future__ import annotations

from typing import Any, Optional

from .schema import AUTONOMY_MATRIX, AUTONOMY_MATRIX_COLLECTION, RISK_TIERS_COLLECTION

# Levels and risks recognized by the gate.
AUTONOMY_LEVELS: tuple[str, ...] = ("L1", "L2", "L3", "L4", "L5")
RISK_LEVELS: tuple[str, ...] = ("R0", "R1", "R2", "R3", "R4")

DECISIONS: tuple[str, ...] = ("allow", "require_approval", "deny")

# Unknown tools default to the least-burdenous tier (FR-2 / US2).
DEFAULT_RISK_LEVEL = "R0"


def _get_db() -> Any:
    from app.core.db import get_db

    return get_db()


async def register_risk_tier(
    *,
    tenant_id: str,
    tool: str,
    risk: str,
    note: str = "",
) -> dict[str, Any]:
    """Register (upsert) a tool's risk tier for a tenant.

    Tenant ``""`` is the global default; a specific tenant's document wins over
    the global one in :func:`risk_level_for`.
    """
    if risk not in RISK_LEVELS:
        raise ValueError(f"invalid risk level: {risk!r} (expected one of {RISK_LEVELS})")
    db = _get_db()
    document = {"tenant_id": tenant_id, "tool": tool, "risk": risk, "note": note}
    await db[RISK_TIERS_COLLECTION].update_one(
        {"tenant_id": tenant_id, "tool": tool},
        {"$set": document},
        upsert=True,
    )
    return document


async def list_risk_tiers(*, tenant_id: str = "", tool: Optional[str] = None) -> list[dict[str, Any]]:
    """List registered risk tiers, optionally filtered by tenant / tool."""
    db = _get_db()
    query: dict[str, Any] = {}
    if tenant_id:
        query["tenant_id"] = tenant_id
    if tool:
        query["tool"] = tool
    cursor = db[RISK_TIERS_COLLECTION].find(query).sort("tool", 1)
    return [doc async for doc in cursor]


async def risk_level_for(*, tenant_id: str, tool: str) -> str:
    """Resolve the effective risk level for ``(tenant, tool)``.

    A tenant-specific registration beats the global (``tenant_id=""``) one; when
    nothing is registered the tool defaults to :data:`DEFAULT_RISK_LEVEL`.
    Degrades safely to the default when the store is unreachable.
    """
    try:
        db = _get_db()
    except Exception:
        return DEFAULT_RISK_LEVEL
    # Tenant-specific registration first, then the global (tenant_id="") row.
    try:
        document = await db[RISK_TIERS_COLLECTION].find_one({"tenant_id": tenant_id, "tool": tool})
        if document is None:
            document = await db[RISK_TIERS_COLLECTION].find_one({"tenant_id": "", "tool": tool})
    except Exception:
        return DEFAULT_RISK_LEVEL
    if document is None:
        return DEFAULT_RISK_LEVEL
    risk = document.get("risk")
    return risk if risk in RISK_LEVELS else DEFAULT_RISK_LEVEL


async def matrix_decision(
    *,
    level: Optional[str] = None,
    risk: Optional[str] = None,
    db: Optional[Any] = None,
) -> str:
    """Return the gate decision for an ``(L, R)`` cell.

    Reads the stored cell when available; falls back to the canonical constant.
    Any stored cell that violates the R4 red line (R4 must be ``deny``) is
    rejected and replaced by the canonical value (fail-closed, constitution II).
    """
    canonical = _canon(level, risk)
    if risk == "R4":
        return "deny"
    store = db
    if store is None:
        try:
            store = _get_db()
        except Exception:
            return canonical
    try:
        document = await store[AUTONOMY_MATRIX_COLLECTION].find_one({"cell": f"{level}:{risk}"})
    except Exception:
        return canonical
    if document and document.get("decision") in DECISIONS:
        return document["decision"]
    return canonical


def _canon(level: Optional[str], risk: Optional[str]) -> str:
    """Canonical constant-table lookup with safe fallbacks."""
    levels = [level] if level else list(AUTONOMY_MATRIX)
    for lvl in levels:
        row = AUTONOMY_MATRIX.get(lvl)
        if row and risk in row:
            return row[risk]
    # Unknown cell -> the most permissive *read-only* default, never deny-by-default
    # for unknowns (mirrors the R0 default above).
    return "allow"


async def audit_matrix_change(*, actor: str, level: str, risk: str, decision: str, previous: str = "") -> None:
    """Record a matrix edit in the single audit sink (gate_events, FR-9 / T018)."""
    from .layers.audit import GATE_EVENTS_COLLECTION, _utcnow

    import uuid

    try:
        db = _get_db()
        await db[GATE_EVENTS_COLLECTION].insert_one(
            {
                "event_id": uuid.uuid4().hex,
                "occurred_at": _utcnow(),
                "tenant_id": "",
                "user_id": actor,
                "roles": [],
                "tool": f"gate.matrix.{level}:{risk}",
                "risk_level": risk,
                "autonomy_level": level,
                "decision": decision,
                "layer": "matrix_admin",
                "reason": f"matrix cell updated (previous={previous or 'n/a'})",
                "detail": {"cell": f"{level}:{risk}", "decision": decision, "previous": previous},
            }
        )
    except Exception:
        # Audit write failures must never break the admin endpoint; the change
        # itself already validated R4 invariants.
        pass
