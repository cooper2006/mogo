"""Capability asset registration + governance view (018 T006-T011 / US1/US2).

Registers capability assets (tools / models / skills / agents) with the
contract four-part + version + owner, deduplicates scanned endpoints, and
provides the governance view (list + detail drill-down), status management
(active / deprecated / offline + approval), and the ``a2a_exposed`` mark that
012 uses to generate AgentCards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

VALID_STATUSES = ("active", "deprecated", "offline")


@dataclass
class CapabilityAsset:
    key: str
    display_name: str
    asset_type: str
    owner: str
    version: str = "1"
    contract: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    a2a_exposed: bool = False
    dedupe_ref: str = ""  # endpoint + method for scan dedup (T007)

    def as_document(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "asset_type": self.asset_type,
            "owner": self.owner,
            "version": self.version,
            "contract": dict(self.contract),
            "status": self.status,
            "a2a_exposed": self.a2a_exposed,
            "dedupe_ref": self.dedupe_ref,
        }


class CapabilityAssetRegistry:
    """In-memory / Mongo-backed capability asset registry (018)."""

    def __init__(self, db: Optional[Any] = None) -> None:
        self._db = db
        self._assets: dict[str, CapabilityAsset] = {}
        self._dedupe: dict[str, str] = {}

    def register(
        self,
        *,
        key: str,
        display_name: str = "",
        asset_type: str = "tool",
        owner: str = "",
        version: str = "1",
        contract: dict[str, Any] | None = None,
        dedupe_ref: str = "",
    ) -> CapabilityAsset:
        asset = CapabilityAsset(
            key=key,
            display_name=display_name or key,
            asset_type=asset_type,
            owner=owner,
            version=version,
            contract=dict(contract or {}),
            dedupe_ref=dedupe_ref,
        )
        if self._db is not None:
            self._db["capability_assets"].replace_one({"key": key}, asset.as_document(), upsert=True)
        else:
            self._assets[key] = asset
        if dedupe_ref:
            self._dedupe[dedupe_ref] = key
        return asset

    # --- T007 scan dedup (endpoint + method) --------------------------------

    def dedupe(self, dedupe_ref: str, asset_key: str) -> bool:
        """Returns True when the ref is new (register); False when it was a dupe."""
        if dedupe_ref in self._dedupe:
            return False
        self._dedupe[dedupe_ref] = asset_key
        return True

    # --- T009 governance view (list + detail drill-down) -------------------

    def governance_view(self, *, asset_type: str = "") -> list[dict[str, Any]]:
        assets = self._assets.values()
        if asset_type:
            assets = [a for a in assets if a.asset_type == asset_type]
        return [a.as_document() for a in assets]

    def governance_detail(self, key: str) -> Optional[dict[str, Any]]:
        asset = self._assets.get(key)
        if asset is None:
            return None
        document = asset.as_document()
        document["detail"] = {
            "contract": dict(asset.contract),
            "status_history": [],
        }
        return document

    # --- T010 status management (active/deprecated/offline + 审批) ---------

    def get_status(self, key: str) -> str:
        return self._assets[key].status

    def set_status(
        self,
        key: str,
        status: str,
        *,
        approver: str = "",
        require_approval: bool = False,
        reason: str = "",
    ) -> CapabilityAsset:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        if require_approval and not approver:
            raise PermissionError("status change to offline/deprecated requires an approver")
        asset = self._assets[key]
        asset.status = status
        if self._db is not None:
            self._db["capability_assets"].update_one({"key": key}, {"$set": {"status": status}})
        return asset

    # --- T011 a2a_exposed marking (for 012 AgentCard generation) ----------

    def mark_a2a_exposed(self, key: str, exposed: bool) -> CapabilityAsset:
        asset = self._assets[key]
        asset.a2a_exposed = exposed
        if self._db is not None:
            self._db["capability_assets"].update_one({"key": key}, {"$set": {"a2a_exposed": exposed}})
        return asset

    def is_a2a_exposed(self, key: str) -> bool:
        asset = self._assets.get(key)
        return bool(asset.a2a_exposed) if asset else False

    # --- US1 tests: discover + register + dedup ---------------------------

    def discover_and_register(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        registered: list[str] = []
        duplicates: list[str] = []
        for entry in entries:
            dedupe_ref = entry.get("dedupe_ref") or f"{entry.get('endpoint')}+{entry.get('method')}"
            if self.dedupe(dedupe_ref, entry.get("key", "")):
                self.register(
                    key=entry.get("key", ""),
                    display_name=entry.get("display_name", ""),
                    asset_type=entry.get("asset_type", "tool"),
                    owner=entry.get("owner", ""),
                    contract=entry.get("contract") or {},
                    dedupe_ref=dedupe_ref,
                )
                registered.append(entry.get("key", ""))
            else:
                duplicates.append(entry.get("key", ""))
        return {"registered": registered, "duplicates": duplicates}


__all__ = [
    "VALID_STATUSES",
    "CapabilityAsset",
    "CapabilityAssetRegistry",
]
