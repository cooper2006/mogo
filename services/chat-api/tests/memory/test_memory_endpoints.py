"""017 production wiring: memory HTTP endpoints (CRUD + promote).

B1 / DEP-1: the auth fixture here uses the **real** return shape of
``app.services.end_user_session.resolve_session_user`` -> ``{session, user,
tenant_id, org_id}``.  The previous fixture invented ``user_id`` / ``role`` /
``is_workspace_member`` keys that the helper never returns; all 12 endpoint
tests were green while production resolved every caller to ``viewer_id=""``,
which let every logged-in user read everyone's personal memories
(``"" == ""``) and made workspace memories invisible.

D4: role / project / department lookups are pinned on the new ``load_*``
seam, and the store is driven by a single ``viewer=`` MemoryViewerContext.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from app.memory.scope import Memory, MemoryScope, visible_to
from app.memory.viewer import FULL_ACCESS_ROLE_KEY, MemoryViewerContext


# The endpoint module is being rewritten by the parallel production task.
# Import lazily so an intermediate ``app.api.endpoints.memory`` cannot break
# test collection; the assertions below always describe the D4 target state.
async def create_memory(*args, **kwargs):
    from app.api.endpoints.memory import create_memory as _fn

    return await _fn(*args, **kwargs)


async def list_memories(*args, **kwargs):
    from app.api.endpoints.memory import list_memories as _fn

    return await _fn(*args, **kwargs)


async def delete_memory(*args, **kwargs):
    from app.api.endpoints.memory import delete_memory as _fn

    return await _fn(*args, **kwargs)


async def promote_memory(*args, **kwargs):
    from app.api.endpoints.memory import promote_memory as _fn

    return await _fn(*args, **kwargs)


async def update_memory(*args, **kwargs):
    from app.api.endpoints.memory import update_memory as _fn

    return await _fn(*args, **kwargs)


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


def _patch_lookups(
    monkeypatch,
    *,
    role_keys=(),
    project_keys=(),
    department_ids=(),
) -> None:
    """Pin the three server-side lookups; no live DB, no fabricated auth keys.

    ``load_visible_department_ids`` returns ``(visible_ids, primary)`` just like
    the real seam; the auth ``org_id`` seed is always included as the primary
    department so promote / department writes have a visible target.
    """
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
    """In-memory MemoryStore stand-in for endpoint tests."""

    def __init__(self) -> None:
        self._memories: dict[tuple[str, str], Memory] = {}
        self.last_list_kwargs: dict[str, Any] = {}
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
        self.last_list_kwargs = {"viewer": viewer, "top_n": top_n}
        tenant_id = viewer.tenant_id
        return [
            m for (tid, _), m in self._memories.items()
            if tid == tenant_id and visible_to(m, viewer=viewer)
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
    # D4: a single server-built viewer object is threaded through.
    assert isinstance(fake_store.last_list_kwargs["viewer"], MemoryViewerContext)
    assert "viewer_id" not in fake_store.last_list_kwargs


@pytest.mark.asyncio
async def test_list_memories_scope_filter(fake_store, monkeypatch):
    # A project write requires the viewer to actually hold the (id, owner) key.
    _patch_lookups(monkeypatch, project_keys=(("p1", "ownerA"),))
    await create_memory(
        payload={"content": "personal", "scope": "personal"},
        authorization="Bearer test",
    )
    await create_memory(
        payload={
            "content": "project", "scope": "project",
            "project_id": "p1", "project_owner_id": "ownerA",
        },
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

    # No 006 role assigned → not a full-access admin → 403.
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
async def test_create_memory_rejects_department_scope_without_admin_role(fake_store):
    """FR-4: writing straight to department scope needs the 006 admin role."""
    with pytest.raises(HTTPException) as exc:
        await create_memory(
            payload={"content": "dept wide", "scope": "department"},
            authorization="Bearer test",
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_memory_allows_department_scope_for_admin(fake_store, monkeypatch):
    """Role comes from 006 role bindings, never from the auth dict."""
    _patch_lookups(monkeypatch, role_keys=(FULL_ACCESS_ROLE_KEY,))
    result = await create_memory(
        payload={"content": "dept wide", "scope": "department"},
        authorization="Bearer test",
    )
    assert result["code"] == 0
    assert result["data"]["scope"] == "department"


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
    """P0 regression: alice's personal memory must stay invisible to bob."""
    await create_memory(payload={"content": "alice private"}, authorization="Bearer alice")

    _patch_auth(monkeypatch, user_id="u2")
    result = await list_memories(authorization="Bearer bob")
    assert result["data"]["total"] == 0
    assert result["data"]["memories"] == []


@pytest.mark.asyncio
async def test_legacy_auth_fixture_is_rejected(fake_store, monkeypatch):
    """DEP-1: a fabricated auth dict must fail closed (401), not grant admin."""
    async def _legacy_resolve(authorization):
        return {
            "user_id": "u1",
            "main_id": "t1",
            "role": FULL_ACCESS_ROLE_KEY,
            "is_workspace_member": True,
        }

    monkeypatch.setattr("app.api.endpoints.auth._resolve_session_user", _legacy_resolve)
    with pytest.raises(HTTPException) as exc:
        await create_memory(payload={"content": "x"}, authorization="Bearer test")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_project_memory_visible_to_real_project_member(fake_store, monkeypatch):
    """Project visibility is resolved from 049 projects as (id, owner) pairs."""
    _patch_lookups(monkeypatch, project_keys=(("p1", "ownerA"),))
    await create_memory(
        payload={
            "content": "team note", "scope": "project",
            "project_id": "p1", "project_owner_id": "ownerA",
        },
        authorization="Bearer test",
    )
    result = await list_memories(authorization="Bearer test")
    assert result["data"]["total"] == 1
    assert result["data"]["memories"][0]["content"] == "team note"


@pytest.mark.asyncio
async def test_department_memory_is_bounded_by_department(fake_store, monkeypatch):
    """R-04: department visibility is bounded by department id, not by tenant."""
    _patch_lookups(monkeypatch, role_keys=(FULL_ACCESS_ROLE_KEY,))
    await create_memory(
        payload={"content": "dept note", "scope": "department"},
        authorization="Bearer alice",
    )
    assert fake_store._memories[("t1", "m-1")].department_id == "t1"

    _patch_lookups(monkeypatch)
    _patch_auth(monkeypatch, user_id="u2", org_id="t1")
    assert (await list_memories(authorization="Bearer bob"))["data"]["total"] == 1

    _patch_auth(monkeypatch, user_id="u3", org_id="org2")
    assert (await list_memories(authorization="Bearer carol"))["data"]["total"] == 0


def test_visible_to_rejects_empty_viewer_and_empty_owner():
    """B1 P0 + B-7: legacy rows with owner_id="" stay unreadable, an
    unresolved viewer context is fail-closed, and **even a full-access admin
    cannot read a structurally incomplete record** (N1/N2 收紧后的新语义).

    B1 originally let the admin shortcut precede this check; B2 moved the
    structural integrity gate ahead of it so malformed rows can only be
    handled by the audited governance path / offline migration.
    """
    legacy = Memory(
        content="legacy", scope="personal", owner_id="", tenant_id="t1", memory_id="m0"
    )
    ordinary = MemoryViewerContext(tenant_id="t1", user_id="u1")
    admin = MemoryViewerContext(
        tenant_id="t1", user_id="u1", role_keys=frozenset({FULL_ACCESS_ROLE_KEY})
    )
    assert visible_to(legacy, viewer=MemoryViewerContext()) is False
    assert visible_to(legacy, viewer=ordinary) is False
    assert visible_to(legacy, viewer=admin) is False

    # Same gate for the N1/N2 project cases: admin must not resurrect them.
    for project_id, project_owner_id in (("", ""), ("p1", ""), ("default", "o1")):
        broken = Memory(
            content="legacy",
            scope="project",
            owner_id="u1",
            tenant_id="t1",
            memory_id="m1",
            project_id=project_id,
            project_owner_id=project_owner_id,
        )
        assert visible_to(broken, viewer=admin) is False

    # A well-formed record is still governable by the admin.
    valid = Memory(
        content="ok", scope="personal", owner_id="u2", tenant_id="t1", memory_id="m2"
    )
    assert visible_to(valid, viewer=admin) is True


@pytest.mark.asyncio
async def test_promote_memory_allows_admin(fake_store, monkeypatch):
    """FR-4: a real 006 admin role makes promotion to department work."""
    await create_memory(payload={"content": "promote me"}, authorization="Bearer test")
    _patch_lookups(monkeypatch, role_keys=(FULL_ACCESS_ROLE_KEY,))
    result = await promote_memory("m-1", authorization="Bearer test")
    assert result["code"] == 0
    assert result["data"]["scope"] == "department"
    assert fake_store._memories[("t1", "m-1")].scope == "department"


# ── T030 / B4 收口：通用 PATCH、promote body、list 分页筛选 ───────────────


@pytest.mark.asyncio
async def test_update_memory_success_returns_scope_echo(fake_store):
    """通用编辑返回更新后的记录，含 actual_scope / resolved_from / project_owner_id。"""
    await create_memory(
        payload={"content": "original", "l0_summary": "L0", "l1_overview": "L1"},
        authorization="Bearer test",
    )
    result = await update_memory(
        "m-1", {"content": "edited", "l1_overview": "new L1"}, authorization="Bearer test"
    )
    assert result["code"] == 0
    assert result["message"] == "updated"
    data = result["data"]
    assert data["content"] == "edited"
    assert data["l1_overview"] == "new L1"
    assert data["actual_scope"] == "personal"
    assert data["resolved_from"] == "default"
    assert data["project_owner_id"] == ""
    assert "addr" in data


@pytest.mark.asyncio
async def test_update_memory_invisible_returns_404(fake_store, monkeypatch):
    """不可见一律 404，且不改动、不泄露内容。"""
    await create_memory(payload={"content": "alice private"}, authorization="Bearer alice")
    _patch_auth(monkeypatch, user_id="u2")
    with pytest.raises(HTTPException) as exc:
        await update_memory("m-1", {"content": "hack"}, authorization="Bearer bob")
    assert exc.value.status_code == 404
    assert fake_store._memories[("t1", "m-1")].content == "alice private"


@pytest.mark.asyncio
async def test_update_memory_ignores_authorization_fields(fake_store):
    """授权字段客户端传值一律忽略；增量 $set 只携带内容类字段 + updated_at。"""
    await create_memory(payload={"content": "original"}, authorization="Bearer test")
    before = fake_store._memories[("t1", "m-1")]
    original = (
        before.scope, before.owner_id, before.tenant_id, before.project_id,
        before.project_owner_id, before.department_id,
    )
    result = await update_memory(
        "m-1",
        {
            "content": "edited",
            "scope": "department",
            "project_id": "evil",
            "project_owner_id": "evil",
            "department_id": "evil",
            "owner_id": "attacker",
            "tenant_id": "other",
        },
        authorization="Bearer test",
    )
    assert result["code"] == 0
    after = fake_store._memories[("t1", "m-1")]
    assert after.content == "edited"
    assert (
        after.scope, after.owner_id, after.tenant_id, after.project_id,
        after.project_owner_id, after.department_id,
    ) == original
    assert set(fake_store.last_update_fields) == {"content", "updated_at"}


@pytest.mark.asyncio
async def test_update_memory_incremental_set_preserves_tiers(fake_store):
    """update_fields 增量 $set 不清空 L0/L1/L2、provenance、archived、project_owner_id。"""
    await create_memory(
        payload={
            "content": "original", "l0_summary": "L0", "l1_overview": "L1",
            "source_session_id": "s1", "source_type": "session",
        },
        authorization="Bearer test",
    )
    stored = fake_store._memories[("t1", "m-1")]
    stored.project_owner_id = "ownerA"  # 模拟已有归属（不影响 personal 可见性）
    result = await update_memory("m-1", {"content": "edited"}, authorization="Bearer test")
    data = result["data"]
    assert data["l0_summary"] == "L0"
    assert data["l1_overview"] == "L1"
    assert data["tierable"] is True
    assert data["source_session_id"] == "s1"
    assert data["source_type"] == "session"
    assert data["resolved_from"] == "sediment"
    assert stored.archived is False
    assert stored.project_owner_id == "ownerA"
    assert set(fake_store.last_update_fields) == {"content", "updated_at"}


@pytest.mark.asyncio
async def test_update_memory_too_large_returns_413(monkeypatch):
    """MemoryTooLargeError（FR-16）→ 413，与 create 端点同款映射。"""
    from app.memory.store import MemoryTooLargeError

    _patch_auth(monkeypatch)
    _patch_lookups(monkeypatch)

    class _FailingStore:
        async def get(self, *, tenant_id, memory_id):
            return Memory(memory_id="m1", content="x", owner_id="u1", tenant_id=tenant_id)

        async def update_fields(self, *, tenant_id, memory_id, **fields):
            raise MemoryTooLargeError("too large")

    monkeypatch.setattr("app.memory.store.MemoryStore", lambda: _FailingStore())
    with pytest.raises(HTTPException) as exc:
        await update_memory("m1", {"content": "x" * 2_000_000}, authorization="Bearer test")
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_promote_memory_body_department_id_takes_precedence(fake_store, monkeypatch):
    """promote 读 body.department_id（优先于 query / 主部门回落）。"""
    await create_memory(payload={"content": "promote me"}, authorization="Bearer test")
    _patch_lookups(monkeypatch, role_keys=(FULL_ACCESS_ROLE_KEY,), department_ids=("d2",))
    result = await promote_memory(
        "m-1",
        {"target_scope": "department", "department_id": "d2", "reason": "share"},
        authorization="Bearer test",
    )
    assert result["code"] == 0
    assert result["data"]["department_id"] == "d2"
    assert fake_store._memories[("t1", "m-1")].department_id == "d2"


@pytest.mark.asyncio
async def test_promote_memory_query_department_id_fallback(fake_store, monkeypatch):
    """无 body 时回落 query.department_id（兼容只认 query 的旧调用方）。"""
    await create_memory(payload={"content": "promote me"}, authorization="Bearer test")
    _patch_lookups(monkeypatch, role_keys=(FULL_ACCESS_ROLE_KEY,), department_ids=("d3",))
    result = await promote_memory(
        "m-1", None, authorization="Bearer test", department_id="d3"
    )
    assert result["data"]["department_id"] == "d3"


@pytest.mark.parametrize("bad", ["org", "workspace"])
@pytest.mark.asyncio
async def test_promote_memory_legacy_target_scope_returns_400(fake_store, bad):
    """target_scope 旧值 → 400 scope_invalid（D4 无兼容层）。"""
    await create_memory(payload={"content": "promote me"}, authorization="Bearer test")
    with pytest.raises(HTTPException) as exc:
        await promote_memory(
            "m-1", {"target_scope": bad, "department_id": "t1"}, authorization="Bearer test"
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == "scope_invalid"


@pytest.mark.asyncio
async def test_list_memories_page_size_and_next_cursor(fake_store):
    """page / page_size 分页 + cursor 简单偏移，next_cursor 仅在还有下一页时给出。"""
    for i in range(5):
        await create_memory(payload={"content": f"note-{i}"}, authorization="Bearer test")

    page1 = (await list_memories(authorization="Bearer test", page=1, page_size=2))["data"]
    assert page1["page"] == 1 and page1["page_size"] == 2
    assert page1["total"] == 5
    assert len(page1["items"]) == 2
    assert page1["items"] == page1["memories"]
    assert page1["next_cursor"] == "2"

    page2 = (await list_memories(authorization="Bearer test", cursor="2", page_size=2))["data"]
    assert len(page2["items"]) == 2
    assert page2["next_cursor"] == "4"

    page3 = (await list_memories(authorization="Bearer test", cursor="4", page_size=2))["data"]
    assert len(page3["items"]) == 1
    assert page3["next_cursor"] == ""


@pytest.mark.asyncio
async def test_list_memories_response_contract_keys(fake_store):
    """data 含 items/memories/total/page/page_size/next_cursor，逐条回显 scope 字段。"""
    await create_memory(payload={"content": "x"}, authorization="Bearer test")
    data = (await list_memories(authorization="Bearer test"))["data"]
    assert {"items", "memories", "total", "page", "page_size", "next_cursor"} <= set(data)
    assert data["items"][0]["actual_scope"] == "personal"
    assert data["items"][0]["resolved_from"] == "default"
    assert data["items"][0]["project_owner_id"] == ""


@pytest.mark.asyncio
async def test_list_memories_keyword_filter_case_insensitive(fake_store):
    """keyword 对 content / l0_summary / l1_overview 大小写不敏感包含匹配。"""
    await create_memory(
        payload={"content": "Hello World", "l0_summary": "L0"}, authorization="Bearer test"
    )
    await create_memory(payload={"content": "unrelated"}, authorization="Bearer test")

    hit = (await list_memories(authorization="Bearer test", keyword="hello"))["data"]
    assert hit["total"] == 1
    assert hit["items"][0]["content"] == "Hello World"
    upper = (await list_memories(authorization="Bearer test", keyword="WORLD"))["data"]
    assert upper["total"] == 1


@pytest.mark.asyncio
async def test_list_memories_status_filter(fake_store):
    """status 支持 active / archived；归档记录被 visible_to 挡在可见集合外。"""
    await create_memory(payload={"content": "active one"}, authorization="Bearer test")
    await create_memory(payload={"content": "archived one"}, authorization="Bearer test")
    fake_store._memories[("t1", "m-2")].archived = True

    active = (await list_memories(authorization="Bearer test", status="active"))["data"]
    assert active["total"] == 1
    assert active["items"][0]["content"] == "active one"
    archived = (await list_memories(authorization="Bearer test", status="archived"))["data"]
    assert archived["total"] == 0


@pytest.mark.asyncio
async def test_list_memories_limit_alias(fake_store):
    """limit 作为 page_size 别名，兼容既有 user-web 调用方。"""
    for i in range(4):
        await create_memory(payload={"content": f"n{i}"}, authorization="Bearer test")
    data = (await list_memories(authorization="Bearer test", limit=2))["data"]
    assert data["page_size"] == 2
    assert len(data["items"]) == 2
    assert data["total"] == 4


@pytest.mark.parametrize("bad", ["workspace", "org", "WORKSPACE"])
@pytest.mark.asyncio
async def test_list_memories_legacy_scope_returns_400(fake_store, bad):
    """list 的旧 scope 查询值 → 400 scope_invalid。"""
    with pytest.raises(HTTPException) as exc:
        await list_memories(authorization="Bearer test", scope=bad)
    assert exc.value.status_code == 400
    assert exc.value.detail == "scope_invalid"
