"""Feature 001 — autonomy matrix + risk tier unit tests (US2 / T017).

Acceptance (spec):
* L3 x R2 -> require_approval
* L5 x R4 -> deny (the R4 red line cannot be overridden by any admin)
* R0 at any L -> allow
"""

from __future__ import annotations

import pytest

from app.governance import risk
from app.governance.schema import AUTONOMY_MATRIX


class _FakeStore:
    """Matrix-aware fake DB: returns stored cells when present, else None."""

    def __init__(self, cells: dict | None = None) -> None:
        self._cells = cells or {}
        self.collections = {
            "autonomy_matrix": _FakeCollection(self._cells),
            "risk_tiers": _FakeCollection({}),
            "gate_events": _FakeCollection({}),
        }

    def __getitem__(self, name):
        return self.collections[name]


class _FakeCollection:
    def __init__(self, cells: dict) -> None:
        self._cells = cells

    async def find_one(self, query: dict):
        cell = query.get("cell")
        if cell in self._cells:
            return {"cell": cell, "decision": self._cells[cell]}
        # risk_tiers / pii_policies style: (tenant_id, tool) lookup
        tenant_id = query.get("tenant_id")
        tool = query.get("tool")
        if tenant_id is not None and tool is not None:
            key = f"{tenant_id}:{tool}"
            if key in self._cells:
                return {"tenant_id": tenant_id, "tool": tool, "risk": self._cells[key]}
        return None

    async def find(self, *args, **kwargs):  # pragma: no cover - unused here
        raise NotImplementedError

    async def insert_one(self, doc):
        key = f"{doc.get('tenant_id', '')}:{doc.get('tool', doc.get('cell', ''))}"
        self._cells[key] = doc.get("risk") or doc.get("decision")

    async def update_one(self, filter_doc, update, upsert=False):
        cell = filter_doc.get("cell")
        if cell is not None and "$set" in update:
            self._cells[cell] = update["$set"].get("decision")
            return {"modified_count": 1}
        # risk_tiers upsert: (tenant_id, tool) -> risk
        if upsert and filter_doc.get("tool") is not None:
            key = f"{filter_doc.get('tenant_id', '')}:{filter_doc['tool']}"
            if "$set" in update:
                self._cells[key] = update["$set"].get("risk")
            return {"modified_count": 1}
        return {"modified_count": 0}

    async def count_documents(self, query=None):
        return len(self._cells)


# --- T017 matrix acceptance ---------------------------------------------------


@pytest.mark.asyncio
async def test_matrix_acceptance_l3_r2_requires_approval():
    assert await risk.matrix_decision(level="L3", risk="R2", db=_FakeStore()) == "require_approval"


@pytest.mark.asyncio
async def test_matrix_acceptance_l5_r4_denies():
    assert await risk.matrix_decision(level="L5", risk="R4", db=_FakeStore()) == "deny"


@pytest.mark.asyncio
async def test_matrix_acceptance_r0_always_allows():
    for level in risk.AUTONOMY_LEVELS:
        assert await risk.matrix_decision(level=level, risk="R0", db=_FakeStore()) == "allow", level


@pytest.mark.asyncio
async def test_r4_red_line_cannot_be_overridden_even_in_store():
    """A stored cell claiming L5:R4 = allow must be rejected (FR-4, T016)."""
    store = _FakeStore({"L5:R4": "allow"})
    assert await risk.matrix_decision(level="L5", risk="R4", db=store) == "deny"


@pytest.mark.asyncio
async def test_stored_cell_overrides_canonical_when_legal():
    """L3:R1 may be legally edited to require_approval; the store value wins."""
    store = _FakeStore({"L3:R1": "require_approval"})
    assert await risk.matrix_decision(level="L3", risk="R1", db=store) == "require_approval"


@pytest.mark.asyncio
async def test_unknown_cell_falls_back_to_canonical():
    store = _FakeStore({})  # no stored cells
    # L4 x R3 canonical = require_approval
    assert await risk.matrix_decision(level="L4", risk="R3", db=store) == "require_approval"
    # R4 stays deny no matter what
    assert await risk.matrix_decision(level="L1", risk="R4", db=store) == "deny"


# --- risk tier lookup ----------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_tool_defaults_to_r0():
    store = _FakeStore()
    assert await risk.risk_level_for(tenant_id="t", tool="no-such-tool") == "R0"


@pytest.mark.asyncio
async def test_register_and_lookup_risk_tier():
    store = _FakeStore()

    async def _no_db():
        raise RuntimeError("no db in test")

    import app.governance.risk as risk_mod

    original = risk_mod._get_db
    risk_mod._get_db = lambda: store
    try:
        await risk_mod.register_risk_tier(tenant_id="t", tool="file.write", risk="R3")
        assert await risk_mod.risk_level_for(tenant_id="t", tool="file.write") == "R3"
        assert await risk_mod.risk_level_for(tenant_id="other", tool="file.write") == "R0"
    finally:
        risk_mod._get_db = original


@pytest.mark.asyncio
async def test_invalid_risk_level_rejected():
    store = _FakeStore()
    import app.governance.risk as risk_mod

    original = risk_mod._get_db
    risk_mod._get_db = lambda: store
    try:
        with pytest.raises(ValueError):
            await risk_mod.register_risk_tier(tenant_id="t", tool="x", risk="R9")
    finally:
        risk_mod._get_db = original
