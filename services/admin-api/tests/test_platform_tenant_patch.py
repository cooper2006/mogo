"""Route-level tests for the platform tenant PATCH endpoint (T030).

The service-level test in ``test_tenant_lifecycle.py`` covers
``update_tenant(member_limit="null")`` directly, but nothing exercised how the
*route* builds that argument from a JSON payload. That gap let a rename-only
PATCH clear ``member_limit``: the route defaulted the field to the ``"null"``
sentinel whenever the caller omitted it.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api.routes.platform import tenants as platform_tenants
from app.core import product_edition
from app.services import tenant_lifecycle

MAIN_ID = "acme-1a2b3c4d5e6f7a8b9c0d1e2f"


def _matches(doc: dict, flt: dict | None) -> bool:
    if not flt:
        return True
    for key, value in flt.items():
        if isinstance(value, dict):
            for op, operand in value.items():
                if op == "$ne" and doc.get(key) == operand:
                    return False
                elif op != "$ne":
                    raise AssertionError(f"unsupported operator: {op}")
        elif doc.get(key) != value:
            return False
    return True


class _MemCol:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    async def find_one(self, flt, *args, **kwargs):
        for doc in self.docs:
            if _matches(doc, flt):
                return dict(doc)
        return None

    async def update_one(self, flt, update, upsert=False):
        for doc in self.docs:
            if _matches(doc, flt):
                doc.update(update.get("$set", {}))
                for key in update.get("$unset") or {}:
                    doc.pop(key, None)
                return
        if upsert:
            new_doc = dict(flt)
            new_doc.update(update.get("$set", {}))
            self.docs.append(new_doc)


class _Mem:
    def __init__(self) -> None:
        self.collections: dict[str, _MemCol] = {}

    def __getitem__(self, name: str) -> _MemCol:
        return self.collections.setdefault(name, _MemCol())


def _seed(mem: _Mem, member_limit: int | None = 10) -> None:
    mem["tenants"].docs.append(
        {
            "_id": "t1",
            "tenant_id": MAIN_ID,
            "name": "Acme",
            "status": "active",
            "member_limit": member_limit,
            "admin_username": "acme-admin",
        }
    )


def _patch(monkeypatch, mem: _Mem) -> None:
    monkeypatch.setattr(tenant_lifecycle, "get_db", lambda: mem)
    # ``assert_member_limit_settable`` lives in product_edition and resolves the
    # organizations row through *its own* get_db, so both modules need the fake.
    monkeypatch.setattr(product_edition, "get_db", lambda: mem)

    async def no_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(tenant_lifecycle, "_record_audit", no_audit)


def test_patch_rename_only_keeps_member_limit(monkeypatch) -> None:
    """Regression: a payload with no ``memberLimit`` must not clear the cap."""
    mem = _Mem()
    _seed(mem, member_limit=10)
    _patch(monkeypatch, mem)

    view = asyncio.run(platform_tenants.patch_tenant(MAIN_ID, {"name": "Acme Renamed"}, platform_admin={"username": "root"}))

    assert view["name"] == "Acme Renamed"
    assert view["memberLimit"] == 10, "renaming must not wipe member_limit"
    assert mem["tenants"].docs[0]["member_limit"] == 10


def test_patch_status_only_keeps_member_limit(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem, member_limit=7)
    _patch(monkeypatch, mem)

    asyncio.run(platform_tenants.patch_tenant(MAIN_ID, {"status": "disabled"}, platform_admin={"username": "root"}))
    assert mem["tenants"].docs[0]["member_limit"] == 7


def test_patch_can_still_clear_member_limit_explicitly(monkeypatch) -> None:
    """The API contract keeps an explicit way to remove the cap."""
    mem = _Mem()
    _seed(mem, member_limit=10)
    _patch(monkeypatch, mem)

    view = asyncio.run(
        platform_tenants.patch_tenant(MAIN_ID, {"memberLimit": "null"}, platform_admin={"username": "root"})
    )
    assert view["memberLimit"] is None


def test_patch_can_set_member_limit(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem, member_limit=None)
    _patch(monkeypatch, mem)

    view = asyncio.run(
        platform_tenants.patch_tenant(MAIN_ID, {"memberLimit": 25}, platform_admin={"username": "root"})
    )
    assert view["memberLimit"] == 25


def test_patch_accepts_snake_case_member_limit(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem, member_limit=None)
    _patch(monkeypatch, mem)

    view = asyncio.run(
        platform_tenants.patch_tenant(MAIN_ID, {"member_limit": 3}, platform_admin={"username": "root"})
    )
    assert view["memberLimit"] == 3


def test_patch_rejects_negative_member_limit(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem)
    _patch(monkeypatch, mem)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(platform_tenants.patch_tenant(MAIN_ID, {"memberLimit": -1}, platform_admin={"username": "root"}))
    assert exc.value.status_code == 400
