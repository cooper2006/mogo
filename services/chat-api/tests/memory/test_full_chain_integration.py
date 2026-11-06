"""T025 full-chain integration test (017).

Exercises the whole 017 pipeline in one sequence, using an in-memory persistent
store (no live DB):

    write (create) → sediment (session → memory) → RAG retrieval →
    address round-trip → promotion request → admin approve → visibility re-check

Plus an invalidation leg that confirms RAG drops an ``invalidated`` memory.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.memory import promotion as promotion_sm
from app.memory.address import MemoryAddress, parse_memory_uri
from app.memory.scope import (
    Memory,
    MemoryScope,
    PROMOTION_STATUS_APPROVED,
    PROMOTION_STATUS_PENDING,
    visible_to,
)
from app.memory.sediment import on_session_end
from app.memory.viewer import MemoryViewerContext
from app.memory.retrieval import memory_rag_candidates


class _FakeStore:
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

    async def update_fields(self, *, tenant_id, memory_id, **fields):
        m = self._memories.get((tenant_id, memory_id))
        if m is None:
            return False
        for key, value in fields.items():
            if hasattr(m, key):
                setattr(m, key, value)
        return True

    async def get(self, *, tenant_id, memory_id):
        return self._memories.get((tenant_id, memory_id))


def _owner_viewer() -> MemoryViewerContext:
    return MemoryViewerContext(
        tenant_id="t1",
        user_id="u1",
        visible_department_ids=frozenset({"d1"}),
        primary_department_id="d1",
        visible_project_keys=frozenset({("p1", "ownerA")}),
    )


def _admin_viewer() -> MemoryViewerContext:
    return MemoryViewerContext(
        tenant_id="t1",
        user_id="admin",
        role_keys=frozenset({"full_access_admin"}),
        visible_department_ids=frozenset({"d1"}),
        primary_department_id="d1",
        visible_project_keys=frozenset({("p1", "ownerA")}),
    )


def _outsider_viewer() -> MemoryViewerContext:
    # Sees neither u1's personal memory nor the p1/ownerA project.
    return MemoryViewerContext(
        tenant_id="t1",
        user_id="u9",
        visible_department_ids=frozenset({"d9"}),
        primary_department_id="d9",
        visible_project_keys=frozenset(),
    )


@pytest.mark.asyncio
async def test_full_chain_write_sediment_rag_address_promote():
    store = _FakeStore()

    # 1) WRITE — create a personal memory directly via the store.
    m1 = await store.save(
        content="personal onboarding note",
        owner_id="u1",
        tenant_id="t1",
        scope="personal",
    )

    # 2) SEDIMENT — a 002 session ends and sediments into a project memory.
    m2 = await on_session_end(
        session_id="sess-1",
        snapshot={"title": "Quarterly OKRs", "content": "ship three-scope memory"},
        store=store,
        owner_id="u1",
        tenant_id="t1",
        project_id="p1",
        project_owner_id="ownerA",
    )
    assert m2 is not None
    assert m2.scope == MemoryScope.PROJECT.value
    assert m2.project_owner_id == "ownerA"
    assert m2.source_type == "session"  # sedimentation provenance

    viewer = _owner_viewer()

    # 3) RAG — both the personal and the project memory are retrievable.
    candidates = memory_rag_candidates([m1, m2], viewer=viewer, top_n=10)
    returned_ids = {c["memory_id"] for c in candidates}
    assert m1.memory_id in returned_ids
    assert m2.memory_id in returned_ids

    # 4) ADDRESS — the project memory resolves to a browsable, parseable URI.
    uri = m2.addr("L0")
    assert uri.startswith("mogo://memory/project/")
    parsed = parse_memory_uri(uri)
    assert isinstance(parsed, MemoryAddress)
    assert parsed.scope == "project"
    assert parsed.memory_id == m2.memory_id
    assert parsed.uri() == uri  # round-trip

    # 5) PROMOTION REQUEST — owner opens a pending request into d1.
    promotion_sm.request_promotion(m1, viewer=viewer, department_id="d1", reason="team wide")
    assert m1.promotion_status == PROMOTION_STATUS_PENDING

    # 6) ADMIN APPROVE — promotes to department and resolves the request.
    admin = _admin_viewer()
    promotion_sm.approve_promotion(m1, viewer=admin, department_id="d1")
    assert m1.scope == MemoryScope.DEPARTMENT.value
    assert m1.department_id == "d1"
    assert m1.promotion_status == PROMOTION_STATUS_APPROVED
    # persist the state on the store
    await store.update_fields(
        tenant_id="t1",
        memory_id=m1.memory_id,
        scope=m1.scope,
        department_id=m1.department_id,
        promotion_status=m1.promotion_status,
    )

    # 7) VISIBILITY — the promoted memory is now readable inside d1 by the owner,
    #    and invisible to an outsider (fail-closed).
    assert visible_to(m1, viewer) is True
    assert visible_to(m1, _outsider_viewer()) is False
    # the project sedimented memory is still visible to its project member
    assert visible_to(m2, viewer) is True


@pytest.mark.asyncio
async def test_full_chain_invalidated_excluded_from_rag():
    store = _FakeStore()
    m1 = await store.save(content="keep", owner_id="u1", tenant_id="t1", scope="personal")
    m2 = await store.save(content="offboarded", owner_id="u1", tenant_id="t1", scope="personal")
    m2.invalidated = True
    m2.invalidated_reason = "owner_offboarded"

    viewer = _owner_viewer()
    candidates = memory_rag_candidates([m1, m2], viewer=viewer, top_n=10)
    returned_ids = {c["memory_id"] for c in candidates}
    assert m1.memory_id in returned_ids
    assert m2.memory_id not in returned_ids  # invalidated dropped from RAG
