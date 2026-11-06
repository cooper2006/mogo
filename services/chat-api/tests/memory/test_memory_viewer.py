"""017 B1 / DEP-1: server-side viewer context contract tests.

Pins the real ``resolve_session_user`` return shape and the fail-closed
behaviour of every identity lookup.  These are pure / fake-DB tests: no Mongo,
no HTTP, no monkeypatched auth fields.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.memory.viewer import (
    DEFAULT_PROJECT_ID,
    FULL_ACCESS_ROLE_KEY,
    build_viewer_context,
    load_primary_org_id,
    load_role_keys,
    load_visible_workspace_ids,
    resolve_viewer_context,
    resolve_viewer_from_identity,
)


TENANT = "t1"


def _auth(*, user_id="u1", tenant_id=TENANT, org_id="org1"):
    return {
        "session": {"_id": "s1", "user_id": user_id, "tenant_id": tenant_id},
        "user": {
            "_id": user_id,
            "tenant_id": tenant_id,
            "status": "active",
            "primary_org_id": org_id,
        },
        "tenant_id": tenant_id,
        "org_id": org_id,
    }


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, length=None):
        return self._rows[:length] if length else list(self._rows)


class _Collection:
    def __init__(self, rows, queries=None):
        self._rows = rows
        self._queries = queries

    def find(self, query, projection=None):
        if self._queries is not None:
            self._queries.append(query)
        return _Cursor(self._rows)

    async def find_one(self, query):
        return self._rows[0] if self._rows else None


class _DB:
    def __init__(self, **collections):
        self._collections = collections

    def __getitem__(self, name):
        if name not in self._collections:
            return _Collection([])
        value = self._collections[name]
        return value if isinstance(value, _Collection) else _Collection(value)


class _BrokenDB:
    def __getitem__(self, name):
        raise RuntimeError("db unavailable")


# ── build_viewer_context (pure) ────────────────────────────────────────


def test_build_viewer_context_reads_real_auth_contract():
    ctx = build_viewer_context(_auth())
    assert ctx.is_valid
    assert ctx.tenant_id == TENANT
    assert ctx.user_id == "u1"
    assert ctx.viewer_org_id == "org1"


def test_build_viewer_context_rejects_legacy_fabricated_auth_dict():
    """DEP-1: the old endpoint-test fixture must NOT be accepted."""
    legacy = {
        "user_id": "u1",
        "main_id": "t1",
        "role": FULL_ACCESS_ROLE_KEY,
        "is_workspace_member": True,
    }
    ctx = build_viewer_context(legacy)
    assert ctx.user_id == ""
    # Fail-closed: a missing tenant stays empty. We deliberately do NOT call
    # resolve_tenant_id("") here, which would silently turn an unresolvable
    # identity into the default tenant.
    assert ctx.tenant_id == ""
    assert ctx.is_valid is False


def test_build_viewer_context_does_not_grant_admin_without_role_bindings():
    ctx = build_viewer_context(_auth())
    assert ctx.role == ""
    assert ctx.is_full_access_admin is False
    assert ctx.is_workspace_member is False


def test_build_viewer_context_maps_real_role_keys():
    ctx = build_viewer_context(_auth(), role_keys=(FULL_ACCESS_ROLE_KEY,))
    assert ctx.is_full_access_admin
    assert ctx.role == FULL_ACCESS_ROLE_KEY


def test_build_viewer_context_excludes_default_project():
    """N2: 049's tenant-wide ``default`` row must never grant membership."""
    ctx = build_viewer_context(_auth(), visible_workspace_ids=("p1", DEFAULT_PROJECT_ID))
    assert ctx.visible_workspace_ids == frozenset({"p1"})
    assert ctx.is_workspace_member is True

    only_default = build_viewer_context(_auth(), visible_workspace_ids=(DEFAULT_PROJECT_ID,))
    assert only_default.is_workspace_member is False


def test_as_visibility_kwargs_carries_every_field():
    """One source of truth prevents the org-id omission found in RAG (G2)."""
    ctx = build_viewer_context(
        _auth(),
        role_keys=(FULL_ACCESS_ROLE_KEY,),
        visible_workspace_ids=("p1",),
    )
    assert ctx.as_visibility_kwargs() == {
        "viewer_id": "u1",
        "viewer_role": FULL_ACCESS_ROLE_KEY,
        "is_workspace_member": True,
        "viewer_org_id": "org1",
    }


# ── DB lookups (fake, fail-closed) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_load_role_keys_resolves_system_key_via_position_roles():
    db = _DB(
        end_user_position_roles=[{"role_id": "system:t1:full_access_admin"}],
        position_roles=[
            {"_id": "system:t1:full_access_admin", "system_key": FULL_ACCESS_ROLE_KEY, "status": "active"}
        ],
    )
    keys = await load_role_keys(db, TENANT, "u1")
    assert FULL_ACCESS_ROLE_KEY in keys


@pytest.mark.asyncio
async def test_load_role_keys_returns_empty_when_db_unavailable():
    assert await load_role_keys(_BrokenDB(), TENANT, "u1") == frozenset()
    assert await load_role_keys(None, TENANT, "u1") == frozenset()


@pytest.mark.asyncio
async def test_load_visible_workspace_ids_excludes_default_and_archived():
    queries: list[dict] = []
    rows = [
        {"_id": "p1"},
        {"_id": DEFAULT_PROJECT_ID},
    ]
    db = _DB(projects=_Collection(rows, queries))
    ids = await load_visible_workspace_ids(db, TENANT, "u1")
    assert ids == frozenset({"p1"})
    query = queries[0]
    assert query["status"] == {"$ne": "archived"}
    assert {"user_id": "u1"} in query["$or"]
    assert {"member_user_ids": "u1"} in query["$or"]
    assert query["tenant_id"] == TENANT


@pytest.mark.asyncio
async def test_project_lookup_failure_is_fail_closed():
    assert await load_visible_workspace_ids(_BrokenDB(), TENANT, "u1") == frozenset()


@pytest.mark.asyncio
async def test_load_primary_org_id_reads_end_users():
    db = _DB(end_users=[{"_id": "u1", "primary_org_id": "org7"}])
    assert await load_primary_org_id(db, TENANT, "u1") == "org7"


@pytest.mark.asyncio
async def test_load_primary_org_id_failure_is_fail_closed():
    assert await load_primary_org_id(_BrokenDB(), TENANT, "u1") == ""


# ── async entry points ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_viewer_context_rejects_fabricated_auth(monkeypatch):
    async def _legacy(authorization):
        return {"user_id": "u1", "main_id": "t1", "role": FULL_ACCESS_ROLE_KEY}

    monkeypatch.setattr("app.api.endpoints.auth._resolve_session_user", _legacy)
    with pytest.raises(HTTPException) as exc:
        await resolve_viewer_context("Bearer test")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_resolve_viewer_context_resolves_real_identity(monkeypatch):
    async def _real(authorization):
        return _auth()

    monkeypatch.setattr("app.api.endpoints.auth._resolve_session_user", _real)
    db = _DB(
        end_user_position_roles=[{"role_id": "system:t1:full_access_admin"}],
        position_roles=[{"_id": "system:t1:full_access_admin", "system_key": FULL_ACCESS_ROLE_KEY}],
        projects=[{"_id": "p1"}, {"_id": DEFAULT_PROJECT_ID}],
    )
    ctx = await resolve_viewer_context("Bearer test", db=db)
    assert ctx.user_id == "u1"
    assert ctx.tenant_id == TENANT
    assert ctx.viewer_org_id == "org1"  # from auth dict, no extra lookup
    assert ctx.is_full_access_admin
    assert ctx.visible_workspace_ids == frozenset({"p1"})


@pytest.mark.asyncio
async def test_resolve_viewer_from_identity_uses_trusted_ids_only():
    db = _DB(
        end_users=[{"_id": "u1", "primary_org_id": "org9"}],
        projects=[{"_id": "p2"}],
    )
    ctx = await resolve_viewer_from_identity(tenant_id=TENANT, user_id="u1", db=db)
    assert ctx.is_valid
    assert ctx.viewer_org_id == "org9"  # resolved from end_users, not a header
    assert ctx.is_workspace_member
    assert ctx.role == ""
