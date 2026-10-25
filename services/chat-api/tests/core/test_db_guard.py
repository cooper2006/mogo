"""026 T014/T015/T016/T017/T019/T022 — 数据库性能守护测试。"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.core.db_guard import (
    DEFAULT_MAX_TIME_MS,
    ErrorRateWindow,
    GuardedCollection,
    PoolLeakTracker,
    SlowQueryRegistry,
    explain_and_store,
    guarded_query,
    persist_pool_utilization,
    persist_slow_queries,
    pool_kwargs,
    pool_utilization_snapshot,
)


class TestPoolLeakTracker:
    def test_checkout_checkin_no_leak(self) -> None:
        tracker = PoolLeakTracker()
        now = 1000.0
        tracker.checkout("tok-1", now=now)
        assert tracker.borrowed_count() == 1
        tracker.checkin("tok-1")
        assert tracker.borrowed_count() == 0
        assert tracker.leaked(now=now) == []

    def test_leak_detected_after_warn(self) -> None:
        tracker = PoolLeakTracker(warn_ms=90000)
        tracker.checkout("tok-1", now=1000.0)
        # 91 秒后仍未归还 → 泄漏
        assert tracker.leaked(now=1091.0) == ["tok-1"]

    def test_under_warn_no_leak(self) -> None:
        tracker = PoolLeakTracker(warn_ms=90000)
        tracker.checkout("tok-1", now=1000.0)
        assert tracker.leaked(now=1089.0) == []


class TestPoolKwargs:
    def test_defaults(self) -> None:
        kw = pool_kwargs(settings=None)
        assert kw["maxPoolSize"] == 100
        assert kw["minPoolSize"] == 10
        assert kw["maxIdleTimeMS"] == 30000

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MONGODB_MAX_POOL_SIZE", "50")
        monkeypatch.setenv("MONGODB_MIN_POOL_SIZE", "5")
        monkeypatch.setenv("MONGODB_MAX_IDLE_MS", "60000")
        kw = pool_kwargs(settings=None)
        assert kw["maxPoolSize"] == 50
        assert kw["minPoolSize"] == 5
        assert kw["maxIdleTimeMS"] == 60000


class TestSlowQueryRegistry:
    def test_under_threshold_not_recorded(self) -> None:
        reg = SlowQueryRegistry(threshold_ms=100.0)
        assert reg.record("find", "chat_messages", 50.0) is False
        assert reg.records == []

    def test_over_threshold_recorded(self) -> None:
        reg = SlowQueryRegistry(threshold_ms=100.0)
        assert reg.record("aggregate", "memories", 350.0, tenant_id="t1") is True
        assert len(reg.records) == 1
        assert reg.records[0]["command"] == "aggregate"
        assert reg.records[0]["duration_ms"] == 350.0
        assert reg.records[0]["tenant_id"] == "t1"

    def test_drain(self) -> None:
        reg = SlowQueryRegistry(threshold_ms=1.0)
        reg.record("find", "c", 5.0)
        assert len(reg.drain()) == 1
        assert reg.drain() == []


class TestErrorRateWindow:
    def test_empty_rate_zero(self) -> None:
        w = ErrorRateWindow()
        assert w.rate(now=1000.0) == 0.0
        assert w.tripped(now=1000.0) is False

    def test_all_ok(self) -> None:
        w = ErrorRateWindow()
        for i in range(10):
            w.record(True, now=1000.0 + i)
        assert w.rate(now=1010.0) == 0.0

    def test_trips_above_50pct(self) -> None:
        w = ErrorRateWindow()
        # 7 失败 + 3 成功 = 70% 错误率
        for i in range(7):
            w.record(False, now=1000.0 + i)
        for i in range(3):
            w.record(True, now=1010.0 + i)
        assert w.rate(now=1020.0) == pytest.approx(0.7)
        assert w.tripped(now=1020.0) is True

    def test_window_evicts_old_events(self) -> None:
        w = ErrorRateWindow(window_seconds=30.0)
        w.record(False, now=1000.0)  # 30s 前失败
        w.record(True, now=1031.0)   # 窗口内成功
        assert w.rate(now=1032.0) == 0.0


class FakeCursor:
    def __init__(self, docs: list):
        self.docs = docs

    async def to_list(self, length: int = 100) -> list:
        return self.docs


class FakeCollection:
    def __init__(self, name: str = "c", find_docs: list | None = None):
        self.name = name
        self._find_docs = find_docs or []
        self.calls: list[dict] = []

    async def find(self, *args: dict, **kwargs) -> FakeCursor:
        self.calls.append({"op": "find", "args": args, "kwargs": kwargs})
        return FakeCursor(self._find_docs)

    async def find_one(self, *args, **kwargs):
        self.calls.append({"op": "find_one", "args": args, "kwargs": kwargs})
        return self._find_docs[0] if self._find_docs else None

    async def aggregate(self, *args, **kwargs):
        self.calls.append({"op": "aggregate", "args": args, "kwargs": kwargs})
        return FakeCursor(self._find_docs)

    async def count_documents(self, *args, **kwargs):
        self.calls.append({"op": "count_documents", "args": args, "kwargs": kwargs})
        return len(self._find_docs)


class TestGuardedCollection:
    async def test_find_sets_default_max_time_ms(self) -> None:
        col = FakeCollection()
        gc = GuardedCollection(col)
        await gc.find({"tenant_id": "t1"})
        assert col.calls[0]["kwargs"]["max_time_ms"] == DEFAULT_MAX_TIME_MS

    async def test_explicit_max_time_wins(self) -> None:
        col = FakeCollection()
        gc = GuardedCollection(col, default_max_time_ms=5000)
        await gc.find({"a": 1}, max_time_ms=800)
        assert col.calls[0]["kwargs"]["max_time_ms"] == 800

    async def test_slow_recorded(self) -> None:
        col = FakeCollection()
        slow = SlowQueryRegistry(threshold_ms=0.0)
        gc = GuardedCollection(col, slow_registry=slow)
        await gc.find({"a": 1})
        assert len(slow.records) == 1
        assert slow.records[0]["command"] == "find"
        assert slow.records[0]["namespace"] == "c"

    async def test_breaker_records_success(self) -> None:
        col = FakeCollection()
        breaker = ErrorRateWindow()
        gc = GuardedCollection(col, breaker=breaker)
        await gc.find({"a": 1})
        assert breaker.rate() == 0.0

    async def test_breaker_records_failure(self) -> None:
        class Boom(FakeCollection):
            async def find(self, *args, **kwargs):
                raise RuntimeError("boom")

        breaker = ErrorRateWindow()
        gc = GuardedCollection(Boom(), breaker=breaker)
        with pytest.raises(RuntimeError):
            await gc.find({"a": 1})
        assert breaker.rate() == 1.0

    async def test_leak_tracker_checkout_checkin(self) -> None:
        col = FakeCollection()
        leak = PoolLeakTracker()
        gc = GuardedCollection(col, leak_tracker=leak)
        await gc.find({"a": 1})
        assert leak.borrowed_count() == 0  # 完成后已归还


class TestGuardedQuery:
    async def test_circuit_open_raises(self) -> None:
        breaker = ErrorRateWindow()
        now = time.monotonic()
        for i in range(7):
            breaker.record(False, now=now + i * 0.1)

        async def op() -> str:
            return "ok"

        with pytest.raises(RuntimeError, match="circuit open"):
            await guarded_query(breaker, "find.memories", op())

    async def test_circuit_open_fallback(self) -> None:
        breaker = ErrorRateWindow()
        now = time.monotonic()
        for i in range(7):
            breaker.record(False, now=now + i * 0.1)

        async def op() -> str:
            return "ok"

        result = await guarded_query(breaker, "find.memories", op(), fallback="cached")
        assert result == "cached"

    async def test_normal_path(self) -> None:
        breaker = ErrorRateWindow()
        called = []

        async def op(v: int) -> int:
            called.append(v)
            return v

        result = await guarded_query(breaker, "op", op(42))
        assert result == 42
        assert called == [42]
        assert breaker.rate() == 0.0

    async def test_failure_recorded(self) -> None:
        breaker = ErrorRateWindow()

        async def op() -> None:
            raise ValueError("bad")

        with pytest.raises(ValueError):
            await guarded_query(breaker, "op", op())
        assert breaker.rate() == 1.0


class TestExplainAndStore:
    async def test_stores_plan(self) -> None:
        class FakeDB:
            def __init__(self):
                self.plans = []
                self._overrides = {}

            def __setitem__(self, name, obj):
                self._overrides[name] = obj

            def __getitem__(self, name: str):
                if name in self._overrides:
                    return self._overrides[name]
                if name == "query_plans":
                    return self._plans_col()
                return FakeCollection(name)

            def _plans_col(self):
                return self

            async def insert_one(self, doc):
                self.plans.append(doc)
                return {"inserted_id": "x"}

        class FakeExplainCollection(FakeCollection):
            async def find(self, *args, **kwargs):
                return self

            async def explain(self, **kwargs):
                return {
                    "executionStats": {
                        "nReturned": 5,
                        "totalDocsExamined": 20,
                        "totalKeysExamined": 200,
                        "executionSuccess": True,
                        "executionTimeMillis": 42,
                    }
                }

        db = FakeDB()
        db["chat_messages"] = FakeExplainCollection("chat_messages")  # 覆写
        record = await explain_and_store(db, "chat_messages", {"tenant_id": "t1"})
        assert record["executionStats"]["nReturned"] == 5
        assert record["executionStats"]["executionTimeMillis"] == 42
        assert record["collection"] == "chat_messages"
        assert record["query_filter"] == {"tenant_id": "t1"}


class TestPoolUtilizationSnapshot:
    def test_returns_shape(self) -> None:
        snap = pool_utilization_snapshot()
        assert isinstance(snap, dict)
        for dep, info in snap.items():
            assert "registered" in info
            if info.get("registered"):
                assert "utilization" in info
                assert info["peak_utilization_max"] == 0.8
                assert "breached" in info


class FakeColl:
    """最小 collection stub：记录 insert_many / insert_one 调用。"""

    def __init__(self) -> None:
        self.many: list = []
        self.one: list = []

    async def insert_many(self, recs: list) -> int:
        self.many.extend(recs)
        return len(recs)

    async def insert_one(self, rec: dict) -> None:
        self.one.append(rec)


class FakeDB:
    def __init__(self) -> None:
        self.cols: dict = {}

    def __getitem__(self, name: str) -> FakeColl:
        return self.cols.setdefault(name, FakeColl())


class TestPersist:
    async def test_persist_slow_queries(self) -> None:
        reg = SlowQueryRegistry()
        assert reg.record("find", "chat_messages", 150) is True
        assert reg.record("find_one", "memories", 10) is False  # 低于阈值不登记
        db = FakeDB()
        n = await persist_slow_queries(db, reg)
        assert n == 1
        row = db.cols["slow_queries"].many[0]
        assert row["command"] == "find" and row["namespace"] == "chat_messages"
        assert row["duration_ms"] == 150 and row["threshold_ms"] == 100
        assert reg.drain() == []  # 已 drain，重复调用不再落
        assert await persist_slow_queries(db, reg) == 0

    async def test_persist_pool_utilization(self) -> None:
        db = FakeDB()
        snap = {"mongo": {"registered": False}, "redis": {"registered": False}}
        out = await persist_pool_utilization(db, snapshot=snap)
        assert out is snap
        row = db.cols["pool_metrics"].one[0]
        assert row["snapshot"] == snap
        assert "at" in row