"""Tests for the platform tenant registry (Phase 2–4 / feature 020): T007 + T008.

These use an in-memory fake of ``get_db`` so they run without a real MongoDB.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import tenant_registry


def _matches(doc: dict, flt: dict | None) -> bool:
    if not flt:
        return True
    for key, value in flt.items():
        if doc.get(key) != value:
            return False
    return True


class _Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = list(docs)

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield dict(d)

        return gen()


class _MemCol:
    def __init__(self) -> None:
        self.docs: list[dict] = []
        self.indexes: list = []

    async def create_index(self, *args, **kwargs) -> None:
        self.indexes.append(args)

    async def distinct(self, field: str) -> list:
        return list({d.get(field) for d in self.docs})

    def find(self, flt=None, projection=None):
        return _Cursor(self.docs)

    async def find_one(self, flt, projection=None):
        for d in self.docs:
            if _matches(d, flt):
                return dict(d)
        return None

    async def find_one_and_update(self, flt, update, upsert=False, return_document=None):
        doc = None
        for d in self.docs:
            if _matches(d, flt):
                doc = d
                break
        inserted = False
        if doc is None:
            if not upsert:
                return None
            doc = {}
            if "_id" in (flt or {}):
                doc["_id"] = flt["_id"]
            inserted = True
        doc.update(update.get("$set", {}))
        if inserted:
            doc.update(update.get("$setOnInsert", {}))
        if doc not in self.docs:
            self.docs.append(doc)
        return dict(doc)


class _Mem:
    def __init__(self) -> None:
        self.collections: dict[str, _MemCol] = {}

    def __getitem__(self, name: str) -> _MemCol:
        return self.collections.setdefault(name, _MemCol())


def test_ensure_tenant_record_is_idempotent(monkeypatch) -> None:
    mem = _Mem()
    monkeypatch.setattr(tenant_registry, "get_db", lambda: mem)

    asyncio.run(tenant_registry.ensure_tenant_record(tenant_id="t1", name="First", created_by="setup-wizard"))
    asyncio.run(tenant_registry.ensure_tenant_record(tenant_id="t1", name="Updated", created_by="migration"))

    docs = mem["tenants"].docs
    assert len(docs) == 1
    assert docs[0]["name"] == "Updated"  # $set is applied on re-run
    assert docs[0]["created_by"] == "setup-wizard"  # $setOnInsert is NOT overwritten
    assert docs[0]["status"] == "active"


def test_backfill_excludes_reserved_and_skips_existing(monkeypatch) -> None:
    mem = _Mem()
    mem["admin_accounts"].docs = [
        {"_id": "1", "tenant_id": "tenant-a", "username": "adminA", "is_protected": True},
        {"_id": "2", "tenant_id": "tenant-b", "username": "adminB"},
        {"_id": "3", "tenant_id": "default", "username": "x"},
        {"_id": "4", "tenant_id": None, "username": "y"},
        {"_id": "5", "tenant_id": "__platform__", "username": "plat"},
    ]
    mem["organizations"].docs = [
        {"tenant_id": "tenant-a", "org_name": "Acme A", "edition": "enterprise"},
        {"tenant_id": "tenant-b", "org_name": "Acme B"},
    ]
    # tenant-a already registered by a prior run — must not be re-created.
    mem["tenants"].docs = [{"_id": "t0", "tenant_id": "tenant-a", "name": "Acme A", "created_by": "old", "status": "active"}]

    monkeypatch.setattr(tenant_registry, "get_db", lambda: mem)
    registered = asyncio.run(tenant_registry.backfill_tenants_from_accounts())

    # only tenant-b is newly registered (reserved ids skipped, tenant-a existing)
    assert registered == 1
    assert {d["tenant_id"] for d in mem["tenants"].docs} == {"tenant-a", "tenant-b"}

    tb = next(d for d in mem["tenants"].docs if d["tenant_id"] == "tenant-b")
    assert tb["name"] == "Acme B"
    assert tb["edition"] == "community"  # defaults when the org has no edition
    assert tb["admin_username"] == "adminB"
    assert tb["created_by"] == "migration"

    ta = next(d for d in mem["tenants"].docs if d["tenant_id"] == "tenant-a")
    assert ta["created_by"] == "old"  # untouched


def test_backfill_is_reentrant(monkeypatch) -> None:
    mem = _Mem()
    mem["admin_accounts"].docs = [{"_id": "1", "tenant_id": "tenant-a", "username": "adminA"}]

    monkeypatch.setattr(tenant_registry, "get_db", lambda: mem)
    first = asyncio.run(tenant_registry.backfill_tenants_from_accounts())
    second = asyncio.run(tenant_registry.backfill_tenants_from_accounts())

    assert first == 1
    assert second == 0  # nothing new on the second pass
    assert len(mem["tenants"].docs) == 1
