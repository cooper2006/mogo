"""Tests for the tenant lifecycle service (Phase 7–8): T039 / T041 / T043 / T050.

Uses an in-memory fake of ``get_db`` so no MongoDB is required. The fake only
implements the handful of operations ``tenant_lifecycle`` performs.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.services import tenant_lifecycle


def _matches(doc: dict, flt: dict | None) -> bool:
    if not flt:
        return True
    for key, value in flt.items():
        if doc.get(key) != value:
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
                for key in (update.get("$unset") or {}):
                    doc.pop(key, None)
                return
        if upsert:
            new_doc = dict(flt)
            new_doc.update(update.get("$set", {}))
            self.docs.append(new_doc)

    async def count_documents(self, flt) -> int:
        return sum(1 for doc in self.docs if _matches(doc, flt))

    async def delete_many(self, flt):
        class _Result:
            deleted_count = 0

        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not _matches(doc, flt)]
        result = _Result()
        result.deleted_count = before - len(self.docs)
        return result


class _Mem:
    def __init__(self) -> None:
        self.collections: dict[str, _MemCol] = {}

    def __getitem__(self, name: str) -> _MemCol:
        return self.collections.setdefault(name, _MemCol())


def _patch(monkeypatch, mem: _Mem) -> None:
    monkeypatch.setattr(tenant_lifecycle, "get_db", lambda: mem)

    async def no_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(tenant_lifecycle, "_record_audit", no_audit)


def _seed(mem: _Mem, main_id: str = "acme-1a2b3c4d5e6f7a8b9c0d1e2f", status: str = "active") -> None:
    mem["tenants"].docs.append({"_id": "t1", "main_id": main_id, "name": "Acme", "status": status})
    mem["organizations"].docs.append({"main_id": main_id, "status": "active"})
    mem["org_quota_policies"].docs.append({"main_id": main_id, "status": "active"})


# ---------------------------------------------------------------------------
# T039 archive
# ---------------------------------------------------------------------------


def test_archive_sets_status_and_disables_config(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem)
    _patch(monkeypatch, mem)

    result = asyncio.run(tenant_lifecycle.archive_tenant(mem["tenants"].docs[0]["main_id"], actor="platform", reason="churn"))

    assert result["status"] == "archived"
    tenant = mem["tenants"].docs[0]
    assert tenant["status"] == "archived"
    assert tenant["archive_reason"] == "churn"
    assert tenant["archived_at"] is not None
    # decisions 3/13/18: in-tenant config flips to disabled so every check short-circuits
    assert mem["organizations"].docs[0]["status"] == "disabled"
    assert mem["org_quota_policies"].docs[0]["status"] == "disabled"


def test_archive_twice_is_conflict(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem, status="archived")
    _patch(monkeypatch, mem)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(tenant_lifecycle.archive_tenant(mem["tenants"].docs[0]["main_id"], actor="platform"))
    assert exc.value.status_code == 409


def test_archive_rejects_reserved_identifier(monkeypatch) -> None:
    mem = _Mem()
    _patch(monkeypatch, mem)
    for bad in ("__platform__", "default", "short"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(tenant_lifecycle.archive_tenant(bad, actor="platform"))
        assert exc.value.status_code == 400


def test_archive_missing_tenant_is_404(monkeypatch) -> None:
    mem = _Mem()
    _patch(monkeypatch, mem)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(tenant_lifecycle.archive_tenant("acme-1a2b3c4d5e6f7a8b9c0d1e2f", actor="platform"))
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# T041 restore
# ---------------------------------------------------------------------------


def test_restore_returns_to_active_and_clears_archive_fields(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem, status="archived")
    mem["organizations"].docs[0]["status"] = "disabled"
    mem["tenants"].docs[0].update({"archived_at": "2026-01-01", "archive_reason": "churn"})
    _patch(monkeypatch, mem)

    result = asyncio.run(tenant_lifecycle.restore_tenant(mem["tenants"].docs[0]["main_id"], actor="platform"))

    assert result["status"] == "active"
    tenant = mem["tenants"].docs[0]
    assert tenant["status"] == "active"
    assert "archived_at" not in tenant
    assert "archive_reason" not in tenant
    assert mem["organizations"].docs[0]["status"] == "active"
    assert mem["org_quota_policies"].docs[0]["status"] == "active"


def test_restore_non_archived_is_conflict(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem, status="active")
    _patch(monkeypatch, mem)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(tenant_lifecycle.restore_tenant(mem["tenants"].docs[0]["main_id"], actor="platform"))
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# T043 licensing count (decision 18: archived tenants do not count)
# ---------------------------------------------------------------------------


def test_active_tenant_count_excludes_archived_and_disabled(monkeypatch) -> None:
    mem = _Mem()
    mem["tenants"].docs = [
        {"main_id": "t-a", "status": "active"},
        {"main_id": "t-b", "status": "active"},
        {"main_id": "t-c", "status": "disabled"},
        {"main_id": "t-d", "status": "archived"},
        {"main_id": "t-e", "status": "purged"},
    ]
    _patch(monkeypatch, mem)
    assert asyncio.run(tenant_lifecycle.active_tenant_count()) == 2


def test_archive_drops_tenant_from_licensing_count(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem)
    _patch(monkeypatch, mem)
    assert asyncio.run(tenant_lifecycle.active_tenant_count()) == 1
    asyncio.run(tenant_lifecycle.archive_tenant(mem["tenants"].docs[0]["main_id"], actor="platform"))
    assert asyncio.run(tenant_lifecycle.active_tenant_count()) == 0


# ---------------------------------------------------------------------------
# update_tenant / tenant_view (T027/T030)
# ---------------------------------------------------------------------------


def test_update_tenant_rename_and_member_limit(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem)
    _patch(monkeypatch, mem)
    view = asyncio.run(
        tenant_lifecycle.update_tenant(
            mem["tenants"].docs[0]["main_id"], actor="platform", name=" Renamed ", member_limit=25
        )
    )
    assert view["name"] == "Renamed"
    assert view["memberLimit"] == 25
    assert mem["tenants"].docs[0]["name"] == "Renamed"


def test_update_tenant_clears_member_limit_with_null_string(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem)
    mem["tenants"].docs[0]["member_limit"] = 10
    _patch(monkeypatch, mem)
    view = asyncio.run(
        tenant_lifecycle.update_tenant(mem["tenants"].docs[0]["main_id"], actor="platform", member_limit="null")
    )
    assert view["memberLimit"] is None


def test_update_tenant_rejects_negative_member_limit(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem)
    _patch(monkeypatch, mem)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(tenant_lifecycle.update_tenant(mem["tenants"].docs[0]["main_id"], actor="platform", member_limit=-1))
    assert exc.value.status_code == 400


def test_update_tenant_cannot_reenable_archived(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem, status="archived")
    _patch(monkeypatch, mem)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(tenant_lifecycle.update_tenant(mem["tenants"].docs[0]["main_id"], actor="platform", status_target="active"))
    assert exc.value.status_code == 409


def test_tenant_view_exposes_no_business_metrics(monkeypatch) -> None:
    """T027: the platform console must not see member counts or usage."""
    tenant = {
        "_id": "t1",
        "main_id": "acme-1a2b3c4d5e6f7a8b9c0d1e2f",
        "name": "Acme",
        "status": "active",
        "edition": "enterprise",
        "admin_username": "adminA",
        "member_limit": 10,
        "created_by": "platform-admin:x",
        "member_count": 42,
        "used_points": 999,
        "total_points": 1000,
    }
    view = asyncio.run(tenant_lifecycle.tenant_view(tenant))
    assert set(view) == {
        "mainId",
        "name",
        "status",
        "edition",
        "adminUsername",
        "memberLimit",
        "createdAt",
        "createdBy",
        "archivedAt",
        "archiveReason",
        "purgedAt",
    }
    assert "member_count" not in view
    assert "used_points" not in view


def test_tenant_view_missing_member_limit_is_none(monkeypatch) -> None:
    view = asyncio.run(
        tenant_lifecycle.tenant_view({"main_id": "acme-1a2b3c4d5e6f7a8b9c0d1e2f", "name": "A", "status": "active"})
    )
    assert view["memberLimit"] is None
    assert view["edition"] == "community"  # documented default
