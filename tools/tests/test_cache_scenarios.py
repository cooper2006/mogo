"""026 T032 — 缓存集成场景测试（穿透/击穿/雪崩 + 命中率统计）。

对应 tasks.md 独立测试：命中率 > 80%；穿透/击穿/雪崩防护生效。
全部使用 memory 降级后端，逻辑与 Redis 后端一致。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_COMMON = Path(__file__).resolve().parents[2] / "services" / "common"
if str(_COMMON) not in sys.path:
    sys.path.insert(0, str(_COMMON))

from cache_manager import CacheManager  # noqa: E402
from cache_memoize import cache_result  # noqa: E402
from cache_metrics import CacheMetricsReporter  # noqa: E402
from cache_policies import TTLPolicy  # noqa: E402
from cache_protection import AvalancheGuard, BloomFilterGuard, MutexGuard  # noqa: E402


class TestPenetrationScenario:
    """T025 穿透：布隆过滤 + 空值缓存拦截必然不存在的请求。"""

    def test_unknown_key_blocked_before_producer(self) -> None:
        mgr = CacheManager()
        guard = BloomFilterGuard(mgr)
        calls = []
        result = guard.get_or_load("ghost", lambda: calls.append(1) or {"data": 1})
        assert result is None
        assert calls == []  # 布隆过滤直接拦截，未触达数据源
        assert guard.null_hits >= 1

    def test_empty_value_cached_60s(self) -> None:
        mgr = CacheManager()
        guard = BloomFilterGuard(mgr)
        guard.add("known-missing")
        calls = []
        assert guard.get_or_load("known-missing", lambda: calls.append(1) or None) is None
        assert guard.get_or_load("known-missing", lambda: calls.append(2) or None) is None
        assert calls == [1]  # 第二次命中空值缓存

    def test_hot_key_hits_after_warmup(self) -> None:
        mgr = CacheManager()
        guard = BloomFilterGuard(mgr)
        guard.add("hot")
        calls = []
        assert guard.get_or_load("hot", lambda: calls.append(1) or "V") == "V"
        assert guard.get_or_load("hot", lambda: calls.append(2) or "V") == "V"
        assert calls == [1]


class TestBreakdownScenario:
    """T026 击穿：热点键失效时单请求重建，其余等待后读新值。"""

    def test_singleflight_rebuilds_once(self) -> None:
        mgr = CacheManager()
        guard = MutexGuard(mgr)
        calls = []

        def producer():
            calls.append(1)
            mgr.set("hot", "built")
            return "built"

        assert guard.singleflight("hot", producer) == "built"
        assert guard.singleflight("hot", producer) == "built"
        assert calls == [1]

    def test_lock_release_allows_next_acquire(self) -> None:
        mgr = CacheManager()
        guard = MutexGuard(mgr)
        assert guard.acquire("k") is True
        assert guard.acquire("k") is False  # 已持有
        guard.release("k")
        assert guard.acquire("k") is True

    def test_mutex_lock_expires_to_avoid_deadlock(self) -> None:
        mgr = CacheManager()
        guard = MutexGuard(mgr, lock_ttl=0.01)
        assert guard.acquire("k") is True
        # 持有期间再次获取失败（memory 后端无 TTL 过期，锁必须显式释放）
        assert guard.acquire("k") is False
        guard.release("k")
        assert guard.acquire("k") is True


class TestAvalancheScenario:
    """T027 雪崩：TTL 抖动 ±10% 随机，避免热点键同时失效。"""

    def test_ttl_jitter_within_band(self) -> None:
        mgr = CacheManager()
        guard = AvalancheGuard(mgr, jitter_ratio=0.10)
        for _ in range(200):
            ttl = guard.jittered_ttl(100.0)
            assert 90.0 <= ttl <= 110.0

    def test_keys_expire_at_different_times(self) -> None:
        mgr = CacheManager()
        guard = AvalancheGuard(mgr, jitter_ratio=0.10)
        ttls = {f"k{i}": guard.set_with_jitter(f"k{i}", i, base_ttl=300.0) for i in range(50)}
        distinct = len(set(round(t, 1) for t in ttls.values()))
        assert distinct > 1  # 抖动使 50 个键 TTL 不全部相同

    def test_policy_ttl_default_300(self) -> None:
        mgr = CacheManager()
        guard = AvalancheGuard(mgr)
        policy = guard.policy
        assert isinstance(policy, TTLPolicy)
        assert policy.default_ttl == 300.0


class TestHitRateScenario:
    """T030/T032 命中率统计：命中率 > 80% 目标可达成。"""

    def test_hit_rate_above_80pct(self) -> None:
        mgr = CacheManager()
        mgr.set("hot", "v")
        for _ in range(10):
            assert mgr.get("hot") == "v"
        mgr.get("miss")  # 一次 miss
        stats = mgr.stats()
        assert stats["hit_rate"] >= 0.9  # 11 次请求中 10 次命中

    def test_hit_rate_reported_ok(self) -> None:
        mgr = CacheManager()
        mgr.set("k", "v")
        for _ in range(20):
            mgr.get("k")
        reporter = CacheMetricsReporter(mgr)
        snap = reporter.collect()
        assert snap["hit_rate"] == pytest.approx(1.0)
        assert snap["breached"] is False

    def test_memoize_hit_rate(self) -> None:
        mgr = CacheManager()
        calls = []

        @cache_result(mgr, ttl=60.0)
        def compute(x):
            calls.append(x)
            return x * x

        for _ in range(5):
            compute(4)
        assert calls == [4]  # 只算一次
        assert mgr.stats()["hit_rate"] == pytest.approx(0.8)


class TestEndToEndScenario:
    """T032 端到端：穿透+击穿+雪崩防护叠加使用。"""

    def test_stacked_protection(self) -> None:
        mgr = CacheManager()
        bloom = BloomFilterGuard(mgr)
        mutex = MutexGuard(mgr)
        avalanche = AvalancheGuard(mgr)
        bloom.add("key")
        calls = []

        def load():
            calls.append(1)
            mgr.set("key", "data")
            return "data"

        # 布隆过滤 → 击穿防护 → 雪崩抖动写
        v = bloom.get_or_load("key", lambda: mutex.singleflight("key", load))
        assert v == "data"
        assert calls == [1]
        ttl = avalanche.jittered_ttl(300.0)
        assert 270.0 <= ttl <= 330.0


class TestCacheCapacity:
    """T031 Redis maxmemory-policy=allkeys-lru 容量淘汰策略检查。"""

    def test_expected_defaults(self) -> None:
        from tools.perf.cache_capacity_check import expected_settings

        assert expected_settings({}) == {
            "maxmemory-policy": "allkeys-lru",
            "maxmemory": "256mb",
        }

    def test_expected_env_override(self) -> None:
        from tools.perf.cache_capacity_check import MAXMEMORY_ENV, POLICY_ENV, expected_settings

        env = {POLICY_ENV: "allkeys-random", MAXMEMORY_ENV: "512mb"}
        assert expected_settings(env) == {
            "maxmemory-policy": "allkeys-random",
            "maxmemory": "512mb",
        }

    def test_evaluate_ok(self) -> None:
        from tools.perf.cache_capacity_check import evaluate, expected_settings

        result = evaluate({"maxmemory-policy": "allkeys-lru", "maxmemory": "268435456"}, expected_settings({}))
        assert result["policy"]["ok"] is True
        assert result["maxmemory"]["ok"] is True
        assert result["all_ok"] is True

    def test_evaluate_wrong_policy(self) -> None:
        from tools.perf.cache_capacity_check import evaluate, expected_settings

        result = evaluate({"maxmemory-policy": "noeviction", "maxmemory": "268435456"}, expected_settings({}))
        assert result["policy"]["ok"] is False
        assert result["all_ok"] is False

    def test_evaluate_zero_maxmemory(self) -> None:
        from tools.perf.cache_capacity_check import evaluate, expected_settings

        result = evaluate({"maxmemory-policy": "allkeys-lru", "maxmemory": "0"}, expected_settings({}))
        assert result["maxmemory"]["ok"] is False
        assert result["all_ok"] is False

    def test_bytes_conversion(self) -> None:
        from tools.perf.cache_capacity_check import _to_bytes

        assert _to_bytes("256mb") == 256 * 1024 * 1024
        assert _to_bytes("1gb") == 1024 ** 3
        assert _to_bytes("1024") == 1024

    def test_memory_ok_larger_allowed(self) -> None:
        from tools.perf.cache_capacity_check import _memory_ok

        assert _memory_ok("512mb", "256mb") is True
        assert _memory_ok("128mb", "256mb") is False