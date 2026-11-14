"""026 T052 — 性能配置加载与一致性校验测试。"""
from __future__ import annotations

from tools.perf.config_loader import (
    apply_env_overrides,
    check_consistency,
    _load,
)


class TestLoad:
    def test_load_missing_raises(self, tmp_path) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            _load(tmp_path / "nope.yaml")

    def test_load_invalid_top_level(self, tmp_path) -> None:
        import pytest

        f = tmp_path / "bad.yaml"
        f.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(ValueError):
            _load(f)


class TestConsistency:
    def test_matching_returns_no_issues(self) -> None:
        perf = {
            "database": {
                "mongodb": {
                    "max_pool_size": 100,
                    "min_pool_size": 10,
                    "slow_query_threshold_ms": 100,
                }
            },
            "rate_limit": {"default_rps": 1000},
            "backpressure": {"max_depth": 1000},
            "frontend": {"admin_max_gzip_kb": 500, "user_max_gzip_kb": 300},
            "baselines": {"peak_connections_max_utilization": 0.8, "memory_max_utilization": 0.8},
        }
        base = {
            "database": {
                "pool": {"max_pool_size": 100, "min_pool_size": 10, "peak_utilization_max": 0.8},
                "slow_query_ms": 100,
            },
            "services": {"chat-api": {"throughput": {"max_rps_per_instance": 1000}}},
            "concurrency": {"queue_depth_max": 1000},
            "frontend": {
                "admin-web": {"bundle_gzip_max_kb": 500},
                "user-web": {"bundle_gzip_max_kb": 300},
            },
        }
        assert check_consistency(perf, base) == []

    def test_mismatch_reported(self) -> None:
        perf = {
            "database": {"mongodb": {"max_pool_size": 100}},
            "rate_limit": {"default_rps": 500},
            "backpressure": {"max_depth": 1000},
        }
        base = {
            "database": {"pool": {"max_pool_size": 200}},
            "services": {"chat-api": {"throughput": {"max_rps_per_instance": 1000}}},
            "concurrency": {"queue_depth_max": 1000},
        }
        issues = check_consistency(perf, base)
        joined = "\n".join(issues)
        assert "max_pool_size" in joined
        assert "rate_limit.default_rps" in joined

    def test_missing_perf_key_flagged(self) -> None:
        perf: dict = {}
        base = {"database": {"pool": {"max_pool_size": 100}}}
        issues = check_consistency(perf, base)
        assert any("缺失" in i for i in issues)


class TestEnvOverrides:
    def test_applies_env(self, monkeypatch) -> None:
        monkeypatch.setenv("MONGODB_MAX_POOL_SIZE", "200")
        monkeypatch.setenv("REDIS_MAXMEMORY", "512mb")
        cfg = {
            "database": {"mongodb": {"max_pool_size": 100}},
            "cache": {"redis": {"maxmemory": "256mb"}},
        }
        overrides = apply_env_overrides(cfg)
        assert "database.mongodb.max_pool_size" in overrides
        assert overrides["database.mongodb.max_pool_size"]["effective"] == "200"
        assert "cache.redis.maxmemory" in overrides

    def test_no_env_no_overrides(self, monkeypatch) -> None:
        monkeypatch.delenv("MONGODB_MAX_POOL_SIZE", raising=False)
        assert apply_env_overrides({}) == {}