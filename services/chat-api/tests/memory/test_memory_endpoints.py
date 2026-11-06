"""017 production wiring: memory HTTP endpoints (CRUD + promote).

B1 / DEP-1: the auth fixture here uses the **real** return shape of
``app.services.end_user_session.resolve_session_user`` -> ``{session, user,
tenant_id, org_id}``.  The previous fixture invented ``user_id`` / ``role`` /
``is_workspace_member`` keys that the helper never returns; all 12 endpoint
tests were green while production resolved every caller to ``viewer_id=""``,
which let every logged-in user read everyone's personal memories
(``"" == ""``) and made workspace memories invisible.

Role / membership / org lookups are pinned with ``_patch_lookups`` instead of
being faked onto the auth dict, so the test exercises the real resolution
chain without needing a live MongoDB.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from app.api.endpoints.memory import (
    create_memory,
    delete_memory,
    list_memories,
    promote_memory,
)
from app.memory.scope import Memory, MemoryScope, visible_to


# ── helpers ────────────────────────────────────────────────────────────


def _auth_payload(*, user_id: str = "u1", tenant_id: str = "t1", org_id: str = "t1") -> dict:
    """Exact shape returned by ``resolve_session_user`` (end_user_session.py:137)."""
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


def _patch_auth(monkeypatch, *, user_id: str = "u1", tenant_id: str = "t1", org_id: str = "t1") -> None:
    async def _fake_resolve(authorization):
        return _auth_payload(user_id=user_id, tenant_id=tenant_id, org_id=org_id)

    monkeypatch.setattr("app.api.endpoints.auth._resolve_session_user", _fake_resolve)


def _patch_lookups(monkeypatch, *, role_keys=(), workspace_ids=(), org_id: str = "") -> None:
    """Pin the three server-side lookups; no live DB, no fabricated auth keys."""
    async def _roles(db, tenant_id, user_id):
        return frozenset(role_keys)

    async def _projects(db, tenant_id, user_id):
        return frozenset(workspace_ids)

    async def _org(db, tenant_id, user_id):
        return org_id

    monkeypatch.setattr("app.memory.viewer.load_role_keys", _roles)
    monkeypatch.setattr("app.memory.viewer.load_visible_workspace_ids", _projects)
    monkeypatch.setattr("app.memory.viewer.load_primary_org_id", _org)


class _FakeStore:
    """In-memory MemoryStore stand-in for endpoint tests."""

    def __init__(self) -> None:
        self._memories: dict[tuple[str, str], Memory] = {}

    async def save(self, **kwargs: Any) -> Memory:
        mem_id = kwargs.get("memory_id") or f"m-{len(self._memories) + 1}"
        m = Memory(
            memory_id=mem_id,
            content=kwargs["content"],
            scope=kwargs.get("scope", MemoryScope.PERSONAL.value),
            owner_id=kwargs["owner_id"],
            tenant_id=kwargs["tenant_id"],
            workspace_id=kwargs.get("workspace_id", ""),
            org_id=kwargs.get("org_id", ""),
            l0_summary=kwargs.get("l0_summary", ""),
            l1_overview=kwargs.get("l1_overview", ""),
            l2_raw=kwargs.get("l2_raw", kwargs["content"]),
            tierable=kwargs.get("tierable", True),
            source_session_id=kwargs.get("source_session_id", ""),
            source_type=kwargs.get("source_type", ""),
        )
        self._memories[(m.tenant_id, m.memory_id)] = m
        return m

    async def list_for_viewer(self, *, tenant_id, viewer_id, viewer_role="",
                              is_workspace_member=False, viewer_org_id="",
                              top_n=20):
        return [
            m for (tid, _), m in self._memories.items()
            if tid == tenant_id and visible_to(m, viewer_id=viewer_id,
                                               viewer_role=viewer_role,
                                               is_workspace_member=is_workspace_member,
                                               viewer_org_id=viewer_org_id)
        ][:top_n]

    async def get(self, *, tenant_id, memory_id):
        return self._memories.get((tenant_id, memory_id))

    async def delete(self, *, tenant_id, memory_id, owner_id):
        key = (tenant_id, memory_id)
        m = self._memories.get(key)
        if m and m.owner_id == owner_id:
            del self._memories[key]
            return True
        return False


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeStore()
    _patch_auth(monkeypatch)
    _patch_lookups(monkeypatch)
    # NOTE: create/list/delete/promote import MemoryStore *inside* the function,
    # so patching the endpoint module attribute has no effect -- patch the
    # source module instead (017 QA note, 2026-10-06).
    monkeypatch.setattr("app.memory.store.MemoryStore", lambda: store)
    yield store


# ── original endpoint coverage (now on the real auth contract) ──────────


@pytest.mark.asyncio
async def test_create_memory_returns_tiered_fields(fake_store):
    result = await create_memory(
        payload={"content": "hello world", "scope": "personal"},
        authorization="Bearer test",
    )
    assert result["code"] == 0
    assert result["data"]["content"] == "hello world"
    assert result["data"]["scope"] == "personal"
    assert "addr" in result["data"]
    assert result["data"]["addr"].startswith("mogo://memory/")


@pytest.mark.asyncio
async def test_create_memory_rejects_empty_content(fake_store):
    with pytest.raises(HTTPException) as exc:
        await create_memory(payload={"content": "   "}, authorization="Bearer test")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_memory_rejects_invalid_scope(fake_store):
    with pytest.raises(HTTPException) as exc:
        await create_memory(
            payload={"content": "x", "scope": "bogus"}, authorization="Bearer test"
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_memory_rejects_oversized_non_tierable(monkeypatch):
    """FR-16: non-tierable content exceeding hard limit → 413."""
    from app.memory.store import MemoryTooLargeError

    _patch_auth(monkeypatch)
    _patch_lookups(monkeypatch)

    class _FailingStore:
        async def save(self, **kwargs):
            if not kwargs.get("tierable", True) and len(kwargs["content"]) > 1_000_000:
                raise MemoryTooLargeError("too large")
            return Memory(memory_id="m1", content=kwargs["content"], owner_id="u1", tenant_id="t1")

    monkeypatch.setattr("app.memory.store.MemoryStore", lambda: _FailingStore())

    with pytest.raises(HTTPException) as exc:
        await create_memory(
            payload={"content": "x" * 2_000_000, "tierable": False},
            authorization="Bearer test",
        )
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_list_memories_returns_visible_only(fake_store):
    await create_memory(payload={"content": "first"}, authorization="Bearer test")
    await create_memory(payload={"content": "second"}, authorization="Bearer test")

    result = await list_memories(authorization="Bearer test")
    assert result["code"] == 0
    assert result["data"]["total"] == 2
    contents = [m["content"] for m in result["data"]["memories"]]
    assert "first" in contents
    assert "second" in contents


@pytest.mark.asyncio
async def test_list_memories_scope_filter(fake_store):
    await create_memory(
        payload={"content": "personal", "scope": "personal"},
        authorization="Bearer test",
    )
    await create_memory(
        payload={"content": "workspace", "scope": "workspace"},
        authorization="Bearer test",
    )

    result = await list_memories(authorization="Bearer test", scope="personal")
    assert result["data"]["total"] == 1
    assert result["data"]["memories"][0]["content"] == "personal"


@pytest.mark.asyncio
async def test_delete_memory_owner_check(fake_store):
    await create_memory(payload={"content": "to delete"}, authorization="Bearer test")
    result = await delete_memory("m-1", authorization="Bearer test")
    assert result["code"] == 0
    assert result["message"] == "deleted"

    with pytest.raises(HTTPException) as exc:
        await delete_memory("m-1", authorization="Bearer test")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_promote_memory_requires_admin(fake_store):
    await create_memory(payload={"content": "promote me"}, authorization="Bearer test")

    # No 006 role assigned → role resolved to "" → 403.
    with pytest.raises(HTTPException) as exc:
        await promote_memory("m-1", authorization="Bearer test")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_promote_memory_not_found(fake_store):
    with pytest.raises(HTTPException) as exc:
        await promote_memory("nonexistent", authorization="Bearer test")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_memory_with_tier_fields(fake_store):
    result = await create_memory(
        payload={
            "content": "tiered content",
            "l0_summary": "L0 summary",
            "l1_overview": "L1 overview",
            "tierable": True,
            "source_session_id": "s1",
            "source_type": "session",
        },
        authorization="Bearer test",
    )
    assert result["code"] == 0
    assert result["data"]["l0_summary"] == "L0 summary"
    assert result["data"]["l1_overview"] == "L1 overview"
    assert result["data"]["tierable"] is True


@pytest.mark.asyncio
async def test_create_memory_rejects_org_scope_without_admin_role(fake_store):
    """FR-4: writing straight to org scope needs the 006 admin role."""
    with pytest.raises(HTTPException) as exc:
        await create_memory(
            payload={"content": "org wide", "scope": "org"},
            authorization="Bearer test",
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_memory_allows_org_scope_for_admin(fake_store, monkeypatch):
    """Role comes from 006 role bindings, never from the auth dict."""
    _patch_lookups(monkeypatch, role_keys=("full_access_admin",))
    result = await create_memory(
        payload={"content": "org wide", "scope": "org"},
        authorization="Bearer test",
    )
    assert result["code"] == 0
    assert result["data"]["scope"] == "org"


# ── B1 / P0 regressions ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_memory_persists_real_owner_id(fake_store):
    """P0: owner_id used to be "" because user_id was read off the auth dict."""
    await create_memory(payload={"content": "alice private"}, authorization="Bearer alice")
    stored = fake_store._memories[("t1", "m-1")]
    assert stored.owner_id == "u1"
    assert stored.tenant_id == "t1"


@pytest.mark.asyncio
async def test_personal_memory_not_visible_to_other_user(fake_store, monkeypatch):
    """P0 regression: the exact tenant-wide leak from the 2026-11-05 audit."""
    await create_memory(payload={"content": "alice private"}, authorization="Bearer alice")

    _patch_auth(monkeypatch, user_id="u2")
    result = await list_memories(authorization="Bearer bob")
    assert result["data"]["total"] == 0
    assert result["data"]["memories"] == []


@pytest.mark.asyncio
async def test_legacy_auth_fixture_is_rejected(fake_store, monkeypatch):
    """DEP-1: a fabricated auth dict must fail closed, not grant admin rights."""
    async def _legacy_resolve(authorization):
        return {
            "user_id": "u1",
            "main_id": "t1",
            "role": "full_access_admin",
            "is_workspace_member": True,
        }

    monkeypatch.setattr("app.api.endpoints.auth._resolve_session_user", _legacy_resolve)
    with pytest.raises(HTTPException) as exc:
        await create_memory(payload={"content": "x"}, authorization="Bearer test")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_workspace_memory_visible_to_real_project_member(fake_store, monkeypatch):
    """Membership is resolved from 049 projects, not from a client-supplied bool."""
    _patch_lookups(monkeypatch, workspace_ids=("p1",))
    await create_memory(
        payload={"content": "team note", "scope": "workspace", "workspace_id": "p1"},
        authorization="Bearer test",
    )
    result = await list_memories(authorization="Bearer test")
    assert result["data"]["total"] == 1
    assert result["data"]["memories"][0]["content"] == "team note"


@pytest.mark.asyncio
async def test_org_memory_is_bounded_by_org(fake_store, monkeypatch):
    """R-04: org visibility is bounded by org id, not by tenant."""
    _patch_lookups(monkeypatch, role_keys=("full_access_admin",))
    await create_memory(
        payload={"content": "org note", "scope": "org"}, authorization="Bearer alice"
    )
    assert fake_store._memories[("t1", "m-1")].org_id == "t1"

    _patch_lookups(monkeypatch)
    _patch_auth(monkeypatch, user_id="u2", org_id="t1")
    assert (await list_memories(authorization="Bearer bob"))["data"]["total"] == 1

    _patch_auth(monkeypatch, user_id="u3", org_id="org2")
    assert (await list_memories(authorization="Bearer carol"))["data"]["total"] == 0


def test_visible_to_rejects_empty_viewer_and_empty_owner():
    """Defence in depth: legacy rows with owner_id="" stay unreadable."""
    legacy = Memory(content="legacy", scope="personal", owner_id="", memory_id="m0")
    assert visible_to(legacy, viewer_id="") is False
    assert visible_to(legacy, viewer_id="u1") is False
    # Existing 006 semantics: a full-access admin may read any scope in the
    # tenant. P0 was about *ordinary* users; legacy owner_id="" rows are
    # quarantined by the migration archive step, not by changing admin rights.
    assert visible_to(legacy, viewer_id="u1", viewer_role="full_access_admin") is True


@pytest.mark.asyncio
async def test_promote_memory_allows_admin(fake_store, monkeypatch):
    """FR-4: a real 006 admin role makes promotion work (previously always 403)."""
    await create_memory(payload={"content": "promote me"}, authorization="Bearer test")
    _patch_lookups(monkeypatch, role_keys=("full_access_admin",))
    result = await promote_memory("m-1", authorization="Bearer test")
    assert result["code"] == 0
    assert result["data"]["scope"] == "org"
    assert fake_store._memories[("t1", "m-1")].scope == "org"
