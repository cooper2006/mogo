"""Tests for 021 unified context address space (first tenant = memory).

These exercise the router + memory adapter + delegated visibility + trace. The
``MemoryStore`` is monkeypatched so no MongoDB is required.

D4: identity is a server-built ``MemoryViewerContext`` threaded through as
``viewer=``; the retired ``workspace`` / ``org`` address segments fail closed.
"""

from __future__ import annotations

import pytest

from app.context_space.router import ContextNotFoundError, ContextVisibilityError, resolve_memory
from app.memory.scope import Memory
from app.memory.viewer import build_viewer_context


def _auth_payload(*, user_id="u1", tenant_id="t1", org_id=""):
    """Real ``resolve_session_user`` shape (B1 / DEP-1, no invented keys)."""
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


def _viewer(*, user_id="u1", tenant_id="t1", org_id=""):
    return build_viewer_context(_auth_payload(user_id=user_id, tenant_id=tenant_id, org_id=org_id))


def _memory() -> Memory:
    return Memory(
        scope="personal",
        owner_id="u1",
        tenant_id="t1",
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
            return mem if memory_id == mem.memory_id else None

    # The adapter binds the class via ``from app.memory.store import MemoryStore``,
    # so patch it where it is referenced.
    monkeypatch.setattr("app.context_space.adapters.memory.MemoryStore", Store)
    yield


async def test_resolve_visible_l1(fake_store) -> None:
    res = await resolve_memory(
        "mogo://memory/personal/u1/m1/L1", viewer=_viewer()
    )
    assert res["resolved"]["content"] == "key points"
    assert res["resolved"]["meta"]["source_type"] == ""
    assert len(res["trace"]["candidates"]) == 1
    assert res["trace"]["candidates"][0]["tier_used"] == "L1"


async def test_resolve_default_tier_is_l0(fake_store) -> None:
    res = await resolve_memory(
        "mogo://memory/personal/u1/m1", viewer=_viewer()
    )
    assert res["resolved"]["content"] == "one line"


async def test_resolve_invisible_raises(fake_store) -> None:
    with pytest.raises(ContextVisibilityError) as exc:
        await resolve_memory(
            "mogo://memory/personal/u1/m1", viewer=_viewer(user_id="u2")
        )
    # A denied address must not echo the stored content back in its error.
    assert "raw detail" not in str(exc.value)
    assert "key points" not in str(exc.value)


@pytest.mark.parametrize("legacy_scope", ["workspace", "org"])
async def test_resolve_legacy_scope_address_fails_closed(fake_store, legacy_scope) -> None:
    """D4: retired address segments are rejected before any store lookup and
    never leak stored content."""
    with pytest.raises(ValueError) as exc:
        await resolve_memory(
            f"mogo://memory/{legacy_scope}/u1/m1/L1",
            viewer=_viewer(),
        )
    assert "raw detail" not in str(exc.value)
    assert "one line" not in str(exc.value)


async def test_resolve_project_and_department_addresses_parse(fake_store) -> None:
    """project / department segments are legal (404 here, never ValueError)."""
    for scope in ("project", "department"):
        with pytest.raises(ContextNotFoundError):
            await resolve_memory(
                f"mogo://memory/{scope}/u1/missing/L0",
                viewer=_viewer(),
            )


async def test_resolve_not_found(monkeypatch) -> None:
    class Store:
        async def get(self, *, tenant_id, memory_id):
            return None

    monkeypatch.setattr("app.context_space.adapters.memory.MemoryStore", Store)
    with pytest.raises(ContextNotFoundError):
        await resolve_memory(
            "mogo://memory/personal/u1/mx", viewer=_viewer()
        )


async def test_unknown_root_raises() -> None:
    with pytest.raises(ValueError):
        await resolve_memory(
            "mogo://resource/x/y", viewer=_viewer()
        )


def test_viewer_context_is_built_from_real_auth_contract() -> None:
    ctx = _viewer(org_id="d1")
    assert ctx.is_valid
    assert ctx.user_id == "u1"
    assert ctx.tenant_id == "t1"
    assert ctx.primary_department_id == "d1"
    assert ctx.is_full_access_admin is False
    # D4 removed the B1 interim shims.
    for removed in ("viewer_org_id", "visible_workspace_ids", "is_workspace_member",
                    "role", "as_visibility_kwargs"):
        assert not hasattr(ctx, removed)
