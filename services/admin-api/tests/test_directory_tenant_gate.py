"""FR-024: an archived tenant must not gain members through the directory API.

Audit finding P0-4 listed four entry points that had to reject non-active
tenants. Three were covered on the chat-api side
(``end_user_tenant_access._selectable_tenant_main_ids``) and in admin-api's
login path (``test_login_tenant_status.py``). The fourth — the admin-api
*directory* API, which creates members by hand (``POST /users``) and by invite
acceptance — was not: an admin session that predates the archive could still
add people.

These tests pin ``tenant_registry.is_tenant_active`` and its two call sites.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

from app.services import tenant_registry
from app.api.routes import directory

MAIN_ID = "acme-1a2b3c4d5e6f7a8b9c0d1e2f"


class _MemCol:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    async def find_one(self, flt, *args, **kwargs):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in (flt or {}).items()):
                return dict(doc)
        return None


class _Mem:
    def __init__(self) -> None:
        self.collections: dict[str, _MemCol] = {}

    def __getitem__(self, name: str) -> _MemCol:
        return self.collections.setdefault(name, _MemCol())


def _wire(monkeypatch, mem: _Mem) -> None:
    monkeypatch.setattr(tenant_registry, "get_db", lambda: mem)
    monkeypatch.setattr(directory, "get_db", lambda: mem)


def _seed(mem: _Mem, status: str | None) -> None:
    """Seed a registry row; ``status=None`` means *no row at all*."""
    if status is not None:
        mem["tenants"].docs.append({"main_id": MAIN_ID, "status": status})


# ---------------------------------------------------------------------------
# is_tenant_active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_tenant_passes(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem, "active")
    _wire(monkeypatch, mem)
    assert await tenant_registry.is_tenant_active(MAIN_ID) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["disabled", "archived", "purged"])
async def test_non_active_tenant_is_rejected(monkeypatch, status: str) -> None:
    mem = _Mem()
    _seed(mem, status)
    _wire(monkeypatch, mem)
    assert await tenant_registry.is_tenant_active(MAIN_ID) is False


@pytest.mark.asyncio
async def test_tenant_without_registry_row_is_grandfathered(monkeypatch) -> None:
    """Pre-migration deployments have an empty ``tenants`` collection.

    Failing closed there would lock every employee out of an existing
    deployment, so a missing row means "not yet migrated" → allowed.
    """
    mem = _Mem()
    _seed(mem, None)
    _wire(monkeypatch, mem)
    assert await tenant_registry.is_tenant_active(MAIN_ID) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("main_id", ["", "   ", None])
async def test_blank_identifier_is_rejected(monkeypatch, main_id: Any) -> None:
    mem = _Mem()
    _seed(mem, "active")
    _wire(monkeypatch, mem)
    assert await tenant_registry.is_tenant_active(main_id) is False


# ---------------------------------------------------------------------------
# The directory call sites
# ---------------------------------------------------------------------------


def _archive(mem: _Mem, status: str = "archived") -> None:
    mem["tenants"].docs.clear()
    mem["tenants"].docs.append({"main_id": MAIN_ID, "status": status})


def test_invite_accept_rejected_for_archived_tenant(monkeypatch) -> None:
    """An invite generated before the archive must not keep working."""
    mem = _Mem()
    _archive(mem)
    _wire(monkeypatch, mem)

    async def fake_find_invite(token: str) -> dict:
        return {"main_id": MAIN_ID, "status": "active", "role_ids": [], "primary_role_id": ""}

    monkeypatch.setattr(directory, "_find_active_invite", fake_find_invite)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(directory.accept_invite_link("tok", _EmptyPayload()))
    assert exc.value.status_code == 409


def test_invite_accept_allowed_for_active_tenant(monkeypatch) -> None:
    """Regression guard: the gate must not reject a healthy tenant."""
    mem = _Mem()
    _archive(mem, "active")
    _wire(monkeypatch, mem)

    async def fake_find_invite(token: str) -> dict:
        return {"main_id": MAIN_ID, "status": "active", "role_ids": [], "primary_role_id": ""}

    class _StubRoleService:
        def __init__(self) -> None:
            # Constructing the real service opens a DB connection, which this
            # unit test has no business doing. Reaching *here* is the proof
            # that the tenant status gate let the request through.
            raise _PassedGate()

        async def validate_roles(self, *args, **kwargs) -> None:
            raise AssertionError("unreachable")

    monkeypatch.setattr(directory, "_find_active_invite", fake_find_invite)
    monkeypatch.setattr(directory, "PositionRoleService", _StubRoleService)

    with pytest.raises(_PassedGate):
        asyncio.run(directory.accept_invite_link("tok", _EmptyPayload()))


def test_create_user_rejected_for_archived_tenant(monkeypatch) -> None:
    mem = _Mem()
    _archive(mem)
    _wire(monkeypatch, mem)
    monkeypatch.setattr(directory, "_main_id", lambda user: MAIN_ID)

    calls: list[str] = []

    async def fail_capacity(main_id: str) -> None:
        calls.append(main_id)

    monkeypatch.setattr(directory, "assert_member_capacity", fail_capacity)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(directory.create_user(_EmptyPayload(), {"main_id": MAIN_ID}))
    assert exc.value.status_code == 409
    assert calls == [], "the tenant gate must run before the capacity gate"


class _EmptyPayload:
    """Minimal stand-in; the tests stop at the tenant gate, before any field use."""

    password = "x" * 8
    loginName = ""
    departmentIds: list[str] = []
    primaryDepartmentId = ""
    roleIds: list[str] = []
    primaryRoleId = ""
    mobile = ""
    email = ""


class _PassedGate(Exception):
    """Raised to prove execution got past the tenant status check."""
