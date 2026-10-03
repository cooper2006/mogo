"""Tests for capability asset registration (feature 018): contract / registry."""

from __future__ import annotations

import pytest

from app.services.capability_assets.contract import (
    CONTRACT_SECTIONS,
    AssetContract,
    ContractError,
    contract_diff,
    normalize_contract,
)
from app.services.capability_assets.registry import (
    ASSET_STATES,
    AssetError,
    CapabilityAsset,
    dedupe_key,
    discover_assets,
)


# --- contract ----------------------------------------------------------------

def test_contract_has_four_sections() -> None:
    assert CONTRACT_SECTIONS == ("input", "output", "errors", "sla")


def test_normalize_contract_fills_missing_sections() -> None:
    contract = normalize_contract({"input": {"q": "str"}})
    assert contract.input == {"q": "str"}
    assert contract.output == {}
    assert contract.is_complete() is True


def test_normalize_none_is_empty_contract() -> None:
    assert normalize_contract(None).as_dict() == {"input": {}, "output": {}, "errors": {}, "sla": {}}


def test_normalize_rejects_non_object() -> None:
    with pytest.raises(ContractError):
        normalize_contract("not-an-object")


def test_normalize_rejects_non_object_section() -> None:
    with pytest.raises(ContractError):
        normalize_contract({"input": "nope"})


def test_contract_diff_detects_changes() -> None:
    old = normalize_contract({"input": {"q": "str"}})
    new = normalize_contract({"input": {"q": "int"}})
    diff = contract_diff(old, new)
    assert "input" in diff
    assert diff["input"]["before"] == {"q": "str"}


def test_contract_diff_empty_when_identical() -> None:
    contract = normalize_contract({"input": {"q": "str"}})
    assert contract_diff(contract, contract) == {}


# --- registry ----------------------------------------------------------------

def test_asset_states_are_three() -> None:
    assert ASSET_STATES == ("active", "deprecated", "offline")


def test_asset_requires_id_and_known_state() -> None:
    with pytest.raises(AssetError):
        CapabilityAsset(asset_id="")
    with pytest.raises(AssetError):
        CapabilityAsset(asset_id="a", state="ghost")


def test_dedupe_key_normalizes_method_and_endpoint() -> None:
    assert dedupe_key(endpoint="/CRM/Customers", method="post") == "POST:/crm/customers"


def test_update_contract_bumps_version_and_archives() -> None:
    asset = CapabilityAsset(asset_id="a", contract=normalize_contract({"input": {"q": "str"}}))
    diff = asset.update_contract({"input": {"q": "int"}})
    assert asset.version == 2
    assert len(asset.versions) == 1  # old version kept for viewing (FR-5)
    assert diff


def test_update_contract_without_change_does_not_bump() -> None:
    asset = CapabilityAsset(asset_id="a", contract=normalize_contract({"input": {"q": "str"}}))
    assert asset.update_contract({"input": {"q": "str"}}) == {}
    assert asset.version == 1


def test_offline_requires_authorized_role() -> None:
    asset = CapabilityAsset(asset_id="a")
    with pytest.raises(AssetError):
        asset.set_state("offline", role="member")
    asset.set_state("offline", role="full_access_admin")
    assert asset.state == "offline"


def test_deprecate_needs_no_approval() -> None:
    asset = CapabilityAsset(asset_id="a")
    asset.set_state("deprecated")
    assert asset.state == "deprecated"


def test_transfer_owner_requires_non_empty() -> None:
    asset = CapabilityAsset(asset_id="a")
    with pytest.raises(AssetError):
        asset.transfer_owner("")
    asset.transfer_owner("ops_admin")
    assert asset.owner_role == "ops_admin"


def test_a2a_exposed_defaults_false() -> None:
    assert CapabilityAsset(asset_id="a").a2a_exposed is False


# --- discovery ---------------------------------------------------------------

def test_discover_auto_extracts_rest_and_mcp() -> None:
    report = discover_assets(
        [
            {"kind": "rest", "endpoint": "/api/x", "method": "GET", "name": "X"},
            {"kind": "mcp", "endpoint": "mcp://tool", "method": "CALL", "name": "T"},
        ]
    )
    assert len(report.discovered) == 2
    assert report.needs_manual == []


def test_discover_marks_non_standard_for_manual() -> None:
    report = discover_assets([{"kind": "soap", "endpoint": "/ws", "name": "Legacy"}])
    assert report.discovered == []
    assert report.needs_manual[0]["marker"] == "manual_required"


def test_discover_dedupes_same_endpoint_and_method() -> None:
    report = discover_assets(
        [
            {"kind": "rest", "endpoint": "/api/x", "method": "GET", "name": "X"},
            {"kind": "rest", "endpoint": "/api/x", "method": "GET", "name": "X again"},
        ]
    )
    assert len(report.discovered) == 1


def test_discover_keeps_same_endpoint_different_method() -> None:
    report = discover_assets(
        [
            {"kind": "rest", "endpoint": "/api/x", "method": "GET"},
            {"kind": "rest", "endpoint": "/api/x", "method": "POST"},
        ]
    )
    assert len(report.discovered) == 2


def test_persisted_registry_roundtrip_serialization():
    """FR-10: _asset_to_row / _row_to_asset preserve all CapabilityAsset fields."""
    from app.services.capability_assets.registry import (
        _asset_to_row,
        _row_to_asset,
        CapabilityAsset,
    )
    from app.services.capability_assets.contract import normalize_contract

    asset = CapabilityAsset(
        asset_id="rest_/api/x_POST",
        name="X",
        contract=normalize_contract({"input": {"q": "str"}}),
        version=2,
        owner_role="full_access_admin",
        state="active",
        endpoint="/api/x",
        method="POST",
        kind="rest",
        a2a_exposed=True,
        versions=[{"version": 1, "contract": {}}],
    )
    row = _asset_to_row(asset)
    # Round-trip: the row must reconstruct the same asset fields.
    restored = _row_to_asset(row)
    assert restored.asset_id == asset.asset_id
    assert restored.name == asset.name
    assert restored.version == 2
    assert restored.owner_role == "full_access_admin"
    assert restored.state == "active"
    assert restored.endpoint == "/api/x"
    assert restored.method == "POST"
    assert restored.kind == "rest"
    assert restored.a2a_exposed is True
    assert restored.contract.input == {"q": "str"}
    assert restored.versions == [{"version": 1, "contract": {}}]


# --- FR-11 / FR-12: owner transfer audit + a2a_exposed mark ----------------


def test_persisted_transfer_owner_writes_audit(monkeypatch) -> None:
    """FR-11: transfer_owner appends a change record to the audit stream."""
    import asyncio
    from app.services.capability_assets.registry import (
        CapabilityAsset,
        PersistedCapabilityRegistry,
    )

    inserted: list[dict] = []

    class _AuditCol:
        async def insert_one(self, doc):
            inserted.append(doc)

    class _AssetsCol:
        async def replace_one(self, flt, row, upsert=False):
            pass

        async def find_one(self, flt):
            return {"asset_id": "a", "owner_role": "old_role", "state": "active"}

    class _DB:
        def __getitem__(self, name):
            if name == "position_role_audit_logs":
                return _AuditCol()
            return _AssetsCol()

    import app.core.db as core_db
    monkeypatch.setattr(core_db, "get_db", lambda: _DB())

    registry = PersistedCapabilityRegistry()
    asyncio.run(registry.transfer_owner("a", "new_role"))
    assert inserted, "transfer_owner must leave an audit record"
    assert inserted[0]["action"] == "capability.transfer_owner"
    assert inserted[0]["target_id"] == "a"
    assert inserted[0]["details"]["before"] == "old_role"
    assert inserted[0]["details"]["after"] == "new_role"


def test_persisted_set_a2a_exposed_persists_flag(monkeypatch) -> None:
    """FR-12: set_a2a_exposed persists the flag for 012 AgentCard gating."""
    import asyncio
    from app.services.capability_assets.registry import PersistedCapabilityRegistry

    rows = {
        "a": {"asset_id": "a", "owner_role": "old", "state": "active",
              "a2a_exposed": False}
    }

    class _AssetsCol:
        async def replace_one(self, flt, row, upsert=False):
            rows[flt["asset_id"]] = row

        async def find_one(self, flt):
            return rows.get(flt["asset_id"])

    class _AuditCol:
        async def insert_one(self, doc):
            pass

    class _DB:
        def __getitem__(self, name):
            if name == "position_role_audit_logs":
                return _AuditCol()
            return _AssetsCol()

    import app.core.db as core_db
    monkeypatch.setattr(core_db, "get_db", lambda: _DB())

    registry = PersistedCapabilityRegistry()
    asset = asyncio.run(registry.set_a2a_exposed("a", True))
    assert asset.a2a_exposed is True
    assert rows["a"]["a2a_exposed"] is True
