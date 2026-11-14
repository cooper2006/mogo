"""026 T044 — 系统资源指标采集与 Prometheus exporter 测试（FR-29）。"""
from __future__ import annotations

import pytest

from app.infrastructure.observability.prometheus import (
    SystemMetricsCollector,
    collect_system_metrics,
)


def _mk_proc(tmp_path) -> str:
    (tmp_path / "stat").write_text(
        "cpu  100 0 100 800 100 0 0 0 0 0\n"
        "cpu0 100 0 100 800 100 0 0 0 0 0\n"
        "intr 0 0 0 0\n"
        "ctxt 0\n"
        "btime 0\n"
        "processes 0\n"
        "procs_running 1\n"
        "procs_blocked 0\n"
        "softirq 0 0 0 0\n",
        encoding="utf-8",
    )
    (tmp_path / "meminfo").write_text(
        "MemTotal:       1000000 kB\n"
        "MemFree:         200000 kB\n"
        "MemAvailable:    700000 kB\n"
        "Buffers:         100000 kB\n",
        encoding="utf-8",
    )
    (tmp_path / "diskstats").write_text(
        "   8       0 sda 100 0 200 0 50 0 100 0 0 0 0 0 0 0\n"
        "   8       1 sda1 50 0 100 0 25 0 50 0 0 0 0 0 0 0\n",
        encoding="utf-8",
    )
    (tmp_path / "loadavg").write_text("1.00 2.00 3.00 1/100 42\n", encoding="utf-8")
    (tmp_path / "mounts").write_text("", encoding="utf-8")
    return str(tmp_path)


class TestProcParsers:
    def test_cpu_usage_delta(self, tmp_path) -> None:
        proc = _mk_proc(tmp_path)
        col = SystemMetricsCollector(proc_root=proc)
        assert col.cpu_usage_percent() == 0.0  # 首次采样无基准
        # 第二次：busy 200→300（user+system +100），total 1100→1200 → 100/200 = 50%
        (tmp_path / "stat").write_text(
            "cpu  150 0 150 850 100 0 0 0 0 0\n", encoding="utf-8"
        )
        # 首采样 busy=100+100=200, idle=800, iowait=100, total=1100
        # 第二次 busy=150+150=300, idle=850, iowait=100, total=1250 → dbusy=100, dtotal=150
        pct = col.cpu_usage_percent()
        assert pct == pytest.approx(66.67, abs=0.02)

    def test_memory(self, tmp_path) -> None:
        col = SystemMetricsCollector(proc_root=_mk_proc(tmp_path))
        mem = col.memory()
        # MemTotal=1000000kB=1024000000B, MemAvailable=700000kB=716800000B
        assert mem["total_bytes"] == 1024000000
        assert mem["available_bytes"] == 716800000
        assert mem["used_bytes"] == 307200000
        assert mem["usage_percent"] == pytest.approx(30.0)

    def test_disk_io_aggregates_partitions(self, tmp_path) -> None:
        col = SystemMetricsCollector(proc_root=_mk_proc(tmp_path))
        io = col.disk_io()
        # sda: sectors_read=200 → 102400B; sectors_written=100 → 51200B; reads=100; writes=50
        # sda1: sectors_read=100 → 51200B; sectors_written=50 → 25600B; reads=50; writes=25
        assert io["read_bytes_total"] == 102400 + 51200
        assert io["write_bytes_total"] == 51200 + 25600
        assert io["reads_total"] == 150
        assert io["writes_total"] == 75

    def test_loadavg(self, tmp_path) -> None:
        col = SystemMetricsCollector(proc_root=_mk_proc(tmp_path))
        la = col.loadavg()
        assert la["loadavg_1m"] == 1.0
        assert la["loadavg_5m"] == 2.0
        assert la["loadavg_15m"] == 3.0

    def test_disks_empty_when_no_mounts(self, tmp_path) -> None:
        col = SystemMetricsCollector(proc_root=_mk_proc(tmp_path))
        assert col.disks() == []

    def test_missing_proc_returns_zero(self, tmp_path) -> None:
        col = SystemMetricsCollector(proc_root=str(tmp_path / "nonexistent"))
        snap = col.snapshot()
        assert snap["cpu_usage_percent"] == 0.0
        assert snap["memory"]["total_bytes"] == 0
        assert snap["disk_io"]["read_bytes_total"] == 0
        assert snap["loadavg"]["loadavg_1m"] == 0.0

    def test_collect_system_metrics_convenience(self, tmp_path) -> None:
        snap = collect_system_metrics(proc_root=_mk_proc(tmp_path))
        assert "memory" in snap and "loadavg" in snap and "disk_io" in snap
        assert snap["loadavg"]["loadavg_5m"] == 2.0


class TestPrometheusRegistration:
    def test_register_gauge_to_registry(self) -> None:
        from prometheus_client import CollectorRegistry

        registry = CollectorRegistry()
        from app.infrastructure.observability.prometheus import register_system_metrics

        gauges = register_system_metrics(registry)
        assert gauges
        names = {g._name for g in gauges}
        assert "mogo_system_cpu_usage_percent" in names
        assert "mogo_system_memory_used_bytes" in names
        assert "mogo_system_disk_read_bytes_total" in names
        assert "mogo_system_loadavg_1m" in names