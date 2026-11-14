"""Tests for 017 store tier persistence + FR-16 hard-limit reject.

Requires the chat-api environment (imports ``app.core.config`` → pydantic-settings).
"""

from __future__ import annotations

import pytest

import app.memory.store as _store_mod
from app.memory.store import MemoryStore, MemoryTooLargeError, _row_to_memory


async def test_save_non_tierable_exceeding_hard_limit_rejected() -> None:
    store = MemoryStore()  # db-None path; hard-limit check runs before DB access.
    with pytest.raises(MemoryTooLargeError):
        await store.save(content="x" * 2_000_000, tierable=False, owner_id="u1", tenant_id="t1")


class _FakeCollection:
    """In-memory stand-in for the ``memories`` Mongo collection (replace_one upsert)."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def replace_one(self, filter: dict, doc: dict, upsert: bool = False) -> None:
        key = {k: doc.get(k) for k in filter}
        for i, row in enumerate(self.rows):
            if all(row.get(k) == v for k, v in key.items()):
                self.rows[i] = doc
                return
        if upsert:
            self.rows.append(dict(doc))


class _FakeDb:
    """``db[COLLECTION]`` → fake collection; lets ``save`` persist without a real pool."""

    def __getitem__(self, name: str) -> _FakeCollection:
        return _FakeCollection()


@pytest.mark.asyncio
async def test_save_tierable_huge_accepted(monkeypatch) -> None:
    # PanWeiDB 隔离网模式下 conftest 的 stub 池对真查询显式 raise（conftest.py:138），
    # 本测试要覆盖「tierable 路径落盘」契约 → 注入 fake db，不依赖真实池。
    fake_db = _FakeDb()
    monkeypatch.setattr(_store_mod, "get_db", lambda: fake_db)
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
