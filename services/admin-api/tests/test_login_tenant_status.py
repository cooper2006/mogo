"""Tests for T040: archived / non-active tenants cannot log in (decision 13).

Covers ``_assert_tenant_login_allowed`` / ``_tenant_blocked_for_login`` in
``app/api/routes/auth.py`` — the three entry points are:

* the explicit-``mainId`` login path,
* the cross-tenant discovery path (single and challenge candidates),
* the ``/login/select-tenant`` path.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from fastapi import HTTPException

from app.api.routes import auth
from app.core.tenant_identity import PLATFORM_TENANT_ID


class _TenantCollection:
    """In-memory stand-in for ``db['tenants']`` returning one fixed row per main_id."""

    def __init__(self, rows: dict) -> None:
        self._rows = rows

    async def find_one(self, query, projection=None):
        return self._rows.get(query.get("main_id"))


class _DB:
    def __init__(self, tenant_rows: dict) -> None:
        self._tenants = _TenantCollection(tenant_rows)

    def __getitem__(self, name: str):
        assert name == "tenants", name
        return self._tenants


def _patch_db(monkeypatch, tenant_rows: dict) -> None:
    monkeypatch.setattr(auth, "get_db", lambda: _DB(tenant_rows))


# ---------------------------------------------------------------------------
# _assert_tenant_login_allowed
# ---------------------------------------------------------------------------


def test_reserved_identifiers_skip_tenant_check(monkeypatch) -> None:
    checks: list[str] = []
    monkeypatch.setattr(auth, "get_db", lambda: (_ for _ in ()).throw(AssertionError("db touched")))
    for ident in ("", "default", PLATFORM_MAIN_ID):
        asyncio.run(auth._assert_tenant_login_allowed(ident))
        checks.append(ident)
    assert checks == ["", "default", PLATFORM_MAIN_ID]


def test_unknown_tenant_keeps_legacy_semantics(monkeypatch) -> None:
    _patch_db(monkeypatch, {})
    asyncio.run(auth._assert_tenant_login_allowed("acme-123"))  # no raise


def test_active_tenant_passes(monkeypatch) -> None:
    _patch_db(monkeypatch, {"acme": {"status": "active"}})
    asyncio.run(auth._assert_tenant_login_allowed("acme"))


@pytest.mark.parametrize("state", ["archived", "purged", "", None])
def test_non_active_tenant_is_rejected(monkeypatch, state) -> None:
    _patch_db(monkeypatch, {"acme": {"status": state} if state is not None else {}})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth._assert_tenant_login_allowed("acme"))
    assert exc.value.status_code == 403
    assert exc.value.detail == "Tenant is not active"


# ---------------------------------------------------------------------------
# _tenant_blocked_for_login (candidate filtering)
# ---------------------------------------------------------------------------


def test_candidate_filter_is_blocked_for_archived(monkeypatch) -> None:
    _patch_db(monkeypatch, {"acme": {"status": "archived"}})
    assert asyncio.run(auth._tenant_blocked_for_login("acme")) is True


def test_candidate_filter_allows_active_and_reserved(monkeypatch) -> None:
    _patch_db(monkeypatch, {"acme": {"status": "active"}})
    assert asyncio.run(auth._tenant_blocked_for_login("acme")) is False
    assert asyncio.run(auth._tenant_blocked_for_login(PLATFORM_MAIN_ID)) is False
    assert asyncio.run(auth._tenant_blocked_for_login("default")) is False


def test_candidate_filter_unknown_main_id_allows(monkeypatch) -> None:
    _patch_db(monkeypatch, {})
    assert asyncio.run(auth._tenant_blocked_for_login("acme")) is False
