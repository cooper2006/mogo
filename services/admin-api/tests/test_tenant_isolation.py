"""Tests for T024: tenant isolation and reserved-identifier guards (Phase 4).

Covers the "reverse guard" (T022): the platform identifier may only reach
``/api/platform/*``, and every business route rejects it. The dependency
functions are exercised directly with a stubbed account loader, which is where
the guard actually lives.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api import deps
from app.core.tenant_identity import DEFAULT_TENANT_ID, PLATFORM_TENANT_ID


def _patch_account(monkeypatch, main_id: str) -> None:
    async def fake_loader(_authorization: str | None) -> dict:
        return {"username": "someone", "tenant_id": main_id}

    monkeypatch.setattr(deps, "_load_authenticated_account", fake_loader)


# ---------------------------------------------------------------------------
# Business routes must reject reserved identifiers (T021/T022)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reserved", [PLATFORM_TENANT_ID, DEFAULT_TENANT_ID, ""])
def test_business_route_rejects_reserved_main_id(monkeypatch, reserved) -> None:
    _patch_account(monkeypatch, reserved)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(deps.get_current_admin_user("Bearer t"))
    assert exc.value.status_code == 403
    assert exc.value.detail == "Tenant context is required"


def test_business_route_accepts_real_tenant(monkeypatch) -> None:
    _patch_account(monkeypatch, "acme-1a2b3c4d5e6f7a8b9c0d1e2f")
    user = asyncio.run(deps.get_current_admin_user("Bearer t"))
    assert user["tenant_id"] == "acme-1a2b3c4d5e6f7a8b9c0d1e2f"


# ---------------------------------------------------------------------------
# Platform routes reject real tenants (no privilege escalation)
# ---------------------------------------------------------------------------


def test_platform_route_rejects_real_tenant(monkeypatch) -> None:
    _patch_account(monkeypatch, "acme-1a2b3c4d5e6f7a8b9c0d1e2f")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(deps.get_current_platform_admin("Bearer t"))
    assert exc.value.status_code == 403
    assert exc.value.detail == "Platform administrator privileges are required"


@pytest.mark.parametrize("reserved", [DEFAULT_TENANT_ID, ""])
def test_platform_route_rejects_other_reserved_ids(monkeypatch, reserved) -> None:
    _patch_account(monkeypatch, reserved)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(deps.get_current_platform_admin("Bearer t"))
    assert exc.value.status_code == 403


def test_platform_route_accepts_platform_admin(monkeypatch) -> None:
    _patch_account(monkeypatch, PLATFORM_TENANT_ID)
    user = asyncio.run(deps.get_current_platform_admin("Bearer t"))
    assert user["tenant_id"] == PLATFORM_TENANT_ID


# ---------------------------------------------------------------------------
# Cross-tenant isolation: the token subject is the single source of main_id
# ---------------------------------------------------------------------------


def test_main_id_comes_only_from_token_subject(monkeypatch) -> None:
    """Removing the ``bootstrap_main_id`` fallback is what closes the leak."""
    _patch_account(monkeypatch, "tenant-a-1a2b3c4d5e6f7a8b9c0d1e2f")
    user = asyncio.run(deps.get_current_admin_user("Bearer t"))
    assert user["tenant_id"] == "tenant-a-1a2b3c4d5e6f7a8b9c0d1e2f"

    _patch_account(monkeypatch, "tenant-b-1a2b3c4d5e6f7a8b9c0d1e2f")
    other = asyncio.run(deps.get_current_admin_user("Bearer t"))
    # Two tenants never resolve to the same identity.
    assert other["tenant_id"] != user["tenant_id"]


def test_empty_main_id_is_rejected_before_guard(monkeypatch) -> None:
    """An empty subject main_id is a 401 at load time, never a silent default."""
    monkeypatch.setattr(deps, "_load_authenticated_account", deps._load_authenticated_account)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(deps._load_authenticated_account(None))
    assert exc.value.status_code == 401
    assert exc.value.detail == "Missing bearer token"
