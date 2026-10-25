"""026 T029 (FR-13) — 四类热点数据缓存门面（HotspotCache）测试。

使用 chat-api 的 vendored 副本 ``app.cache.hotspots`` 验证（其他两服务 vendored
副本字节一致，由 ``test_vendored_byte_identical`` 校验 md5）。
全部使用 memory 降级后端，不依赖 Redis。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.cache.hotspots import (
    HOTSPOT_CONFIG,
    HOTSPOT_KINDS,
    HOTSPOT_PERMISSION,
    HOTSPOT_SESSION,
    HOTSPOT_TOKEN,
    HotspotCache,
)
from app.cache.manager import CacheManager
from app.cache.policies import TTLPolicy


def make_hotspot(**kw) -> HotspotCache:
    mgr = CacheManager(None, namespace="test", default_ttl=300)
    return HotspotCache(mgr, **kw)


class TestKey:
    def test_key_format(self) -> None:
        h = make_hotspot()
        assert h.key(HotspotCache.SESSION, "s1") == "hotspot:session:s1"
        assert h.key(HotspotCache.TOKEN, "abc") == "hotspot:token:abc"

    def test_key_rejects_unknown_kind(self) -> None:
        h = make_hotspot()
        with pytest.raises(ValueError, match="unknown hotspot kind"):
            h.key("nope", "1")

    def test_tag_for(self) -> None:
        h = make_hotspot()
        assert h.tag_for(HotspotCache.CONFIG) == "hotspot:config"
        assert h.tag_for(HotspotCache.PERMISSION) == "hotspot:permission"
        with pytest.raises(ValueError):
            h.tag_for("nope")

    def test_kinds_match_fr(self) -> None:
        # 四类热点：session/config/permission/token
        assert set(HOTSPOT_KINDS) == {
            HOTSPOT_SESSION,
            HOTSPOT_CONFIG,
            HOTSPOT_PERMISSION,
            HOTSPOT_TOKEN,
        }


class TestGetPut:
    def test_put_then_get_roundtrip(self) -> None:
        h = make_hotspot()
        assert h.put(HotspotCache.SESSION, "s1", {"user_id": "u1"}) is True
        assert h.get(HotspotCache.SESSION, "s1") == {"user_id": "u1"}

    def test_get_miss_returns_default(self) -> None:
        h = make_hotspot()
        assert h.get(HotspotCache.TOKEN, "missing") is None
        assert h.get(HotspotCache.TOKEN, "missing", default="fallback") == "fallback"

    def test_kind_isolation(self) -> None:
        h = make_hotspot()
        h.put(HotspotCache.SESSION, "x", 1)
        h.put(HotspotCache.CONFIG, "x", 2)
        assert h.get(HotspotCache.SESSION, "x") == 1
        assert h.get(HotspotCache.CONFIG, "x") == 2

    def test_put_applies_jitter(self) -> None:
        # ±10% 抖动：300s 应在 [270, 330] 内，且多次取值不全相同（防雪崩 T027）
        h = make_hotspot()
        ttls = set()
        for i in range(50):
            h.put(HotspotCache.TOKEN, str(i), "v")
            ttls.add(round(h._m._memory[h._m._key(h.key(HotspotCache.TOKEN, str(i)))].ttl, 1))
        assert all(270.0 <= t <= 330.0 for t in ttls)
        assert len(ttls) > 1

    def test_explicit_ttl_wins(self) -> None:
        h = make_hotspot(ttl=300)

        class Fixed(TTLPolicy):
            def jittered_ttl(self, base_ttl=None, *a, **kw):  # type: ignore[override]
                return float(base_ttl)

        h._ttl_policy = Fixed()
        h.put(HotspotCache.SESSION, "a", "v", ttl=60)
        entry = h._m._memory[h._m._key(h.key(HotspotCache.SESSION, "a"))]
        assert 59.0 <= entry.ttl <= 61.0


class TestDelete:
    def test_delete_single(self) -> None:
        h = make_hotspot()
        h.put(HotspotCache.PERMISSION, "p1", "v")
        assert h.get(HotspotCache.PERMISSION, "p1") == "v"
        h.delete(HotspotCache.PERMISSION, "p1")
        assert h.get(HotspotCache.PERMISSION, "p1") is None

    def test_delete_kind_forgets_all(self) -> None:
        h = make_hotspot()
        for i in range(3):
            h.put(HotspotCache.TOKEN, f"t{i}", i)
        for i in range(3):
            h.put(HotspotCache.SESSION, f"s{i}", i)
        removed = h.delete(HotspotCache.TOKEN)
        assert removed == 3
        assert h.get(HotspotCache.TOKEN, "t0") is None
        assert h.get(HotspotCache.SESSION, "s0") == 0  # 其他类型不受影响

    def test_invalidate_all(self) -> None:
        h = make_hotspot()
        for kind in HOTSPOT_KINDS:
            h.put(kind, "k", "v")
        assert h.invalidate_all() == 4
        for kind in HOTSPOT_KINDS:
            assert h.get(kind, "k") is None

    def test_invalidate_all_subset(self) -> None:
        h = make_hotspot()
        for kind in HOTSPOT_KINDS:
            h.put(kind, "k", "v")
        assert h.invalidate_all([HOTSPOT_CONFIG]) == 1
        assert h.get(HOTSPOT_CONFIG, "k") is None
        assert h.get(HOTSPOT_SESSION, "k") == "v"


class TestFactoriesAndStats:
    def test_stats_shape(self) -> None:
        h = make_hotspot()
        h.put(HotspotCache.SESSION, "a", "v")
        h.get(HotspotCache.SESSION, "a")
        h.get(HotspotCache.SESSION, "miss")
        st = h.stats()
        assert st["hits"] == 1 and st["misses"] == 1

    def test_from_common_authoritative_module(self) -> None:
        # 权威源 services/common/cache_hotspots.py 可独立构建（fallback import）
        import sys

        root = Path(__file__).resolve().parents[4]
        common = root / "services" / "common"
        if str(common) not in sys.path:
            sys.path.insert(0, str(common))
        import cache_hotspots  # noqa: E402

        h = cache_hotspots.build_hotspot_from_settings(type("S", (), {"REDIS_URL": None})(), ttl=120)
        assert h.ttl == 120.0
        assert h.manager.backend == "memory"


class TestVendoredByteIdentical:
    def test_three_service_copies_match(self) -> None:
        root = Path(__file__).resolve().parents[4]
        copies = [
            root / "services" / "common" / "cache_hotspots.py",
            root / "services" / "admin-api" / "app" / "cache" / "hotspots.py",
            root / "services" / "chat-api" / "app" / "cache" / "hotspots.py",
            root / "services" / "document-parser" / "app" / "cache" / "hotspots.py",
        ]
        digests = {hashlib.sha256(p.read_bytes()).hexdigest() for p in copies}
        assert len(digests) == 1, "三服务 vendored 副本必须与权威源字节一致"