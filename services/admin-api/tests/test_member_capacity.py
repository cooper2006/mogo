"""Member-cap enforcement must honour the platform-set limit (FR-022).

The platform admin sets a tenant's member cap via
``PATCH /api/platform/tenants/{main_id}`` (``memberLimit``). That value is
stored on the **platform** record (``tenants.member_limit``), while the edition
default lives on the **in-tenant** record (``organizations.user_limit``).

Nothing ever mirrored the two, so the capacity gate in
``assert_member_capacity`` — which only read ``organizations.user_limit`` —
silently ignored the platform setting: the PATCH was audited and displayed, but
never enforced. These tests pin the resolved limit
(:func:`app.core.product_edition.resolve_member_limit`) as the single source
used by enforcement *and* by the dashboard readout.

Uses an in-memory fake DB; no MongoDB required.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

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

    async def count_documents(self, flt, *args, **kwargs):
        return sum(1 for doc in self.docs if _matches(doc, flt))


class _Mem:
    def __init__(self) -> None:
        self.collections: dict[str, _MemCol] = {}

    def __getitem__(self, name: str) -> _MemCol:
        return self.collections.setdefault(name, _MemCol())


def _seed(
    mem: _Mem,
    *,
    tenant_member_limit: int | None = None,
    user_limit: int | None = None,
    edition: str = "cloud",
    members: int = 0,
    with_tenant_row: bool = True,
) -> None:
    if with_tenant_row:
        mem["tenants"].docs.append(
            {
                "_id": "t1",
                "tenant_id": MAIN_ID,
                "name": "Acme",
                "status": "active",
                "edition": edition,
                "member_limit": tenant_member_limit,
            }
        )
    mem["organizations"].docs.append(
        {
            "tenant_id": MAIN_ID,
            "org_name": "Acme",
            "edition": edition,
            "tier": "free",
            "user_limit": user_limit,
        }
    )
    for i in range(members):
        mem["end_users"].docs.append({"tenant_id": MAIN_ID, "name": f"user-{i}"})


def _wire(monkeypatch, mem: _Mem) -> None:
    """Point both modules at the same fake DB (they read different collections)."""
    monkeypatch.setattr(product_edition, "get_db", lambda: mem)
    monkeypatch.setattr(tenant_lifecycle, "get_db", lambda: mem)

    async def no_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(tenant_lifecycle, "_record_audit", no_audit)


# ---------------------------------------------------------------------------
# resolve_member_limit — the override / default precedence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_platform_override_wins_over_edition_default(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem, tenant_member_limit=3, user_limit=50)
    _wire(monkeypatch, mem)

    assert await product_edition.resolve_member_limit(MAIN_ID) == 3


@pytest.mark.asyncio
async def test_falls_back_to_edition_default_without_override(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem, tenant_member_limit=None, user_limit=7)
    _wire(monkeypatch, mem)

    assert await product_edition.resolve_member_limit(MAIN_ID) == 7


@pytest.mark.asyncio
async def test_legacy_tenant_without_registry_row_keeps_edition_default(monkeypatch) -> None:
    """Pre-migration deployments have no ``tenants`` row — must not lock them out."""
    mem = _Mem()
    _seed(mem, user_limit=9, with_tenant_row=False)
    _wire(monkeypatch, mem)

    assert await product_edition.resolve_member_limit(MAIN_ID) == 9


@pytest.mark.asyncio
async def test_community_tenant_ignores_a_stale_override(monkeypatch) -> None:
    """Community is unlimited by edition — a stored cap must not apply.

    The write-side guard (``assert_member_limit_settable``) refuses to record a
    cap for a community tenant, so the only way this row can exist is a write
    that predates the guard. The read side ignores it for the same reason the
    guard exists: a cap on an unlimited edition is not a limit, it is a value
    whose meaning nobody agreed on.
    """
    mem = _Mem()
    _seed(mem, edition="community", user_limit=None, tenant_member_limit=None)
    _wire(monkeypatch, mem)
    assert await product_edition.resolve_member_limit(MAIN_ID) is None

    mem["tenants"].docs[0]["member_limit"] = 2
    assert await product_edition.resolve_member_limit(MAIN_ID) is None


@pytest.mark.asyncio
async def test_setting_a_cap_on_a_community_tenant_is_refused(monkeypatch) -> None:
    """The refusal is explicit (409) rather than a read-side silent ignore."""
    mem = _Mem()
    _seed(mem, edition="community", user_limit=None, tenant_member_limit=None)
    _wire(monkeypatch, mem)

    with pytest.raises(HTTPException) as exc:
        await tenant_lifecycle.update_tenant(MAIN_ID, actor="root", member_limit=3)
    assert exc.value.status_code == 409
    assert mem["tenants"].docs[0]["member_limit"] is None, "nothing may be written"

    # Clearing stays allowed — it restores the edition default (unlimited).
    await tenant_lifecycle.update_tenant(MAIN_ID, actor="root", member_limit="null")
    assert mem["tenants"].docs[0]["member_limit"] is None


@pytest.mark.asyncio
async def test_a_community_tenant_in_the_gate_is_still_unlimited(monkeypatch) -> None:
    """End to end: a community tenant with many members never blocks."""
    mem = _Mem()
    _seed(mem, edition="community", user_limit=None, tenant_member_limit=1, members=50)
    _wire(monkeypatch, mem)

    await product_edition.assert_member_capacity(MAIN_ID)


@pytest.mark.asyncio
async def test_non_numeric_override_falls_back_and_warns(monkeypatch, caplog) -> None:
    mem = _Mem()
    _seed(mem, tenant_member_limit="not-a-number", user_limit=4)
    _wire(monkeypatch, mem)

    assert await product_edition.resolve_member_limit(MAIN_ID) == 4


# ---------------------------------------------------------------------------
# assert_member_capacity — the gate that was silently bypassed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_platform_set_cap_is_enforced(monkeypatch) -> None:
    """Regression: the cap set by the platform admin must actually block."""
    mem = _Mem()
    _seed(mem, tenant_member_limit=2, user_limit=100, members=2)
    _wire(monkeypatch, mem)

    with pytest.raises(HTTPException) as exc:
        await product_edition.assert_member_capacity(MAIN_ID)
    assert exc.value.status_code == 403
    assert "2" in exc.value.detail


@pytest.mark.asyncio
async def test_below_cap_is_allowed(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem, tenant_member_limit=5, user_limit=100, members=4)
    _wire(monkeypatch, mem)

    await product_edition.assert_member_capacity(MAIN_ID)  # must not raise


@pytest.mark.asyncio
async def test_edition_default_still_enforced_without_override(monkeypatch) -> None:
    """The pre-existing behaviour (edition cap only) is unchanged."""
    mem = _Mem()
    _seed(mem, tenant_member_limit=None, user_limit=5, members=5)
    _wire(monkeypatch, mem)

    with pytest.raises(HTTPException) as exc:
        await product_edition.assert_member_capacity(MAIN_ID)
    assert exc.value.status_code == 403
    assert "5" in exc.value.detail


@pytest.mark.asyncio
async def test_clearing_the_cap_lifts_the_block(monkeypatch) -> None:
    """Explicitly clearing ``memberLimit`` must fall back, not stay capped."""
    mem = _Mem()
    _seed(mem, tenant_member_limit=None, user_limit=None, members=42)
    _wire(monkeypatch, mem)

    await product_edition.assert_member_capacity(MAIN_ID)  # must not raise


# ---------------------------------------------------------------------------
# Seat counting — the gate and the display endpoints must count the same way
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_members_counts_disabled_seats(monkeypatch) -> None:
    """Disabled members still occupy a seat.

    Disabling is reversible (``directory.py`` re-enables), it is not a removal.
    If the count skipped them, a tenant at its cap could disable someone to
    free a slot and re-enable later — the cap would be decorative. Deletion is
    a real ``delete_one``, so deleted members are simply absent.
    """
    mem = _Mem()
    _seed(mem, members=2)
    mem["end_users"].docs.append({"tenant_id": MAIN_ID, "name": "off", "status": "disabled"})
    _wire(monkeypatch, mem)

    assert await product_edition.count_members(MAIN_ID) == 3


# ---------------------------------------------------------------------------
# End-to-end: PATCH the tenant, then the gate reflects it (FR-022 "变更生效")
# ---------------------------------------------------------------------------


def test_patch_member_limit_then_gate_blocks(monkeypatch) -> None:
    """The full broken chain: set the cap through the service, see it enforced."""
    mem = _Mem()
    _seed(mem, tenant_member_limit=None, user_limit=None, members=3)
    _wire(monkeypatch, mem)

    view = asyncio.run(
        tenant_lifecycle.update_tenant(MAIN_ID, actor="platform-admin:root", member_limit=3)
    )
    assert view["memberLimit"] == 3, "the tenant view must report the new cap"

    with pytest.raises(HTTPException) as exc:
        asyncio.run(product_edition.assert_member_capacity(MAIN_ID))
    assert exc.value.status_code == 403, "the new cap must be enforced, not just displayed"


def test_patch_clearing_member_limit_then_gate_reopens(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem, tenant_member_limit=1, user_limit=None, members=3)
    _wire(monkeypatch, mem)

    with pytest.raises(HTTPException):
        asyncio.run(product_edition.assert_member_capacity(MAIN_ID))

    asyncio.run(
        tenant_lifecycle.update_tenant(MAIN_ID, actor="platform-admin:root", member_limit="null")
    )
    asyncio.run(product_edition.assert_member_capacity(MAIN_ID))  # must not raise
