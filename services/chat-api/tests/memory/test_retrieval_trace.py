"""Tests for 017 progressive retrieval + unified trace (FR-14 / FR-17)."""

from __future__ import annotations

from app.memory.retrieval import (
    memory_rag_candidates,
    progressive_memory_retrieval,
)
from app.memory.scope import Memory


def _mem(**kw) -> Memory:
    return Memory(scope="personal", owner_id="u1", memory_id="m1", **kw)


def test_progressive_default_l1() -> None:
    m = _mem(content="detail", l0_summary="l0", l1_overview="l1")
    cands, trace = progressive_memory_retrieval([m], viewer_id="u1", include_tier="L1")
    assert cands[0]["content"] == "l1"
    assert trace["candidates"][0]["tier_used"] == "L1"


def test_progressive_l0_and_l2() -> None:
    m = _mem(content="detail", l0_summary="l0", l1_overview="l1")
    c0, _ = progressive_memory_retrieval([m], viewer_id="u1", include_tier="L0")
    assert c0[0]["content"] == "l0"
    c2, _ = progressive_memory_retrieval([m], viewer_id="u1", include_tier="L2")
    assert c2[0]["content"] == "detail"


def test_progressive_trace_binds_session() -> None:
    m = _mem()
    _, trace = progressive_memory_retrieval(
        [m], viewer_id="u1", session_id="s1", turn_id="t1"
    )
    assert trace["session_id"] == "s1" and trace["turn_id"] == "t1"
    assert len(trace["candidates"]) == 1
    assert "trace_id" in trace


def test_progressive_excludes_invisible() -> None:
    m = _mem()
    cands, _ = progressive_memory_retrieval([m], viewer_id="u2")
    assert cands == []


def test_candidates_include_tier_legacy_l2() -> None:
    m = _mem(content="raw", l0_summary="s")
    c = memory_rag_candidates([m], viewer_id="u1", include_tier="L2")
    assert c[0]["content"] == "raw"
    assert c[0]["l0_summary"] == "s" and c[0]["tier"] == "L2"
    assert c[0]["addr"].startswith("mogo://memory/")
