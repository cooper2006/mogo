"""Skill tenant adapter (021 / 004 / 018).

Resolves a ``mogo://skill/<subtype>/...`` address:

* ``skill``  → 004 ``user_skills`` (draft/published) or ``skill_releases`` (by version)
* ``asset``  → 018 ``capability_assets`` via ``CapabilityAssetRegistry``

Tiers reuse existing structured metadata, not an LLM (OQ-11):
L0 = one-line capability description, L1 = contract summary (in/out/when),
L2 = the full skill markdown / contract.
"""

from __future__ import annotations

from typing import Any, Optional

from app.context_space.adapters.base import ResolvedTier, TierAdapter
from app.context_space.address import ASSET, SKILL, SkillAddress
from app.context_space.visibility import (
    ContextNotFoundError,
    ContextVisibilityError,
    ViewerContext,
    check_visibility,
)
from app.core.db import get_db
from app.core.tenant import add_main_scope, resolve_main_id


class SkillTierAdapter(TierAdapter):
    """Resolves skill / capability-asset addresses."""

    root = "skill"

    async def resolve(
        self,
        *,
        uri: str,
        tier: Optional[str],
        tenant_id: str,
        viewer: ViewerContext,
    ) -> ResolvedTier:
        addr = _parse(uri)
        if tier:
            addr = SkillAddress(addr.subtype, addr.identifiers, tier)
        if not check_visibility(addr=addr, ctx=viewer):
            raise ContextVisibilityError(f"viewer may not resolve {uri}")

        if addr.subtype == SKILL:
            content, meta = await _load_skill(addr, tenant_id)
        else:  # ASSET
            content, meta = await _load_asset(addr, tenant_id)

        if content is None:
            raise ContextNotFoundError(f"skill not found: {uri}")

        return ResolvedTier(
            uri=addr.uri(),
            tier_used=addr.tier,
            content=content,
            meta=meta or {},
        )


def _parse(uri: str) -> SkillAddress:
    from app.context_space.address import parse_context_uri

    addr = parse_context_uri(uri)
    if not isinstance(addr, SkillAddress):
        raise ContextNotFoundError(f"not a skill uri: {uri}")
    return addr


async def _load_skill(addr: SkillAddress, tenant_id: str) -> tuple[Optional[str], dict]:
    org_id, skill_id = addr.identifiers[0], addr.identifiers[1]
    version = addr.identifiers[2] if len(addr.identifiers) > 2 else ""
    db = get_db()
    if db is None:
        return None, {}
    row: Optional[dict[str, Any]] = None
    if version:
        release = await db["skill_releases"].find_one(
            add_main_scope({"skill_id": skill_id, "version": version}, resolve_main_id(org_id))
        )
        row = release.get("snapshot") if release else None
    if row is None:
        row = await db["user_skills"].find_one(
            add_main_scope({"_id": skill_id}, resolve_main_id(org_id))
        )
    if row is None:
        # C3 (2026-10-06 R2 遗留建议): the previous fallback queried
        # ``user_skills`` by ``_id`` alone, with no tenant/org scope — a
        # tenant-agnostic read that could return another org's skill. The
        # visibility guard above already verified ``identifiers[0] == tenant``,
        # so a scoping failure here is a genuine not-found, not a visibility
        # edge case. Return 404 instead of widening the query.
        return None, {}

    summary = str(row.get("summary") or row.get("description") or "")
    name = str(row.get("name") or skill_id)
    contract = row.get("contract_json") or {}
    inputs = contract.get("input_profile") or contract.get("inputs") or {}
    outputs = contract.get("output_profile") or contract.get("outputs") or {}
    when = contract.get("applicable_scenarios") or contract.get("when_to_use") or ""
    l0 = (name + (" — " + summary if summary else "")).strip() or name
    l1 = (
        f"when: {when}\n"
        f"in: {_short(inputs)}\n"
        f"out: {_short(outputs)}"
    ).strip()
    l2 = str(row.get("skill_markdown") or l1)
    content = {"L0": l0, "L1": l1, "L2": l2}.get(addr.tier, l2)
    return content, {
        "subtype": "skill",
        "skill_id": skill_id,
        "name": name,
        "version": version or str(row.get("published_version") or ""),
        "category": row.get("category"),
        "a2a_exposed": bool(row.get("a2a_exposed") or False),
    }


async def _load_asset(addr: SkillAddress, tenant_id: str) -> tuple[Optional[str], dict]:
    asset_key = addr.identifiers[0]
    db = get_db()
    if db is None:
        return None, {}
    from app.services.capability_assets import CapabilityAssetRegistry

    registry = CapabilityAssetRegistry(db)
    detail = await registry.governance_detail(asset_key)
    if detail is None:
        return None, {}
    contract = (detail.get("detail") or {}).get("contract") or {}
    display = str(detail.get("display_name") or asset_key)
    l0 = display
    l1 = _short(contract) or display
    l2 = str(contract or display)
    content = {"L0": l0, "L1": l1, "L2": l2}.get(addr.tier, l2)
    return content, {
        "subtype": "asset",
        "asset_key": asset_key,
        "asset_type": detail.get("asset_type"),
        "owner": detail.get("owner"),
        "status": detail.get("status"),
        "a2a_exposed": bool(detail.get("a2a_exposed") or False),
    }


def _short(value: Any, limit: int = 240) -> str:
    text = str(value)
    return text[:limit]


__all__ = ["SkillTierAdapter"]
