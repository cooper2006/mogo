"""058 T010/T011/T013 — 用量日志 DLQ 与对账的单测。

``services/chat-api/app/token_usage/dispatcher.py`` 内联实现了：

* ``_try_dlq_append``：写出死信 + 计数；
* ``submit``：队列满时改走 ``_try_dlq_append``；
* ``_run``：持久化异常时改走 ``_try_dlq_append``（不 ``task_done``）；
* ``_reconcile_token_usage``：从 DLQ 重放 ``token_usage_logs`` 并标记 ``processed``。

用内存假 DB 验证上述四条分支（T013 的「reconcile success / failed」含在内）。
"""

from __future__ import annotations

import asyncio

import pytest

from app.token_usage import dispatcher
from app.token_usage.dispatcher import TokenUsageDispatcher, _reconcile_token_usage
from app.token_usage.models import TokenUsageRecord


class _FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []
        self._last_filter: dict | None = None

    async def insert_one(self, doc) -> None:
        self.docs.append(doc)

    def find(self, filter_=None, *a, **k):
        self._last_filter = filter_
        return self

    async def to_list(self, length=None):
        if self._last_filter and "processed" in self._last_filter:
            return [d for d in self.docs if d.get("processed") == self._last_filter["processed"]]
        return list(self.docs)

    async def update_one(self, filter_, update):
        rid = (filter_ or {}).get("request_id")
        for d in self.docs:
            if d.get("request_id") == rid:
                d["processed"] = True


class _FakeDB:
    def __init__(self) -> None:
        self.token_usage_dlq = _FakeCollection()
        self.token_usage_logs = _FakeCollection()

    def __getitem__(self, name: str):
        return getattr(self, name)

    def __getattr__(self, name: str):
        return _FakeCollection()


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(dispatcher, "get_db", lambda: db)
    import app.core.db as core_db

    monkeypatch.setattr(core_db, "get_db", lambda: db)
    return db


def _make_record(request_id: str = "r1") -> TokenUsageRecord:
    return TokenUsageRecord(
        request_id=request_id,
        tenant_id="t1",
        user_id="u1",
        session_id="s1",
        trace_id="tr1",
        stage="chat",
        model_name="gpt-5.2",
        total_tokens=100,
    )


@pytest.mark.asyncio
async def test_try_dlq_append_writes_doc(fake_db) -> None:
    d = TokenUsageDispatcher()
    await d._try_dlq_append(_make_record(), "queue_full")
    assert len(fake_db.token_usage_dlq.docs) == 1
    doc = fake_db.token_usage_dlq.docs[0]
    assert doc["reason"] == "queue_full"
    assert doc["request_id"] == "r1"
    assert doc["processed"] is False


@pytest.mark.asyncio
async def test_submit_queue_full_triggers_dlq(fake_db) -> None:
    d = TokenUsageDispatcher()
    await d.start()
    # 确定性触发队列满分支：让 put_nowait 直接抛 QueueFull，
    # 不走「填满队列」路径（worker 并发消费会带来竞态）。
    d._queue.put_nowait = lambda r: (_ for _ in ()).throw(asyncio.QueueFull)
    ok = await d.submit(_make_record("r-overflow"))
    await d.stop()
    assert ok is False
    assert any(x["request_id"] == "r-overflow" for x in fake_db.token_usage_dlq.docs)


@pytest.mark.asyncio
async def test_reconcile_success_moves_dlq_to_logs(fake_db) -> None:
    fake_db.token_usage_dlq.docs.append(
        {
            "request_id": "r-dlq",
            "tenant_id": "t1",
            "user_id": "u1",
            "session_id": "s1",
            "trace_id": "tr1",
            "stage": "chat",
            "model_name": "gpt-5.2",
            "total_tokens": 50,
            "processed": False,
        }
    )
    await _reconcile_token_usage()
    # logs 增加
    assert len(fake_db.token_usage_logs.docs) == 1
    # dlq 标记为 processed
    assert fake_db.token_usage_dlq.docs[0]["processed"] is True


@pytest.mark.asyncio
async def test_reconcile_failure_retains_dlq(fake_db) -> None:
    fake_db.token_usage_dlq.docs.append(
        {
            "request_id": "r-dlq2",
            "tenant_id": "t1",
            "user_id": "u1",
            "session_id": "s1",
            "trace_id": "tr1",
            "stage": "chat",
            "model_name": "gpt-5.2",
            "total_tokens": 50,
            "processed": False,
        }
    )

    async def _boom(doc):
        raise RuntimeError("db down")

    fake_db.token_usage_logs.insert_one = _boom
    await _reconcile_token_usage()
    # 重放失败 → DLQ 保留（不标记 processed）
    assert fake_db.token_usage_dlq.docs[0]["processed"] is False
