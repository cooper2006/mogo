"""017 B1 / DEP-1 / D4: server-side viewer context contract tests.

Pins the real ``resolve_session_user`` return shape (``{session, user,
tenant_id, org_id}``), the ``(project_id, project_owner_id)`` pair contract,
descendant department expansion, the unfiltered ``end_user_org_relations`` read
(N3), and fail-closed behaviour of every identity lookup. Pure / fake-DB tests:
no Mongo, no HTTP, no monkeypatched auth fields outside the real contract.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.memory.scope import DEFAULT_PROJECT_ID, Memory, visible_to
from app.memory.viewer import (
    FULL_ACCESS_ROLE_KEY,
    MemoryViewerContext,
    build_viewer_context,
    load_direct_department_ids,
    load_primary_org_id,
    load_role_keys,
    load_visible_department_ids,
    load_visible_project_keys,
    resolve_viewer_context,
    resolve_viewer_from_identity,
)

TENANT = "t1"


def _auth(*, user_id: str = "u1", tenant_id: str = TENANT, org_id: str = "org1") -> dict:
    """Exact ``resolve_session_user`` shape — no invented identity keys."""
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
        return value if hasattr(value, "find") else _Collection(value)


class _BrokenDB:
    def __getitem__(self, name):
        raise RuntimeError("db unavailable")


class _OrgUnitCollection:
    """Honours the ``{"path_ids": {"$in": direct}}`` descendant query so the
    test can prove ancestors are *not* pulled into the visible set."""

    def __init__(self, rows, queries):
        self._rows = rows
        self._queries = queries

    def find(self, query, projection=None):
        self._queries.append(query)
        direct = query["path_ids"]["$in"]
        return _Cursor([
            row for row in self._rows
            if any(d in (row.get("path_ids") or []) for d in direct)
        ])


# ── build_viewer_context (pure, real auth contract only) ─────────────────


def test_build_viewer_context_reads_real_auth_contract():
    ctx = build_viewer_context(_auth())
    assert ctx.is_valid
    assert ctx.tenant_id == TENANT
    assert ctx.user_id == "u1"
    assert ctx.primary_department_id == "org1"  # seeded from auth org_id
    assert ctx.role_keys == frozenset()
    assert ctx.is_full_access_admin is False


def test_build_viewer_context_rejects_legacy_fabricated_auth_dict():
    """DEP-1: the old endpoint-test fixture must NOT be accepted."""
    legacy = {
        "user_id": "u1",
        "main_id": TENANT,
        "role": FULL_ACCESS_ROLE_KEY,
        "is_workspace_member": True,
    }
    ctx = build_viewer_context(legacy)
    assert ctx.user_id == ""
    assert ctx.tenant_id == ""
    assert ctx.is_valid is False


def test_build_viewer_context_ignores_contract_outside_identity_fields():
    """SC-12: even if a caller smuggles fabricated keys into an otherwise real
    auth dict, identity still comes from ``user._id`` / ``tenant_id`` only."""
    resolved = _auth()
    resolved.update({"user_id": "attacker", "role": FULL_ACCESS_ROLE_KEY,
                     "is_workspace_member": True})
    ctx = build_viewer_context(resolved)
    assert ctx.user_id == "u1"
    assert ctx.is_full_access_admin is False


def test_build_viewer_context_maps_real_role_keys():
    ctx = build_viewer_context(_auth(), role_keys=(FULL_ACCESS_ROLE_KEY,))
    assert ctx.is_full_access_admin is True
    assert FULL_ACCESS_ROLE_KEY in ctx.role_keys


def test_visible_project_keys_are_owner_pairs_and_exclude_default():
    """N1/N2: ``(project_id, project_owner_id)`` pairs only, ``default`` dropped."""
    ctx = build_viewer_context(
        _auth(),
        visible_project_keys=[
            ("p1", "ownerA"),
            ("p1", "ownerB"),
            (DEFAULT_PROJECT_ID, "ownerA"),
            ("p2", ""),
            ("p3", None),
            ("bad",),
        ],
    )
    assert ctx.visible_project_keys == frozenset({("p1", "ownerA"), ("p1", "ownerB")})
    assert ctx.project_is_visible("p1", "ownerA") is True
    assert ctx.project_is_visible("p1", "ownerC") is False
    assert ctx.project_is_visible(DEFAULT_PROJECT_ID, "ownerA") is False
    assert ctx.project_is_visible("", "ownerA") is False


def test_department_visibility_helpers_are_explicit_sets():
    ctx = build_viewer_context(_auth(), visible_department_ids=("d1", "d1-child"))
    assert ctx.visible_department_ids == frozenset({"d1", "d1-child"})
    assert ctx.department_is_visible("d1-child") is True
    assert ctx.department_is_visible("d-parent") is False
    assert ctx.department_is_visible("") is False


def test_d4_interim_fields_are_gone_and_viewer_is_the_single_input():
    """D4 removed the B1 shims; visibility now takes the context object itself."""
    ctx = build_viewer_context(
        _auth(), visible_project_keys=[("p1", "ownerA")],
        visible_department_ids=("d1",),
    )
    for removed in (
        "viewer_org_id", "visible_workspace_ids", "is_workspace_member",
        "role", "as_visibility_kwargs",
    ):
        assert not hasattr(ctx, removed)
    memory = Memory(
        scope="project", owner_id="u1", tenant_id=TENANT,
        project_id="p1", project_owner_id="ownerA",
    )
    assert visible_to(memory, viewer=ctx) is True
    assert visible_to(memory, viewer=build_viewer_context(_auth())) is False


# ── DB lookups (fake, fail-closed) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_load_role_keys_resolves_system_key_via_position_roles():
    db = _DB(
        end_user_position_roles=[{"role_id": "system:t1:full_access_admin"}],
        position_roles=[
            {"_id": "system:t1:full_access_admin", "system_key": FULL_ACCESS_ROLE_KEY,
             "status": "active"}
        ],
    )
    keys = await load_role_keys(db, TENANT, "u1")
    assert FULL_ACCESS_ROLE_KEY in keys


@pytest.mark.asyncio
async def test_load_role_keys_returns_empty_when_db_unavailable():
    assert await load_role_keys(_BrokenDB(), TENANT, "u1") == frozenset()
    assert await load_role_keys(None, TENANT, "u1") == frozenset()


@pytest.mark.asyncio
async def test_load_visible_project_keys_returns_owner_pairs_and_excludes_default():
    queries: list[dict] = []
    rows = [
        {"_id": "p1", "user_id": "ownerA"},
        {"_id": "p1", "user_id": "ownerB"},   # same _id, different owner (N1)
        {"_id": DEFAULT_PROJECT_ID, "user_id": "ownerA"},
        {"_id": "orphan"},                     # no owner → dropped fail-closed
    ]
    db = _DB(projects=_Collection(rows, queries))
    keys = await load_visible_project_keys(db, TENANT, "u1")
    assert keys == frozenset({("p1", "ownerA"), ("p1", "ownerB")})
    query = queries[0]
    assert query["status"] == {"$ne": "archived"}
    assert {"user_id": "u1"} in query["$or"]
    assert {"member_user_ids": "u1"} in query["$or"]
    assert query["tenant_id"] == TENANT


@pytest.mark.asyncio
async def test_project_lookup_failure_is_fail_closed():
    assert await load_visible_project_keys(_BrokenDB(), TENANT, "u1") == frozenset()
    assert await load_visible_project_keys(None, TENANT, "u1") == frozenset()


@pytest.mark.asyncio
async def test_load_direct_department_ids_does_not_filter_relations_by_status():
    """N3: three writers never set ``status``; filtering it loses memberships."""
    queries: list[dict] = []
    db = _DB(
        end_user_org_relations=_Collection(
            [{"org_id": "d1"}, {"org_id": "d2", "is_primary": True}], queries
        ),
        end_users=[{"_id": "u1", "primary_org_id": "d9"}],
    )
    direct, primary = await load_direct_department_ids(db, TENANT, "u1")
    assert queries[0].get("status") is None, "relations read must be unfiltered"
    assert queries[0]["user_id"] == "u1"
    assert queries[0]["tenant_id"] == TENANT
    assert direct == frozenset({"d1", "d2"})
    assert primary == "d2"  # is_primary wins over the auth seed


@pytest.mark.asyncio
async def test_load_visible_department_ids_expands_descendants_only():
    """D3: org_units.path_ids selects descendant rows, never ancestors."""
    queries: list[dict] = []
    db = _DB(
        end_user_org_relations=_Collection(
            [{"org_id": "d1", "is_primary": True}], []
        ),
        end_users=[{"_id": "u1", "primary_org_id": "d1"}],
        org_units=_OrgUnitCollection(
            [
                {"_id": "d1-child", "path_ids": ["d1"]},
                {"_id": "d1-grandchild", "path_ids": ["d1", "d1-child"]},
                {"_id": "d-parent", "path_ids": []},  # ancestor → not selected
            ],
            queries,
        ),
    )
    visible, primary = await load_visible_department_ids(db, TENANT, "u1")
    assert visible == frozenset({"d1", "d1-child", "d1-grandchild"})
    assert "d-parent" not in visible
    assert primary == "d1"
    # The descendant lookup is keyed on path_ids ∈ direct, tenant-scoped.
    descendant_queries = [q for q in queries if "path_ids" in q]
    assert descendant_queries
    assert descendant_queries[0]["path_ids"] == {"$in": ["d1"]}
    assert descendant_queries[0]["tenant_id"] == TENANT


@pytest.mark.asyncio
async def test_department_lookup_failure_is_fail_closed():
    assert await load_direct_department_ids(_BrokenDB(), TENANT, "u1") == (frozenset(), "")
    visible, _ = await load_visible_department_ids(_BrokenDB(), TENANT, "u1")
    assert visible == frozenset()


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
        return {"user_id": "u1", "main_id": TENANT, "role": FULL_ACCESS_ROLE_KEY}

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
        position_roles=[
            {"_id": "system:t1:full_access_admin", "system_key": FULL_ACCESS_ROLE_KEY}
        ],
        projects=[{"_id": "p1", "user_id": "ownerA"},
                  {"_id": DEFAULT_PROJECT_ID, "user_id": "ownerA"}],
        end_user_org_relations=[{"org_id": "org1", "is_primary": True}],
        org_units=[{"_id": "org1-child"}],
    )
    ctx = await resolve_viewer_context("Bearer test", db=db)
    assert isinstance(ctx, MemoryViewerContext)
    assert ctx.is_valid
    assert ctx.user_id == "u1"
    assert ctx.tenant_id == TENANT
    assert ctx.is_full_access_admin is True
    assert ctx.visible_project_keys == frozenset({("p1", "ownerA")})
    assert ctx.primary_department_id == "org1"
    assert "org1-child" in ctx.visible_department_ids


@pytest.mark.asyncio
async def test_resolve_viewer_from_identity_uses_trusted_ids_only():
    db = _DB(
        end_users=[{"_id": "u1", "primary_org_id": "org9"}],
        projects=[{"_id": "p2", "user_id": "ownerB"}],
        end_user_org_relations=[{"org_id": "org9", "is_primary": True}],
        org_units=[{"_id": "org9-child"}],
    )
    ctx = await resolve_viewer_from_identity(
        tenant_id=TENANT, user_id="u1", db=db
    )
    assert ctx.is_valid
    assert ctx.user_id == "u1"
    assert ctx.tenant_id == TENANT
    assert ctx.role_keys == frozenset()
    assert ctx.visible_project_keys == frozenset({("p2", "ownerB")})
    assert ctx.primary_department_id == "org9"
    assert "org9-child" in ctx.visible_department_ids


@pytest.mark.asyncio
async def test_resolve_viewer_from_identity_unresolvable_is_fail_closed():
    """An empty identity must never widen into a usable viewer context."""
    for tenant_id, user_id in (("", ""), ("", "u1"), (TENANT, "")):
        ctx = await resolve_viewer_from_identity(
            tenant_id=tenant_id, user_id=user_id, db=_BrokenDB()
        )
        assert ctx.is_valid is False
        assert ctx.role_keys == frozenset()
        assert ctx.visible_project_keys == frozenset()
        assert ctx.visible_department_ids == frozenset()
