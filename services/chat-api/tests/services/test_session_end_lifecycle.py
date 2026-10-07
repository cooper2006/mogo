"""Tests for 002 ``end_session`` — the real 009 SessionEnd carrier (P1-2).

Before this, the only terminal session operation was ``delete_session``, so the
009 → 017 sedimentation fired on delete instead of on a normal session end.
These tests pin the new lifecycle semantics: end is idempotent, persists
``ended_at``, and reaches the 017 memory write through the 009 dispatcher.
"""

from __future__ import annotations

import pytest

from app.memory.scope import Memory
from app.services import session_persistence_service as sps


class _FakeCursor:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        return self

    async def to_list(self, length=None):
        return list(self._rows)[: (length or len(self._rows))]


class _FakeCollection:
    def __init__(self, docs: list) -> None:
        self._docs = docs
        self.updates: list = []
        self.inserts: list = []

    def find(self, query: dict) -> _FakeCursor:
        return _FakeCursor([d for d in self._docs if _match(d, query)])

    async def find_one(self, query: dict):
        for d in self._docs:
            if _match(d, query):
                return d
        return None

    async def update_one(self, query: dict, update: dict, upsert: bool = False):
        self.updates.append((query, update))
        for d in self._docs:
            if _match(d, query):
                d.update(update.get("$set", {}))
                break
        return type("R", (), {"matched_count": 1, "modified_count": 1})()

    async def insert_one(self, doc: dict):
        self.inserts.append(doc)
        return type("R", (), {"inserted_id": "x"})()

    async def delete_one(self, q):
        return type("R", (), {"deleted_count": 1})()

    async def delete_many(self, q):
        return type("R", (), {"deleted_count": 0})()

    async def count_documents(self, q):
        return 0


def _match(doc: dict, query: dict) -> bool:
    for key, cond in query.items():
        if key == "$or":
            if not any(_match(doc, s) for s in cond):
                return False
            continue
        if key == "$and":
            if not all(_match(doc, s) for s in cond):
                return False
            continue
        val = doc.get(key)
        if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
            for op, expect in cond.items():
                if op == "$in" and val not in expect:
                    return False
                if op == "$ne" and val == expect:
                    return False
                if op == "$exists" and bool(expect) != (key in doc):
                    return False
        elif str(val) != str(cond):
            return False
    return True


class _FakeDb(dict):
    def __getitem__(self, name: str):
        if name not in self:
            self[name] = _FakeCollection([])
        return super().__getitem__(name)

    def __getattr__(self, name: str):
        return self[name]


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeDb()
    monkeypatch.setattr(sps, "get_db", lambda: db)
    monkeypatch.setattr("app.core.tenant.add_main_scope", lambda q, _m=None: q)
    monkeypatch.setattr("app.core.tenant.resolve_main_id", lambda t: t)
    return db


@pytest.fixture(autouse=True)
def _clean_hook_registry():
    from app.dsh_runtime.hooks.dispatcher import clear_subscribers
    from app.memory.sediment import reset_sedimentation_ledger

    clear_subscribers()
    reset_sedimentation_ledger()
    yield
    clear_subscribers()
    reset_sedimentation_ledger()


def _seed_session(db) -> None:
    db["chat_sessions"] = _FakeCollection(
        [
            {
                "_id": "507f1f77bcf86cd799439011",
                "user_id": "u1",
                "main_id": "t1",
                "title": "Planning",
                "summary": "roadmap",
                "content": "the full transcript",
                "message_count": 4,
                "multi_user": False,
            }
        ]
    )


async def test_end_session_persists_ended_at(fake_db) -> None:
    _seed_session(fake_db)
    doc = await sps.session_persistence_service.end_session(
        session_id="507f1f77bcf86cd799439011", user_id="u1", main_id="t1", reason="user_ended"
    )
    assert doc["ended_at"] is not None
    assert doc["end_reason"] == "user_ended"
    stored = fake_db["chat_sessions"]._docs[0]
    assert stored["ended_at"] is not None


async def test_end_session_sediments_via_dispatcher(fake_db) -> None:
    """The core P1-2 regression: ending a session must write a memory."""
    _seed_session(fake_db)
    written: dict = {}

    class _Store:
        async def save(self, **kw):
            written.update(kw)
            return Memory(**kw)

    # Replace the store the service hands to the subscriber.
    import app.memory.store as store_mod

    orig = store_mod.MemoryStore
    store_mod.MemoryStore = _Store
    try:
        await sps.session_persistence_service.end_session(
            session_id="507f1f77bcf86cd799439011", user_id="u1", main_id="t1"
        )
    finally:
        store_mod.MemoryStore = orig

    assert written.get("source_session_id") == "507f1f77bcf86cd799439011"
    assert written.get("source_type") == "session"
    assert written.get("content") == "the full transcript"


async def test_end_session_is_idempotent(fake_db) -> None:
    _seed_session(fake_db)
    svc = sps.session_persistence_service
    first = await svc.end_session(session_id="507f1f77bcf86cd799439011", user_id="u1", main_id="t1")
    second = await svc.end_session(session_id="507f1f77bcf86cd799439011", user_id="u1", main_id="t1")
    assert first["ended_at"] == second["ended_at"]
    # Only one update should have been issued (the second call short-circuits).
    assert len(fake_db["chat_sessions"].updates) == 1


async def test_end_session_missing_raises_lookup(fake_db) -> None:
    fake_db["chat_sessions"] = _FakeCollection([])
    with pytest.raises(LookupError):
        await sps.session_persistence_service.end_session(
            session_id="507f1f77bcf86cd799439011", user_id="u1", main_id="t1"
        )


async def test_end_session_invalid_id_raises_value(fake_db) -> None:
    with pytest.raises(ValueError):
        await sps.session_persistence_service.end_session(
            session_id="not-an-oid", user_id="u1", main_id="t1"
        )


async def test_end_session_survives_subscriber_failure(fake_db) -> None:
    """A broken hook consumer must not roll back the state change."""
    _seed_session(fake_db)

    from app.dsh_runtime.hooks.dispatcher import subscribe
    from app.dsh_runtime.hooks.registry import SESSION_END

    def boom(payload):
        raise RuntimeError("consumer down")

    subscribe(SESSION_END, boom)
    doc = await sps.session_persistence_service.end_session(
        session_id="507f1f77bcf86cd799439011", user_id="u1", main_id="t1"
    )
    assert doc["ended_at"] is not None
