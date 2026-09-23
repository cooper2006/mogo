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
from typing import Any, Iterable

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
