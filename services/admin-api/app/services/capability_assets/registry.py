"""Capability asset registry (018 FR-1 / FR-2 / FR-5 / FR-6 / FR-10 / FR-11).

* **discovery** scans standard REST / MCP capabilities automatically and flags the
  rest as needing manual completion (clarify OQ-2);
* assets are deduplicated by ``endpoint + method`` (FR-10);
* contract changes bump the version, keeping the old version viewable (FR-5);
* state is one of active / deprecated / offline, with **offline requiring an
  authorized approver** (FR-6);
* the owner is a position role and may be transferred, audited (FR-11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .contract import AssetContract, contract_diff, normalize_contract

# Asset lifecycle states (FR-6).
ASSET_STATES: tuple[str, ...] = ("active", "deprecated", "offline")

# Role allowed to approve taking an asset offline (clarify OQ-4).
OFFLINE_APPROVER_ROLES = frozenset({"full_access_admin"})

# Standards we can auto-discover a contract from (clarify OQ-2).
AUTO_DISCOVERABLE_KINDS = frozenset({"rest", "mcp"})


class AssetError(ValueError):
    """Raised for an invalid asset operation."""


def dedupe_key(*, endpoint: str, method: str) -> str:
    """The discovery dedupe key: endpoint + method (FR-10)."""
    return f"{str(method).upper()}:{str(endpoint).strip().lower()}"


@dataclass
class CapabilityAsset:
    """A registered capability asset."""

    asset_id: str
    name: str = ""
    contract: AssetContract = field(default_factory=AssetContract)
    version: int = 1
    owner_role: str = ""
    state: str = "active"
    endpoint: str = ""
    method: str = ""
    kind: str = "rest"
    a2a_exposed: bool = False            # gates 012 AgentCard generation (FR-12)
    versions: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not str(self.asset_id or "").strip():
            raise AssetError("asset_id must not be empty")
        if self.state not in ASSET_STATES:
            raise AssetError(f"unknown asset state: {self.state!r}")

    def dedupe_key(self) -> str:
        return dedupe_key(endpoint=self.endpoint, method=self.method)

    def update_contract(self, document: Any) -> dict[str, Any]:
        """Replace the contract, bump the version, and archive the old version (FR-5).

        Returns the change diff (for the audit record).
        """
        new_contract = normalize_contract(document)
        diff = contract_diff(self.contract, new_contract)
        if not diff:
            return {}
        self.versions.append({"version": self.version, "contract": self.contract.as_dict()})
        self.contract = new_contract
        self.version += 1
        return diff

    def set_state(self, state: str, *, role: str = "") -> None:
        """Change state; taking an asset offline requires an authorized approver (FR-6)."""
        if state not in ASSET_STATES:
            raise AssetError(f"unknown asset state: {state!r}")
        if state == "offline" and role not in OFFLINE_APPROVER_ROLES:
            raise AssetError(f"role {role!r} may not take an asset offline")
        self.state = state

    def transfer_owner(self, role: str) -> None:
        """Transfer ownership to another position role (FR-11)."""
        if not str(role or "").strip():
            raise AssetError("owner role must not be empty")
        self.owner_role = role

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "name": self.name,
            "endpoint": self.endpoint,
            "method": self.method,
            "kind": self.kind,
            "version": self.version,
            "state": self.state,
            "owner_role": self.owner_role,
            "a2a_exposed": self.a2a_exposed,
            "contract": self.contract.as_dict(),
        }


@dataclass
class DiscoveryReport:
    """Outcome of a discovery scan."""

    discovered: list[CapabilityAsset] = field(default_factory=list)
    needs_manual: list[dict[str, Any]] = field(default_factory=list)

    @property
    def discovered_keys(self) -> set[str]:
        return {asset.dedupe_key() for asset in self.discovered}


def discover_assets(candidates: Iterable[dict[str, Any]]) -> DiscoveryReport:
    """Scan capability candidates.

    Standard REST / MCP endpoints yield a discovered asset with an auto-extracted
    contract; anything else is listed under ``needs_manual`` with a marker (FR-2).
    Duplicates (same endpoint + method) are collapsed (FR-10).
    """
    report = DiscoveryReport()
    seen: set[str] = set()
    for candidate in candidates:
        kind = str(candidate.get("kind") or "").strip().lower()
        endpoint = str(candidate.get("endpoint") or "")
        method = str(candidate.get("method") or "POST")
        name = str(candidate.get("name") or endpoint or "capability")

        if kind not in AUTO_DISCOVERABLE_KINDS:
            report.needs_manual.append(
                {"name": name, "endpoint": endpoint, "marker": "manual_required"}
            )
            continue

        key = dedupe_key(endpoint=endpoint, method=method)
        if key in seen:
            continue
        seen.add(key)
        report.discovered.append(
            CapabilityAsset(
                asset_id=key,
                name=name,
                contract=normalize_contract(candidate.get("contract")),
                endpoint=endpoint,
                method=method,
                kind=kind,
            )
        )
    return report


class CapabilityAssetRegistry:
    """In-memory registry of capability assets (018 FR-1 / FR-2 / FR-5 / FR-6 / FR-10).

    Used by unit tests and by the ``PersistedCapabilityRegistry`` (FR-10).
    """

    def __init__(self) -> None:
        self._assets: dict[str, CapabilityAsset] = {}

    def register(self, asset: CapabilityAsset) -> None:
        """Register or upsert an asset (FR-1)."""
        self._assets[asset.asset_id] = asset

    def get(self, asset_id: str) -> Optional[CapabilityAsset]:
        return self._assets.get(asset_id)

    def list_all(self, *, state: Optional[str] = None) -> list[CapabilityAsset]:
        if state is None:
            return list(self._assets.values())
        return [a for a in self._assets.values() if a.state == state]

    def discover_and_register(self, candidates: Iterable[dict[str, Any]]) -> DiscoveryReport:
        """Discover candidates and register them in one step (FR-2 / FR-10)."""
        report = discover_assets(candidates)
        for asset in report.discovered:
            self.register(asset)
        return report

    def update_contract(self, asset_id: str, document: Any, *, role: str = "") -> dict[str, Any]:
        """Update contract and bump version (FR-5)."""
        asset = self._assets.get(asset_id)
        if asset is None:
            raise AssetError(f"asset not found: {asset_id}")
        return asset.update_contract(document)

    def set_state(self, asset_id: str, state: str, *, role: str = "") -> None:
        """Change state; offline requires authorized approver (FR-6)."""
        asset = self._assets.get(asset_id)
        if asset is None:
            raise AssetError(f"asset not found: {asset_id}")
        asset.set_state(state, role=role)

    def transfer_owner(self, asset_id: str, role: str) -> None:
        """Transfer ownership (FR-11)."""
        asset = self._assets.get(asset_id)
        if asset is None:
            raise AssetError(f"asset not found: {asset_id}")
        asset.transfer_owner(role)

    def __len__(self) -> int:
        return len(self._assets)


# ---------------------------------------------------------------------------
# MongoDB-backed persistence (FR-10)
# ---------------------------------------------------------------------------

COLLECTION = "capability_assets"


def _asset_to_row(asset: CapabilityAsset) -> dict[str, Any]:
    return {
        "asset_id": asset.asset_id,
        # Cross-service read aliases: chat-api (012 AgentCard generation, FR-12)
        # reads this collection with `key` / `display_name` / `status`; writing
        # both spellings keeps the shared collection readable from either side
        # (018 FR-12 wiring).
        "key": asset.asset_id,
        "name": asset.name,
        "display_name": asset.name,
        "endpoint": asset.endpoint,
        "method": asset.method,
        "kind": asset.kind,
        "version": str(asset.version),
        "state": asset.state,
        "status": asset.state,
        "owner_role": asset.owner_role,
        "owner": asset.owner_role,
        "a2a_exposed": bool(asset.a2a_exposed),
        "contract": asset.contract.as_dict(),
        "versions": list(asset.versions),
        "updated_at": datetime.now(timezone.utc),
    }


def _row_to_asset(row: dict[str, Any]) -> CapabilityAsset:
    return CapabilityAsset(
        asset_id=str(row.get("asset_id") or ""),
        name=str(row.get("name") or ""),
        contract=normalize_contract(row.get("contract")),
        version=int(row.get("version") or 1),
        owner_role=str(row.get("owner_role") or ""),
        state=str(row.get("state") or "active"),
        endpoint=str(row.get("endpoint") or ""),
        method=str(row.get("method") or ""),
        kind=str(row.get("kind") or "rest"),
        a2a_exposed=bool(row.get("a2a_exposed") or False),
        versions=list(row.get("versions") or []),
    )


class PersistedCapabilityRegistry:
    """MongoDB-backed registry for capability assets (018 FR-10).

    Assets survive process restarts and are shareable across replicas.
    Mirrors the synchronous ``CapabilityAssetRegistry`` API with async
    methods that read/write the ``capability_assets`` collection.
    """

    async def register(self, asset: CapabilityAsset) -> None:
        from app.core.db import get_db

        db = get_db()
        row = _asset_to_row(asset)
        await db[COLLECTION].replace_one({"asset_id": asset.asset_id}, row, upsert=True)

    async def get(self, asset_id: str) -> Optional[CapabilityAsset]:
        from app.core.db import get_db

        db = get_db()
        row = await db[COLLECTION].find_one({"asset_id": asset_id})
        return _row_to_asset(row) if row else None

    async def list_all(self, *, state: Optional[str] = None) -> list[CapabilityAsset]:
        from app.core.db import get_db

        db = get_db()
        query: dict[str, Any] = {}
        if state is not None:
            query["state"] = state
        rows = await db[COLLECTION].find(query).to_list(length=500)
        return [_row_to_asset(r) for r in rows]

    async def discover_and_register(self, candidates: Iterable[dict[str, Any]]) -> DiscoveryReport:
        """Discover candidates and persist them in one step (FR-2 / FR-10)."""
        report = discover_assets(candidates)
        for asset in report.discovered:
            await self.register(asset)
        return report

    async def update_contract(self, asset_id: str, document: Any, *, role: str = "") -> dict[str, Any]:
        asset = await self.get(asset_id)
        if asset is None:
            raise AssetError(f"asset not found: {asset_id}")
        diff = asset.update_contract(document)
        await self.register(asset)
        return diff

    async def set_state(self, asset_id: str, state: str, *, role: str = "") -> None:
        asset = await self.get(asset_id)
        if asset is None:
            raise AssetError(f"asset not found: {asset_id}")
        asset.set_state(state, role=role)
        await self.register(asset)

    async def transfer_owner(self, asset_id: str, role: str) -> None:
        asset = await self.get(asset_id)
        if asset is None:
            raise AssetError(f"asset not found: {asset_id}")
        previous_owner = asset.owner_role
        asset.transfer_owner(role)
        await self.register(asset)
        # 018 FR-11: owner transfer (责任人调岗) is always audited.
        await self.audit(asset_id, "transfer_owner", {
            "before": previous_owner,
            "after": role,
        })

    async def set_a2a_exposed(self, asset_id: str, exposed: bool) -> CapabilityAsset:
        """Explicitly mark/unmark A2A exposure (018 FR-12 / 012 FR-11)."""
        asset = await self.get(asset_id)
        if asset is None:
            raise AssetError(f"asset not found: {asset_id}")
        asset.a2a_exposed = bool(exposed)
        await self.register(asset)
        await self.audit(asset_id, "set_a2a_exposed", {"a2a_exposed": bool(exposed)})
        return asset

    async def audit(self, asset_id: str, action: str, details: dict[str, Any]) -> None:
        """Append a change record to the governance audit stream (018 FR-11).

        Audit failure never breaks the main flow — it is logged honestly.
        """
        from app.core.db import get_db
        from app.position_roles.constants import AUDIT_COLLECTION
        import uuid
        try:
            db = get_db()
            await db[AUDIT_COLLECTION].insert_one({
                "_id": uuid.uuid4().hex,
                "tenant_id": "default",
                "actor": "service",
                "action": f"capability.{action}",
                "target_type": "capability_asset",
                "target_id": asset_id,
                "details": dict(details),
                "created_at": datetime.now(timezone.utc),
            })
        except Exception as exc:  # pragma: no cover - defensive
            import logging
            logging.getLogger(__name__).warning(
                "capability audit write failed asset_id=%s action=%s: %s",
                asset_id, action, exc,
            )

    async def __len__(self) -> int:
        return len(await self.list_all())


__all__ = [
    "ASSET_STATES",
    "COLLECTION",
    "OFFLINE_APPROVER_ROLES",
    "AUTO_DISCOVERABLE_KINDS",
    "AssetError",
    "CapabilityAsset",
    "CapabilityAssetRegistry",
    "DiscoveryReport",
    "PersistedCapabilityRegistry",
    "dedupe_key",
    "discover_assets",
]
