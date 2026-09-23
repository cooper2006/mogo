"""Capability asset registration (feature 018).

Discovers existing business capabilities, registers them as standardized,
versioned, auditable **assets** (contract + version + owner), and exposes a
governance view over the whole inventory.

This package holds the dependency-light core (contract schema / asset model /
discovery), so it is unit-testable without a database.
"""

from __future__ import annotations

from .contract import (
    CONTRACT_SECTIONS,
    AssetContract,
    ContractError,
    normalize_contract,
)
from .registry import (
    ASSET_STATES,
    AssetError,
    CapabilityAsset,
    DiscoveryReport,
    dedupe_key,
    discover_assets,
)

__all__ = [
    "AssetContract",
    "CONTRACT_SECTIONS",
    "ContractError",
    "normalize_contract",
    "CapabilityAsset",
    "ASSET_STATES",
    "AssetError",
    "DiscoveryReport",
    "discover_assets",
    "dedupe_key",
]
