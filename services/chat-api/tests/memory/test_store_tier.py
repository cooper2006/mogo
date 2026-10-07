"""Tests for 017 store tier persistence + FR-16 hard-limit reject.

Requires the chat-api environment (imports ``app.core.config`` → pydantic-settings).
"""

from __future__ import annotations

import pytest

from app.memory.store import MemoryStore, MemoryTooLargeError, _row_to_memory


async def test_save_non_tierable_exceeding_hard_limit_rejected() -> None:
    store = MemoryStore()  # db-None path; hard-limit check runs before DB access.
    with pytest.raises(MemoryTooLargeError):
        await store.save(content="x" * 2_000_000, tierable=False, owner_id="u1", tenant_id="t1")


async def test_save_tierable_huge_accepted() -> None:
    store = MemoryStore()
    m = await store.save(content="y" * 2_000_000, owner_id="u1", tenant_id="t1")
    assert m.tierable is True
    assert m.l2_raw == m.content


def test_row_to_memory_reads_tier_fields() -> None:
    m = _row_to_memory({
        "memory_id": "m1",
        "content": "c",
        "scope": "personal",
        "l0_summary": "s",
        "l1_overview": "o",
        "l2_raw": "c",
        "tierable": True,
        "source_session_id": "s1",
        "source_type": "session",
    })
    assert m.l0_summary == "s"
    assert m.l1_overview == "o"
    assert m.l2_raw == "c"
    assert m.source_session_id == "s1"
    assert m.source_type == "session"
