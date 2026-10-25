"""026 T051 测试 — 性能指标可观测总验证。"""
from __future__ import annotations

import pytest

from tools.perf.observability_verify import (
    CACHE_KPI_KEYS,
    check_cache_kpi,
    check_metrics_text,
    find_missing,
)

FULL_TEXT = """# HELP http_requests_total Total HTTP requests.
http_requests_total{method="POST",path_template="/api/v1/chat/completions",status_class="2xx"} 42
# HELP http_request_duration_seconds Request latency.
http_request_duration_seconds_bucket{le="0.5"} 10
http_request_duration_seconds_bucket{le="+Inf"} 42
http_request_duration_seconds_sum 12.5
http_request_duration_seconds_count 42
# HELP mogo_system_cpu_usage_percent CPU usage percent.
mogo_system_cpu_usage_percent 12.3
mogo_system_memory_used_bytes 512000000
mogo_system_memory_available_bytes 1024000000
mogo_system_disk_read_bytes_total 1000
mogo_system_disk_write_bytes_total 2000
mogo_system_disk_read_iops_total 3
mogo_system_disk_write_iops_total 4
mogo_system_disk_usage_percent{device="/dev/sda1"} 55.0
mogo_system_loadavg_1m 0.5
mogo_system_loadavg_5m 0.4
mogo_system_loadavg_15m 0.3
"""


class TestFindMissing:
    def test_all_present(self):
        assert find_missing("a=1 b=2", ("a", "b")) == []

    def test_some_missing(self):
        assert find_missing("a=1", ("a", "b")) == ["b"]


class TestCheckMetricsText:
    def test_full_text_passes(self):
        result = check_metrics_text(FULL_TEXT)
        assert result["ok"] is True
        assert result["missing"] == []
        for name in ("latency_percentiles", "throughput", "resource_utilization"):
            assert result["categories"][name]["ok"] is True

    def test_missing_resource_flags(self):
        result = check_metrics_text("http_requests_total 1\nhttp_request_duration_seconds_count 1\n")
        assert result["ok"] is False
        assert result["categories"]["resource_utilization"]["ok"] is False
        assert any("resource_utilization" in m for m in result["missing"])

    def test_latency_requires_histogram(self):
        # 只有 requests_total，没有 duration_seconds → latency 类缺失
        result = check_metrics_text("http_requests_total 1\n")
        assert result["categories"]["latency_percentiles"]["ok"] is False


class TestCheckCacheKpi:
    def test_both_keys_pass(self):
        result = check_cache_kpi(["cache_hit_rate", "cache_stats", "other"])
        assert result["ok"] is True
        assert result["missing"] == []

    def test_missing_keys(self):
        result = check_cache_kpi(["other"])
        assert result["ok"] is False
        assert set(result["missing"]) == set(CACHE_KPI_KEYS)

    def test_empty_input(self):
        result = check_cache_kpi([])
        assert result["ok"] is False

    def test_expected_constant(self):
        assert CACHE_KPI_KEYS == ("cache_hit_rate", "cache_stats")