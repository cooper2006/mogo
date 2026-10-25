"""026 T009/T010/T011 — 性能预算检查器测试（含回归判定、前端包体积）。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from app.infrastructure.observability.perf_budget import (
    PerfBudgetChecker,
    PerfBudgetThreshold,
)

# 测试用 baselines.yaml（对齐 benchmarks/perf_baselines/baselines.yaml 的 T010 结构）
FIXTURE = """
version: "026-t010"
services:
  chat-api:
    latency:
      "/chat": {p95_max_ms: 2000}
    throughput:
      max_rps_per_instance: 1000
    defaults:
      p95_max_ms: 2000
  document-parser:
    latency:
      "/jobs/document-parse": {p95_max_ms: 5000}
    throughput:
      max_rps_per_instance: 500
    defaults:
      p95_max_ms: 5000
  admin-api:
    latency:
      "/auth/login": {p95_max_ms: 500}
    throughput:
      max_rps_per_instance: 500
    defaults:
      p95_max_ms: 1000
frontend:
  admin-web:
    bundle_gzip_max_kb: 500
  user-web:
    bundle_gzip_max_kb: 300
cache:
  hit_rate_min: 0.8
database:
  slow_query_ms: 100
  max_time_ms: 5000
  pool:
    max_pool_size: 100
    min_pool_size: 10
    max_idle_seconds: 30
    leak_warning_seconds: 90
    peak_utilization_max: 0.8
concurrency:
  queue_depth_max: 1000
circuit_breaker:
  error_rate_max: 0.5
  rolling_window_seconds: 30
regression:
  p95_regression_ratio: 1.2
"""


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    p = tmp_path / "baselines.yaml"
    p.write_text(FIXTURE, encoding="utf-8")
    return p


@pytest.fixture()
def checker(config_path: Path) -> PerfBudgetChecker:
    checker = PerfBudgetChecker(service_name="chat-api")
    asyncio.get_event_loop_policy().new_event_loop()  # no-op keep import hygiene
    return checker


class TestLoadThresholds:
    async def test_loads_chat_api(self, config_path: Path) -> None:
        checker = PerfBudgetChecker(service_name="chat-api")
        await checker.load_thresholds(str(config_path))
        by_endpoint = {t.endpoint: t for t in checker.thresholds}
        assert by_endpoint["/chat"].max_value == 2000.0
        assert by_endpoint["/chat"].metric == "p95_ms"
        # 吞吐阈值
        rps = [t for t in checker.thresholds if t.metric == "rps"]
        assert rps and rps[0].max_value == 1000.0

    async def test_loads_admin_api(self, config_path: Path) -> None:
        checker = PerfBudgetChecker(service_name="admin-api")
        await checker.load_thresholds(str(config_path))
        by_endpoint = {t.endpoint: t for t in checker.thresholds}
        assert by_endpoint["/auth/login"].max_value == 500.0

    async def test_missing_file_raises(self, tmp_path: Path) -> None:
        checker = PerfBudgetChecker(service_name="chat-api")
        with pytest.raises(FileNotFoundError):
            await checker.load_thresholds(str(tmp_path / "nope.yaml"))


class TestCheck:
    async def test_breach_detected(self, config_path: Path) -> None:
        checker = PerfBudgetChecker(service_name="chat-api")
        await checker.load_thresholds(str(config_path))
        baseline = {
            "endpoint_percentiles": {
                "/chat": {"p50": 500.0, "p95": 2500.0, "p99": 3000.0, "count": 100},
            }
        }
        breached = await checker.check(baseline)
        assert len(breached) == 1
        assert breached[0].endpoint == "/chat"
        assert breached[0].current_value == 2500.0
        assert breached[0].breached is True

    async def test_within_budget_no_breach(self, config_path: Path) -> None:
        checker = PerfBudgetChecker(service_name="chat-api")
        await checker.load_thresholds(str(config_path))
        baseline = {
            "endpoint_percentiles": {
                "/chat": {"p50": 100.0, "p95": 1200.0, "p99": 1500.0, "count": 50},
            }
        }
        breached = await checker.check(baseline)
        assert breached == []

    async def test_missing_endpoint_skipped(self, config_path: Path) -> None:
        checker = PerfBudgetChecker(service_name="chat-api")
        await checker.load_thresholds(str(config_path))
        breached = await checker.check({"endpoint_percentiles": {}})
        assert breached == []


class TestCheckRegression:
    async def test_regression_detected(self, config_path: Path) -> None:
        checker = PerfBudgetChecker(service_name="chat-api")
        await checker.load_thresholds(str(config_path))
        historical = {"endpoint_percentiles": {"/chat": {"p95": 1000.0}}}
        new = {"endpoint_percentiles": {"/chat": {"p95": 1300.0}}}  # +30%
        regressions = await checker.check_regression(new, historical)
        assert len(regressions) == 1
        assert regressions[0].metric == "p95_regression"
        assert regressions[0].current_value == pytest.approx(1.3)
        assert regressions[0].max_value == pytest.approx(1.2)

    async def test_no_regression_within_threshold(self, config_path: Path) -> None:
        checker = PerfBudgetChecker(service_name="chat-api")
        await checker.load_thresholds(str(config_path))
        historical = {"endpoint_percentiles": {"/chat": {"p95": 1000.0}}}
        new = {"endpoint_percentiles": {"/chat": {"p95": 1100.0}}}  # +10%
        regressions = await checker.check_regression(new, historical)
        assert regressions == []

    async def test_historical_zero_skipped(self, config_path: Path) -> None:
        checker = PerfBudgetChecker(service_name="chat-api")
        await checker.load_thresholds(str(config_path))
        historical = {"endpoint_percentiles": {"/chat": {"p95": 0.0}}}
        new = {"endpoint_percentiles": {"/chat": {"p95": 5000.0}}}
        regressions = await checker.check_regression(new, historical)
        assert regressions == []


class TestCheckFrontendBundle:
    async def test_over_budget(self, config_path: Path) -> None:
        checker = PerfBudgetChecker(service_name="chat-api")
        await checker.load_thresholds(str(config_path))
        breached = await checker.check_frontend_bundle({"user-web": 400.0})
        assert len(breached) == 1
        assert breached[0].service == "user-web"
        assert breached[0].max_value == 300.0

    async def test_within_budget(self, config_path: Path) -> None:
        checker = PerfBudgetChecker(service_name="chat-api")
        await checker.load_thresholds(str(config_path))
        breached = await checker.check_frontend_bundle(
            {"admin-web": 450.0, "user-web": 280.0}
        )
        assert breached == []


class TestBaselinesYamlOnDisk:
    """确保仓库内 T010 文件可被 loader 读入且关键阈值正确。"""

    async def test_parses_and_matches_clarify(self) -> None:
        repo = Path(__file__).resolve().parents[4]  # tests/observability → repo 根
        path = repo / "benchmarks" / "perf_baselines" / "baselines.yaml"
        assert path.exists(), f"缺少 T010 baselines.yaml: {path}"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["services"]["chat-api"]["latency"]["/chat/completions"]["p95_max_ms"] == 2000
        assert data["services"]["document-parser"]["latency"]["/jobs/document-parse"]["p95_max_ms"] == 5000
        assert data["services"]["admin-api"]["latency"]["/auth/login"]["p95_max_ms"] == 500
        assert data["frontend"]["admin-web"]["bundle_gzip_max_kb"] == 500
        assert data["frontend"]["user-web"]["bundle_gzip_max_kb"] == 300
        assert data["cache"]["hit_rate_min"] == 0.8
        assert data["regression"]["p95_regression_ratio"] == 1.2
        # loader 可正常装配 chat-api 阈值
        checker = PerfBudgetChecker(service_name="chat-api")
        await checker.load_thresholds(str(path))
        assert any(t.endpoint == "/chat/completions" and t.max_value == 2000.0 for t in checker.thresholds)


class TestAlert:
    async def test_alert_logs(self, config_path: Path) -> None:
        checker = PerfBudgetChecker(service_name="chat-api")
        await checker.load_thresholds(str(config_path))
        t = PerfBudgetThreshold(endpoint="/chat", metric="p95_ms", max_value=2000.0, current_value=3000.0)
        await checker.alert(t)  # 只应记录日志，不抛异常
        assert True