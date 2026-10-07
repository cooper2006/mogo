"""Tests for 021 unified context address space (first tenant = memory).

These exercise the router + memory adapter + delegated visibility + trace. The
``MemoryStore`` is monkeypatched so no MongoDB is required.
"""

from __future__ import annotations

import pytest

from app.context_space.router import ContextNotFoundError, ContextVisibilityError, resolve_memory
from app.context_space.visibility import ViewerContext
from app.memory.scope import Memory


def _memory() -> Memory:
    return Memory(
        scope="personal",
        owner_id="u1",
        memory_id="m1",
        content="raw detail",
        l0_summary="one line",
        l1_overview="key points",
    )


@pytest.fixture
def fake_store(monkeypatch):
    mem = _memory()

    class Store:
        async def get(self, *, tenant_id, memory_id):
            return mem

    # The adapter binds the class via ``from app.memory.store import MemoryStore``,
    # so patch it where it is referenced.
    monkeypatch.setattr("app.context_space.adapters.memory.MemoryStore", Store)
    yield


async def test_resolve_visible_l1(fake_store) -> None:
    res = await resolve_memory(
        "mogo://memory/personal/u1/m1/L1", tenant_id="t1", viewer_id="u1"
    )
    assert res["resolved"]["content"] == "key points"
    assert res["resolved"]["meta"]["source_type"] == ""
    assert len(res["trace"]["candidates"]) == 1
    assert res["trace"]["candidates"][0]["tier_used"] == "L1"


async def test_resolve_default_tier_is_l0(fake_store) -> None:
    res = await resolve_memory("mogo://memory/personal/u1/m1", tenant_id="t1", viewer_id="u1")
    assert res["resolved"]["content"] == "one line"


async def test_resolve_invisible_raises(fake_store) -> None:
    with pytest.raises(ContextVisibilityError):
        await resolve_memory("mogo://memory/personal/u1/m1", tenant_id="t1", viewer_id="u2")


async def test_resolve_not_found(monkeypatch) -> None:
    class Store:
        async def get(self, *, tenant_id, memory_id):
            return None

    monkeypatch.setattr("app.context_space.adapters.memory.MemoryStore", Store)
    with pytest.raises(ContextNotFoundError):
        await resolve_memory(
            "mogo://memory/personal/u1/mx", tenant_id="t1", viewer_id="u1"
        )


async def test_unknown_root_raises() -> None:
    with pytest.raises(ValueError):
        await resolve_memory("mogo://resource/x/y", tenant_id="t1", viewer_id="u1")


def test_viewer_context_dataclass() -> None:
    ctx = ViewerContext(viewer_id="u1", is_workspace_member=True)
    assert ctx.viewer_role == ""
