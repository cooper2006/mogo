"""Tests for 017 session → memory sedimentation (FR-5 upgrade + FR-19).

D4: ``workspace`` scope is gone; a co-presence session without real project
context falls back to ``personal`` (``resolve_default_scope`` / N2).
"""

from __future__ import annotations

from app.memory.scope import Memory, resolve_default_scope
from app.memory.sediment import (
    NoopSessionSummarizer,
    build_session_memory,
    on_session_end,
    sediment_session_end,
)


def test_build_session_memory_fields() -> None:
    f = build_session_memory(
        session_id="s1", content="c", scope="project", owner_id="u1", tenant_id="t1"
    )
    assert f["source_session_id"] == "s1"
    assert f["source_type"] == "session"
    assert f["tierable"] is True
    assert f["content"] == "c"
    assert f["scope"] == "project"
    # N1: a project memory must carry the owner-disambiguating field.
    assert f["project_owner_id"] == ""


def test_build_session_memory_l0_from_snapshot() -> None:
    s = NoopSessionSummarizer()
    f = build_session_memory(
        session_id="s1",
        content="c",
        scope="personal",
        owner_id="u1",
        tenant_id="t1",
        summarizer=s,
        l0_summary="",
    )
    # NoopSessionSummarizer lifts the snapshot "summary"/content as L0.
    assert f["l0_summary"] != ""


def test_resolve_default_scope_multi_user_without_project_is_personal() -> None:
    """D2: co-presence alone never yields ``project`` without project context."""
    assert resolve_default_scope(multi_user_session=True) == "personal"
    assert resolve_default_scope(multi_user_session=True, has_project_context=False) == "personal"
    assert resolve_default_scope(has_project_context=True) == "project"


async def test_on_session_end_empty_snapshot_returns_none() -> None:
    class FakeStore:
        async def save(self, **kw):  # pragma: no cover - must not be called
            raise AssertionError("should not save on empty snapshot")

    assert await on_session_end(session_id="s", snapshot={}, store=FakeStore()) is None


async def test_on_session_end_saves_with_provenance() -> None:
    saved: dict = {}

    class FakeStore:
        async def save(self, **kw):
            saved.update(kw)
            return Memory(**kw)

    result = await on_session_end(
        session_id="s9",
        snapshot={"title": "T", "transcript": "body"},
        store=FakeStore(),
        owner_id="u1",
        tenant_id="t1",
    )
    assert result is not None
    assert saved["source_session_id"] == "s9"
    assert saved["source_type"] == "session"
    assert saved["content"] == "body"


async def test_sediment_session_end_saves_from_doc() -> None:
    saved: dict = {}

    class FakeStore:
        async def save(self, **kw):
            saved.update(kw)
            return Memory(**kw)

    doc = {
        "title": "Quarter planning",
        "summary": "Q4 roadmap",
        "content": "full transcript text",
        "multi_user": False,
    }
    result = await sediment_session_end(
        session_id="sess-1",
        session_doc=doc,
        store=FakeStore(),
        owner_id="u1",
        tenant_id="t1",
        emit_hook=False,
    )
    assert result is not None
    assert saved["source_session_id"] == "sess-1"
    assert saved["content"] == "full transcript text"
    assert saved["scope"] == "personal"  # single-user → personal (FR-3/FR-5)


async def test_sediment_session_end_group_session_falls_back_to_personal() -> None:
    """multi_user_session=True but no resolvable project context → personal."""
    saved: dict = {}

    class FakeStore:
        async def save(self, **kw):
            saved.update(kw)
            return Memory(**kw)

    doc = {"title": "Team sync", "co_presence": True, "content": "notes"}
    await sediment_session_end(
        session_id="sess-2",
        session_doc=doc,
        store=FakeStore(),
        owner_id="u1",
        tenant_id="t1",
        emit_hook=False,
    )
    assert saved["scope"] == "personal"


async def test_sediment_session_end_empty_doc_returns_none() -> None:
    class FakeStore:
        async def save(self, **kw):  # pragma: no cover - must not be called
            raise AssertionError("should not save on empty doc")

    assert (
        await sediment_session_end(
            session_id="sess-3",
            session_doc={},
            store=FakeStore(),
            owner_id="u1",
            tenant_id="t1",
            emit_hook=False,
        )
        is None
    )
