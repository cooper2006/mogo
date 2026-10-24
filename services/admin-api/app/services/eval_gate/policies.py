"""032-eval-gate: tenant threshold policy (fail-closed default).

The gate is **never** globally switchable (FR-006).  ``policy_defaults()`` always
returns thresholds that enforce a hard gate; the tenant may only tune how tight
or loose those thresholds are (spec 已定决策 #2 / #3).
"""

from __future__ import annotations

import datetime
from typing import Any

from app.core.db import get_db

from .models import POLICIES_COLLECTION, policy_defaults


def now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


async def get_policy(*, tenant_id: str, skill_id: str | None = None) -> dict[str, Any]:
    """Return the effective policy for a tenant / optional skill override.

    Resolution order: skill-level override → tenant-level → built-in defaults.
    The returned dict always carries the full threshold set.
    """
    db = get_db()
    if skill_id:
        skill_row = await db[POLICIES_COLLECTION].find_one({"tenant_id": tenant_id, "skill_id": skill_id})
        if skill_row is not None:
            return _normalise(skill_row)
    tenant_row = await db[POLICIES_COLLECTION].find_one({"tenant_id": tenant_id, "skill_id": None})
    if tenant_row is not None:
        return _normalise(tenant_row)
    return policy_defaults()


async def get_policy_doc(*, tenant_id: str, skill_id: str | None = None) -> dict[str, Any]:
    """Return the raw stored document, or ``None`` when absent."""
    query: dict[str, Any] = {"tenant_id": tenant_id}
    if skill_id:
        query["skill_id"] = skill_id
    else:
        query["skill_id"] = None
    return await get_db()[POLICIES_COLLECTION].find_one(query)


async def save_policy(*, tenant_id: str, skill_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    """Upsert a policy.  ``enabled`` is never accepted — the gate is always on."""
    doc = policy_defaults()
    for key in ("min_citation_support", "min_refusal_accuracy", "min_task_success",
                "min_cases", "max_cases", "timeout_seconds"):
        if key in payload and payload[key] is not None:
            doc[key] = _coerce(key, payload[key])
    doc["tenant_id"] = tenant_id
    doc["skill_id"] = skill_id
    doc["updated_at"] = now()
    db = get_db()
    await db[POLICIES_COLLECTION].update_one(
        {"tenant_id": tenant_id, "skill_id": skill_id},
        {"$set": doc},
        upsert=True,
    )
    return _normalise(doc)


def _coerce(key: str, value: Any) -> Any:
    if key in ("min_cases", "max_cases", "timeout_seconds"):
        number = int(value)
        if key == "min_cases" and number < 1:
            raise ValueError("min_cases 至少为 1")
        if key == "max_cases" and number < 1:
            raise ValueError("max_cases 至少为 1")
        if key == "timeout_seconds" and number < 1:
            raise ValueError("timeout_seconds 至少为 1")
        return number
    # thresholds are fractions in [0, 1]
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{key} 应在 [0, 1] 之间")
    return round(number, 4)


def _normalise(row: dict[str, Any]) -> dict[str, Any]:
    merged = policy_defaults()
    for key in ("min_citation_support", "min_refusal_accuracy", "min_task_success",
                "min_cases", "max_cases", "timeout_seconds"):
        if key in row and row[key] is not None:
            merged[key] = row[key]
    return merged


def view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "tenantId": str(row.get("tenant_id") or ""),
        "skillId": str(row.get("skill_id") or "") or None,
        "minCitationSupport": float(row.get("min_citation_support") or 0),
        "minRefusalAccuracy": float(row.get("min_refusal_accuracy") or 0),
        "minTaskSuccess": float(row.get("min_task_success") or 0),
        "minCases": int(row.get("min_cases") or 0),
        "maxCases": int(row.get("max_cases") or 0),
        "timeoutSeconds": int(row.get("timeout_seconds") or 0),
        "enabled": True,
    }