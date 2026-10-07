"""017 production wiring: memory HTTP endpoints (CRUD + promote).

Verifies create / list / delete / promote reach the 017 library over HTTP,
with server-side scope enforcement (FR-2) and ownership checks (FR-5).
Uses monkeypatched MemoryStore so no MongoDB is required.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.api.endpoints.memory import (
    create_memory,
    delete_memory,
    list_memories,
    promote_memory,
)
from app.memory.scope import Memory, MemoryScope


# ── helpers ────────────────────────────────────────────────────────────

class _FakeStore:
    """In-memory MemoryStore stand-in for endpoint tests."""

    def __init__(self) -> None:
        self._memories: dict[str, Memory] = {}

    async def save(self, **kwargs: Any) -> Memory:
        mem_id = kwargs.get("memory_id") or f"m-{len(self._memories) + 1}"
        m = Memory(
            memory_id=mem_id,
            content=kwargs["content"],
            scope=kwargs.get("scope", MemoryScope.PERSONAL.value),
            owner_id=kwargs["owner_id"],
            tenant_id=kwargs["tenant_id"],
            workspace_id=kwargs.get("workspace_id", ""),
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
                              is_workspace_member=False, top_n=20):
        return [
            m for (tid, _), m in self._memories.items()
            if tid == tenant_id and m.owner_id == viewer_id
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

    async def _fake_resolve(authorization):
        return {
            "user_id": "u1",
            "main_id": "t1",
            "role": "",
            "is_workspace_member": False,
        }

    monkeypatch.setattr("app.api.endpoints.auth._resolve_session_user", _fake_resolve)
    monkeypatch.setattr("app.api.endpoints.memory.MemoryStore", lambda: store)
    # The promote endpoint also imports MemoryStore locally
    monkeypatch.setattr("app.memory.store.MemoryStore", lambda: store)
    yield store


# ── tests ──────────────────────────────────────────────────────────────

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
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await create_memory(payload={"content": "   "}, authorization="Bearer test")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_memory_rejects_invalid_scope(fake_store):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await create_memory(
            payload={"content": "x", "scope": "bogus"}, authorization="Bearer test"
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_memory_rejects_oversized_non_tierable(monkeypatch):
    """FR-16: non-tierable content exceeding hard limit is rejected at the store level."""
    from fastapi import HTTPException
    from app.memory.store import MemoryTooLargeError

    async def _fake_resolve(authorization):
        return {"user_id": "u1", "main_id": "t1", "role": "", "is_workspace_member": False}

    async def _failing_save(**kwargs):
        if not kwargs.get("tierable", True) and len(kwargs["content"]) > 1_000_000:
            raise MemoryTooLargeError("too large")
        return Memory(memory_id="m1", content=kwargs["content"], owner_id="u1", tenant_id="t1")

    monkeypatch.setattr("app.api.endpoints.auth._resolve_session_user", _fake_resolve)
    monkeypatch.setattr("app.api.endpoints.memory.MemoryStore", lambda: type("S", (), {"save": _failing_save})())

    with pytest.raises(HTTPException) as exc:
        await create_memory(
            payload={"content": "x" * 2_000_000, "tierable": False},
            authorization="Bearer test",
        )
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_list_memories_returns_visible_only(fake_store):
    # Create two memories for the viewer
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

    result = await list_memories(
        authorization="Bearer test", scope="personal"
    )
    assert result["data"]["total"] == 1
    assert result["data"]["memories"][0]["content"] == "personal"


@pytest.mark.asyncio
async def test_delete_memory_owner_check(fake_store):
    from fastapi import HTTPException

    await create_memory(payload={"content": "to delete"}, authorization="Bearer test")
    result = await delete_memory("m-1", authorization="Bearer test")
    assert result["code"] == 0
    assert result["message"] == "deleted"

    # Second delete should 404
    with pytest.raises(HTTPException) as exc:
        await delete_memory("m-1", authorization="Bearer test")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_promote_memory_requires_admin(fake_store):
    from fastapi import HTTPException

    await create_memory(payload={"content": "promote me"}, authorization="Bearer test")

    # Non-admin role → 403 (empty role is not full_access_admin)
    with pytest.raises(HTTPException) as exc:
        await promote_memory("m-1", authorization="Bearer test")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_promote_memory_not_found(fake_store):
    from fastapi import HTTPException

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
    # source_session_id/source_type are stored but not echoed in the create response
    # (they are visible via list_memories)


@pytest.mark.asyncio
async def test_create_memory_rejects_org_scope_without_admin_role(fake_store):
    """R3 P1 / 017 FR-4: writing straight to ``org`` scope grants tenant-wide
    visibility, so it needs the same role as ``promote_to_org``."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await create_memory(
            payload={"content": "org wide", "scope": "org"},
            authorization="Bearer test",
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_memory_allows_org_scope_for_admin(monkeypatch):
    """A full-access admin may create an org-scoped memory directly."""
    store = _FakeStore()

    async def _admin_resolve(authorization):
        return {
            "user_id": "u1",
            "main_id": "t1",
            "role": "full_access_admin",
            "is_workspace_member": False,
        }

    monkeypatch.setattr("app.api.endpoints.auth._resolve_session_user", _admin_resolve)
    monkeypatch.setattr("app.api.endpoints.memory.MemoryStore", lambda: store)

    result = await create_memory(
        payload={"content": "org wide", "scope": "org"},
        authorization="Bearer test",
    )
    assert result["code"] == 0
    assert result["data"]["scope"] == "org"