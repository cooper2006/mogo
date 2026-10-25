"""026 T023-T027 — 缓存管理器/失效策略/防护层测试。

全部使用 memory 降级后端（不依赖 Redis），验证逻辑正确性。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 保证能 import services/common 下的缓存模块（测试放在 tools/tests）
_COMMON = Path(__file__).resolve().parents[2] / "services" / "common"
if str(_COMMON) not in sys.path:
    sys.path.insert(0, str(_COMMON))

from cache_manager import CacheManager, DEFAULT_TTL_SECONDS  # noqa: E402
from cache_policies import (  # noqa: E402
    CacheTag,
    EventInvalidationPolicy,
    TTLPolicy,
    VersionStampPolicy,
)
from cache_protection import (  # noqa: E402
    AvalancheGuard,
    BloomFilterGuard,
    MutexGuard,
)


class TestCacheManager:
    def test_backend_memory(self) -> None:
        assert CacheManager().backend == "memory"

    def test_get_miss_returns_default(self) -> None:
        mgr = CacheManager()
        assert mgr.get("missing", default=None) is None
        assert mgr.get("missing", default="d") == "d"

    def test_set_get_roundtrip(self) -> None:
        mgr = CacheManager()
        mgr.set("k", {"a": 1})
        assert mgr.get("k") == {"a": 1}

    def test_delete(self) -> None:
        mgr = CacheManager()
        mgr.set("k", "v")
        assert mgr.delete("k") is True
        assert mgr.get("k") is None

    def test_ttl_expiry(self) -> None:
        mgr = CacheManager()
        mgr.set("k", "v", ttl=0.01)
        import time

        time.sleep(0.02)
        assert mgr.get("k") is None

    def test_default_ttl_value(self) -> None:
        mgr = CacheManager(default_ttl=5.0)
        assert mgr.default_ttl == 5.0
        mgr.set("k", "v")
        assert mgr.get("k") == "v"

    def test_tags_and_forget_tag(self) -> None:
        mgr = CacheManager()
        mgr.set("k1", "v1", tags=["session"])
        mgr.set("k2", "v2", tags=["session"])
        mgr.set("k3", "v3", tags=["config"])
        assert mgr.get("k1") == "v1"
        assert mgr.forget_tag("session") == 2
        assert mgr.get("k1") is None
        assert mgr.get("k2") is None
        assert mgr.get("k3") == "v3"

    def test_keys_for_tag(self) -> None:
        mgr = CacheManager(namespace="ns")
        mgr.set("a", "1", tags=["t"])
        mgr.set("b", "2", tags=["t"])
        keys = sorted(mgr.keys_for_tag("t"))
        assert keys == ["a", "b"]

    def test_set_if_absent(self) -> None:
        mgr = CacheManager()
        assert mgr.set_if_absent("k", "v1") is True
        assert mgr.set_if_absent("k", "v2") is False
        assert mgr.get("k") == "v1"

    def test_hit_rate_metrics(self) -> None:
        mgr = CacheManager()
        mgr.set("k", "v")
        assert mgr.get("k") == "v"
        mgr.get("k")
        mgr.get("missing")
        stats = mgr.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == pytest.approx(2 / 3)
        assert stats["backend"] == "memory"

    def test_lru_eviction(self) -> None:
        mgr = CacheManager(memory_max_entries=2)
        mgr.set("a", 1)
        mgr.set("b", 2)
        mgr.set("c", 3)  # 触发淘汰
        stats = mgr.stats()
        assert stats["evictions"] >= 1
        assert len(mgr._memory) <= 2

    def test_namespace_prefix(self) -> None:
        a = CacheManager(namespace="a")
        b = CacheManager(namespace="b")
        a.set("k", "va")
        b.set("k", "vb")
        assert a.get("k") == "va"
        assert b.get("k") == "vb"

    def test_lock_acquire_release(self) -> None:
        mgr = CacheManager()
        lock = mgr.lock("my_lock")
        assert lock.acquire() is True
        # 已持有 → 幂等
        assert lock.acquire() is True
        lock.release()
        assert mgr.lock("my_lock").acquire() is True

    def test_lock_context_manager(self) -> None:
        mgr = CacheManager()
        with mgr.lock("ctx_lock", ttl=5.0):
            # 进入前已获得锁；再次获取非阻塞应失败
            assert mgr.lock("ctx_lock").acquire(blocking=False) is False
        assert mgr.lock("ctx_lock").acquire(blocking=False) is True


class TestTTLPolicy:
    def test_default_ttl(self) -> None:
        p = TTLPolicy()
        assert p.ttl_for("ns", "k") == DEFAULT_TTL_SECONDS

    def test_override_ttl(self) -> None:
        p = TTLPolicy(default_ttl=10.0)
        assert p.ttl_for("ns", "k") == 10.0
        assert p.ttl_for("ns", "k", base_ttl=50.0) == 50.0

    def test_jittered_ttl_within_range(self) -> None:
        p = TTLPolicy(default_ttl=100.0, jitter_ratio=0.10)
        for _ in range(50):
            ttl = p.jittered_ttl(100.0)
            assert 90.0 <= ttl <= 110.0
            assert ttl >= 1.0

    def test_is_expired(self) -> None:
        p = TTLPolicy()
        import time

        now = time.monotonic()
        assert p.is_expired(now - 1, now=now) is True
        assert p.is_expired(now + 100, now=now) is False


class TestEventInvalidationPolicy:
    def test_notify_forget_tag(self) -> None:
        mgr = CacheManager()
        mgr.set("k", "v", tags=["cfg"])
        policy = EventInvalidationPolicy(mgr)
        assert policy.notify("cfg") == 1
        assert mgr.get("k") is None

    def test_custom_handler(self) -> None:
        mgr = CacheManager()
        policy = EventInvalidationPolicy(mgr)
        calls = []

        def handler(payload):
            calls.append(payload)
            return 7

        policy.register("custom", handler)
        assert policy.notify("custom", {"x": 1}) == 7
        assert calls == [{"x": 1}]

    def test_forget_all(self) -> None:
        mgr = CacheManager()
        mgr.set("k1", "v", tags=["t1"])
        mgr.set("k2", "v", tags=["t2"])
        policy = EventInvalidationPolicy(mgr)
        assert policy.forget_all(["t1", "t2"]) == 2
        assert mgr.get("k1") is None and mgr.get("k2") is None


class TestVersionStampPolicy:
    def test_validate_current(self) -> None:
        mgr = CacheManager()
        policy = VersionStampPolicy(mgr)
        assert policy.current_version("cfg") == 0
        policy.bump("cfg")
        assert policy.current_version("cfg") == 1
        assert policy.validate("cfg", 1) is True
        assert policy.validate("cfg", 0) is False

    def test_bump_increments(self) -> None:
        mgr = CacheManager()
        policy = VersionStampPolicy(mgr)
        assert policy.bump("k") == 1
        assert policy.bump("k") == 2
        assert policy.current_version("k") == 2


class TestBloomFilterGuard:
    def test_might_exist_false_for_unknown(self) -> None:
        mgr = CacheManager()
        guard = BloomFilterGuard(mgr)
        assert guard.might_exist("nope") is False

    def test_add_then_might_exist(self) -> None:
        mgr = CacheManager()
        guard = BloomFilterGuard(mgr)
        guard.add("known")
        assert guard.might_exist("known") is True

    def test_get_or_load_blocks_missing(self) -> None:
        mgr = CacheManager()
        guard = BloomFilterGuard(mgr)
        called = []
        result = guard.get_or_load("missing", lambda: called.append(1) or "data")
        assert result is None
        assert called == []  # 布隆过滤直接拦截，producer 未调用

    def test_get_or_load_empty_cache(self) -> None:
        mgr = CacheManager()
        guard = BloomFilterGuard(mgr)
        guard.add("k")
        called = []
        assert guard.get_or_load("k", lambda: called.append(1) or None) is None
        assert called == [1]
        # 第二次命中空值缓存，producer 不再调用
        assert guard.get_or_load("k", lambda: called.append(2) or None) is None
        assert called == [1]

    def test_get_or_load_hit(self) -> None:
        mgr = CacheManager()
        guard = BloomFilterGuard(mgr)
        guard.add("k")
        calls = []
        result = guard.get_or_load("k", lambda: calls.append(1) or {"data": 1})
        assert result == {"data": 1}
        assert calls == [1]
        # 第二次走缓存
        assert guard.get_or_load("k", lambda: calls.append(2) or {"data": 2}) == {"data": 1}
        assert calls == [1]


class TestMutexGuard:
    def test_singleflight_first_call(self) -> None:
        mgr = CacheManager()
        guard = MutexGuard(mgr)
        calls = []
        result = guard.singleflight("k", lambda: calls.append(1) or "computed")
        assert result == "computed"
        assert calls == [1]

    def test_singleflight_cached(self) -> None:
        mgr = CacheManager()
        mgr.set("k", "cached")
        guard = MutexGuard(mgr)
        calls = []
        assert guard.singleflight("k", lambda: calls.append(1) or "x") == "cached"
        assert calls == []

    def test_singleflight_only_one_rebuild(self) -> None:
        mgr = CacheManager()
        guard = MutexGuard(mgr)
        calls = []
        results = []

        def producer():
            calls.append(1)
            mgr.set("k", "built")
            return "built"

        # 两个请求并发，只有一个真正重建
        results.append(guard.singleflight("k", producer))
        # 第二个请求直接命中缓存（memory 后端锁在单线程里已释放）
        results.append(guard.singleflight("k", producer))
        assert results == ["built", "built"]
        assert calls == [1]

    def test_acquire_release(self) -> None:
        mgr = CacheManager()
        guard = MutexGuard(mgr)
        assert guard.acquire("lock") is True
        # memory 后端再次 acquire 返回 False
        assert guard.acquire("lock") is False
        guard.release("lock")
        assert guard.acquire("lock") is True


class TestAvalancheGuard:
    def test_jittered_ttl_range(self) -> None:
        mgr = CacheManager()
        guard = AvalancheGuard(mgr)
        for _ in range(30):
            ttl = guard.jittered_ttl(100.0)
            assert 90.0 <= ttl <= 110.0

    def test_set_with_jitter(self) -> None:
        mgr = CacheManager()
        guard = AvalancheGuard(mgr)
        used = guard.set_with_jitter("k", "v", base_ttl=100.0)
        assert 90.0 <= used <= 110.0
        assert mgr.get("k") == "v"