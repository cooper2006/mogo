"""T035 user-side promotion-request endpoint (chat-api) integration tests.

Mirrors the fixture pattern in ``test_memory_endpoints.py``: the auth fixture uses
the real ``resolve_session_user`` return shape and the three server-side lookups
are pinned, so no live DB and no fabricated identity keys are involved.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from app.memory.scope import Memory, MemoryScope
from app.memory.viewer import FULL_ACCESS_ROLE_KEY, MemoryViewerContext


async def request_promote_memory(*args, **kwargs):
    from app.api.endpoints.memory import request_promote_memory as _fn

    return await _fn(*args, **kwargs)


async def promote_memory(*args, **kwargs):
    from app.api.endpoints.memory import promote_memory as _fn

    return await _fn(*args, **kwargs)


def _auth_payload(*, user_id: str = "u1", tenant_id: str = "t1", org_id: str = "d1") -> dict:
    return {
        "session": {"_id": "s1", "user_id": user_id, "tenant_id": tenant_id},
        "user": {"_id": user_id, "tenant_id": tenant_id, "status": "active", "primary_org_id": org_id},
        "tenant_id": tenant_id,
        "org_id": org_id,
    }


def _patch_auth(monkeypatch, *, user_id: str = "u1", tenant_id: str = "t1", org_id: str = "d1") -> None:
    async def _fake_resolve(authorization):
        return _auth_payload(user_id=user_id, tenant_id=tenant_id, org_id=org_id)

    monkeypatch.setattr("app.api.endpoints.auth._resolve_session_user", _fake_resolve)


def _patch_lookups(monkeypatch, *, role_keys=(), project_keys=(), department_ids=()):
    async def _roles(db, tenant_id, user_id):
        return frozenset(role_keys)

    async def _projects(db, tenant_id, user_id):
        return frozenset(project_keys)

    async def _departments(db, tenant_id, user_id, *, fallback_primary_org_id=""):
        ids = set(department_ids)
        primary = fallback_primary_org_id
        if primary:
            ids.add(primary)
        return frozenset(ids), primary

    monkeypatch.setattr("app.memory.viewer.load_role_keys", _roles)
    monkeypatch.setattr("app.memory.viewer.load_visible_project_keys", _projects)
    monkeypatch.setattr("app.memory.viewer.load_visible_department_ids", _departments)


class _FakeStore:
    """Persistent in-memory MemoryStore stand-in (mirrors test_memory_endpoints)."""

    def __init__(self) -> None:
        self._memories: dict[tuple[str, str], Memory] = {}
        self.last_update_fields: dict[str, Any] = {}

    async def save(self, **kwargs: Any) -> Memory:
        mem_id = kwargs.get("memory_id") or f"m-{len(self._memories) + 1}"
        m = Memory(
            memory_id=mem_id,
            content=kwargs["content"],
            scope=kwargs.get("scope", MemoryScope.PERSONAL.value),
            owner_id=kwargs["owner_id"],
            tenant_id=kwargs["tenant_id"],
            project_id=kwargs.get("project_id", ""),
            project_owner_id=kwargs.get("project_owner_id", ""),
            department_id=kwargs.get("department_id", ""),
            l0_summary=kwargs.get("l0_summary", ""),
            l1_overview=kwargs.get("l1_overview", ""),
            l2_raw=kwargs.get("l2_raw", kwargs["content"]),
            tierable=kwargs.get("tierable", True),
            source_session_id=kwargs.get("source_session_id", ""),
            source_type=kwargs.get("source_type", ""),
        )
        self._memories[(m.tenant_id, m.memory_id)] = m
        return m

    async def list_for_viewer(self, *, viewer, top_n=20):
        from app.memory.scope import visible_to

        return [
            m for (tid, _), m in self._memories.items()
            if tid == viewer.tenant_id and visible_to(m, viewer=viewer)
        ][:top_n]

    async def update_fields(self, *, tenant_id, memory_id, **fields):
        self.last_update_fields = dict(fields)
        m = self._memories.get((tenant_id, memory_id))
        if m is None:
            return False
        for key, value in fields.items():
            if hasattr(m, key):
                setattr(m, key, value)
        return True

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
def env(monkeypatch):
    store = _FakeStore()
    _patch_auth(monkeypatch)
    _patch_lookups(monkeypatch, department_ids=("d1",))
    monkeypatch.setattr("app.memory.store.MemoryStore", lambda: store)
    return store


async def _create_personal(env):
    from app.api.endpoints.memory import create_memory

    return await create_memory(payload={"content": "my note"}, authorization="Bearer t")


@pytest.mark.asyncio
async def test_owner_can_request_promotion(env):
    m = await _create_personal(env)
    result = await request_promote_memory(
        m["data"]["memory_id"], payload={"department_id": "d1", "reason": "team wide"},
        authorization="Bearer t",
    )
    assert result["code"] == 0
    assert result["data"]["promotion_status"] == "pending"
    assert result["data"]["pending_department_id"] == "d1"
    # persisted on the store
    stored = env._memories[("t1", m["data"]["memory_id"])]
    assert stored.promotion_status == "pending"


@pytest.mark.asyncio
async def test_request_requires_owner(env, monkeypatch):
    m = await _create_personal(env)
    # switch the viewer to a different user: the memory is not visible to them, so
    # the endpoint fail-closes with 404 (not 403) — invisible == not found.
    _patch_auth(monkeypatch, user_id="u2", org_id="d1")
    _patch_lookups(monkeypatch, department_ids=("d1",))
    with pytest.raises(HTTPException) as exc:
        await request_promote_memory(
            m["data"]["memory_id"], payload={"department_id": "d1"}, authorization="Bearer t"
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_request_invalid_department_403(env):
    m = await _create_personal(env)
    with pytest.raises(HTTPException) as exc:
        await request_promote_memory(
            m["data"]["memory_id"], payload={"department_id": "d9"}, authorization="Bearer t"
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_direct_promote_still_requires_admin(env, monkeypatch):
    m = await _create_personal(env)
    # no full_access_admin role -> 403 even via direct promote
    with pytest.raises(HTTPException) as exc:
        await promote_memory(m["data"]["memory_id"], authorization="Bearer t")
    assert exc.value.status_code == 403

    # with the role, direct promote works and records status approved
    _patch_lookups(monkeypatch, role_keys=(FULL_ACCESS_ROLE_KEY,), department_ids=("d1",))
    result = await promote_memory(
        m["data"]["memory_id"], payload=None, department_id="d1", authorization="Bearer t"
    )
    assert result["code"] == 0
    stored = env._memories[("t1", m["data"]["memory_id"])]
    assert stored.scope == MemoryScope.DEPARTMENT.value
    assert stored.promotion_status == "approved"
