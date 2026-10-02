"""020 FR-035/036/037: unlimited org short-circuit (no 402 for new members)."""

from __future__ import annotations

import pytest

from app.core import quota_policy


class _FakeCollection:
    def __init__(self, doc: dict) -> None:
        self._doc = doc

    async def find_one(self, *args, **kwargs):
        return self._doc


class _FakeDB:
    def __init__(self, org_doc: dict) -> None:
        self._org = org_doc

    def __getitem__(self, key: str):
        if key == quota_policy.ORG_COLLECTION:
            return _FakeCollection(self._org)
        # Other collections: empty docs so the limited path proceeds without
        # hitting a real Mongo.
        return _FakeCollection(None)


@pytest.fixture
def patch_db(monkeypatch):
    states: dict[str, dict] = {}

    def _set(org_doc):
        states["org"] = org_doc

    def _fake_get_db():
        return _FakeDB(states["org"])

    monkeypatch.setattr(quota_policy, "get_db", _fake_get_db)
    return _set


@pytest.mark.asyncio
async def test_unlimited_org_short_circuits_quota_check(patch_db):
    patch_db({"main_id": "t1", "org_name": "Org", "points_unlimited": True})
    summary = await quota_policy.get_quota_summary("t1", {"_id": "u1", "org_name": "Org"})
    assert summary["unlimited"] is True
    assert summary["status"] == "active"
    # assert path must not raise (previously raised 402 for new members).
    got = await quota_policy.assert_quota_available("t1", {"_id": "u1", "org_name": "Org"})
    assert got["unlimited"] is True
