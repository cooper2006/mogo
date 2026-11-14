"""026 T044 — 系统资源指标采集与 Prometheus exporter（FR-29）。

* ``collect_system_metrics()``：从 ``/proc`` 读取 CPU / 内存 / IO / 磁盘 / 负载，
  无 psutil 依赖；返回纯 dict，便于测试（可传 ``proc_root`` 指向临时目录）。
* ``register_system_metrics(registry, label)``：把上述指标注册为 Prometheus Gauge，
  挂到既有 ``observability_base.init_metrics()`` 建立的 CollectorRegistry。
* ``metrics_exporter(service_name)``：返回可直接挂到 FastAPI 的 ``/metrics`` ASGI 子应用。

约束：``observability_base`` 已被其他特性冻结（不可改），故本模块只通过
``get_registry()`` 追加指标，不改动其任何实现。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────── /proc 解析（无第三方依赖） ───────────────────────────


def _read_proc(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (OSError, FileNotFoundError):
        return ""


def _cpu_ticks(cpu_line: str) -> dict[str, int]:
    """解析单行 /proc/stat 的 cpu 行 → 各状态 tick 计数。"""
    parts = cpu_line.split()
    keys = ["user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal", "guest", "guest_nice"]
    ticks: dict[str, int] = {}
    for idx, key in enumerate(keys):
        try:
            ticks[key] = int(parts[idx + 1])
        except (IndexError, ValueError):
            ticks[key] = 0
    return ticks


def _cpu_busy_and_total(ticks: dict[str, int]) -> tuple[int, int]:
    busy = (
        ticks.get("user", 0)
        + ticks.get("nice", 0)
        + ticks.get("system", 0)
        + ticks.get("irq", 0)
        + ticks.get("softirq", 0)
        + ticks.get("steal", 0)
    )
    total = busy + ticks.get("idle", 0) + ticks.get("iowait", 0)
    return busy, total


def _parse_meminfo(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(":"):
            try:
                out[parts[0][:-1]] = int(parts[1]) * 1024  # kB → bytes
            except ValueError:
                continue
    return out


def _parse_diskstats(text: str) -> dict[str, dict[str, int]]:
    """聚合 /proc/diskstats 为按设备名的读写字节/IOPS 计数。"""
    devices: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 14:
            continue
        try:
            name = parts[2]
            # fields 3..7 = reads completed, reads merged, sectors read, ms reading, reads in progress
            # fields 8..12 = writes completed, writes merged, sectors written, ms writing, writes in progress
            reads = int(parts[3])
            sectors_read = int(parts[5])
            writes = int(parts[7])
            sectors_written = int(parts[9])
        except ValueError:
            continue
        dev = devices.setdefault(name, {"read_bytes": 0, "write_bytes": 0, "reads": 0, "writes": 0})
        dev["read_bytes"] += sectors_read * 512
        dev["write_bytes"] += sectors_written * 512
        dev["reads"] += reads
        dev["writes"] += writes
    return devices


def _parse_loadavg(text: str) -> dict[str, float]:
    parts = text.split()
    try:
        return {
            "loadavg_1m": float(parts[0]),
            "loadavg_5m": float(parts[1]),
            "loadavg_15m": float(parts[2]),
        }
    except (IndexError, ValueError):
        return {"loadavg_1m": 0.0, "loadavg_5m": 0.0, "loadavg_15m": 0.0}


def _disk_usage(mounts_path: str) -> list[dict[str, Any]]:
    """按挂载点读取 statvfs 使用率，跳过虚拟文件系统。"""
    out: list[dict[str, Any]] = []
    text = _read_proc(mounts_path)
    virtual = {
        "proc", "sysfs", "tmpfs", "devtmpfs", "cgroup", "cgroup2", "overlay",
        "fuse", "none", "devpts", "mqueue", "securityfs", "pstore",
    }
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        fs, mount = parts[0], parts[1]
        fstype = parts[2]
        if fstype in virtual or fs in virtual:
            continue
        try:
            st = os.statvfs(mount)
        except OSError:
            continue
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        if total <= 0:
            continue
        out.append(
            {
                "device": fs,
                "mountpoint": mount,
                "fstype": fstype,
                "total_bytes": total,
                "available_bytes": free,
                "used_bytes": total - free,
                "usage_percent": round((total - free) / total * 100.0, 2),
            }
        )
    return out


# ─────────────────────────── 采样器 ───────────────────────────


class SystemMetricsCollector:
    """系统指标采样器：CPU 利用率需两次采样求差，其余为瞬时值。"""

    def __init__(self, proc_root: Optional[str] = None) -> None:
        self._proc_root = proc_root or "/proc"
        self._last_cpu: Optional[dict[str, int]] = None

    def _p(self, name: str) -> str:
        return os.path.join(self._proc_root, name)

    def cpu_usage_percent(self) -> float:
        line = _read_proc(self._p("stat")).splitlines()
        if not line:
            return 0.0
        ticks = _cpu_ticks(line[0])
        busy, total = _cpu_busy_and_total(ticks)
        prev = self._last_cpu
        self._last_cpu = {"busy": busy, "total": total}
        if prev is None or prev["total"] <= 0 or total <= prev["total"]:
            return 0.0
        dbusy = busy - prev["busy"]
        dtotal = total - prev["total"]
        if dtotal <= 0:
            return 0.0
        return round(max(0.0, min(100.0, dbusy / dtotal * 100.0)), 2)

    def memory(self) -> dict[str, Any]:
        mem = _parse_meminfo(_read_proc(self._p("meminfo")))
        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", 0)
        return {
            "total_bytes": total,
            "available_bytes": available,
            "used_bytes": total - available,
            "usage_percent": round((total - available) / total * 100.0, 2) if total else 0.0,
        }

    def disk_io(self) -> dict[str, int]:
        devs = _parse_diskstats(_read_proc(self._p("diskstats")))
        return {
            "read_bytes_total": sum(d["read_bytes"] for d in devs.values()),
            "write_bytes_total": sum(d["write_bytes"] for d in devs.values()),
            "reads_total": sum(d["reads"] for d in devs.values()),
            "writes_total": sum(d["writes"] for d in devs.values()),
        }

    def disks(self) -> list[dict[str, Any]]:
        return _disk_usage(self._p("mounts"))

    def loadavg(self) -> dict[str, float]:
        return _parse_loadavg(_read_proc(self._p("loadavg")))

    def snapshot(self) -> dict[str, Any]:
        return {
            "cpu_usage_percent": self.cpu_usage_percent(),
            "memory": self.memory(),
            "disk_io": self.disk_io(),
            "disks": self.disks(),
            "loadavg": self.loadavg(),
            "collected_at": __import__("time").time(),
        }


# ─────────────────────────── Prometheus 注册 ───────────────────────────


def register_system_metrics(registry: Any, label: str = "service") -> list[Any]:
    """把系统指标注册为 Prometheus Gauge 到指定 CollectorRegistry。

    返回注册的 Gauge 列表；无 prometheus_client 时返回空列表（degraded）。
    """
    try:
        from prometheus_client import Gauge
    except ImportError:  # pragma: no cover - prometheus_client 为可选依赖
        logger.warning("prometheus_client not available; skip system metrics")
        return []

    collector = SystemMetricsCollector()
    gauges: list[Any] = []

    def _gauge(name: str, doc: str, labels: Optional[list[str]] = None) -> Any:
        g = Gauge(name, doc, labels or [], registry=registry)
        gauges.append(g)
        return g

    cpu = _gauge("mogo_system_cpu_usage_percent", "System CPU usage percent (total)")
    mem_used = _gauge("mogo_system_memory_used_bytes", "System memory used bytes")
    mem_avail = _gauge("mogo_system_memory_available_bytes", "System memory available bytes")
    disk_read = _gauge("mogo_system_disk_read_bytes_total", "System disk read bytes total")
    disk_write = _gauge("mogo_system_disk_write_bytes_total", "System disk write bytes total")
    disk_read_ops = _gauge("mogo_system_disk_read_iops_total", "System disk read operations total")
    disk_write_ops = _gauge("mogo_system_disk_write_iops_total", "System disk write operations total")
    disk_usage = _gauge("mogo_system_disk_usage_percent", "Filesystem usage percent", ["device"])
    load1 = _gauge("mogo_system_loadavg_1m", "1 minute load average")
    load5 = _gauge("mogo_system_loadavg_5m", "5 minute load average")
    load15 = _gauge("mogo_system_loadavg_15m", "15 minute load average")

    def _refresh() -> None:
        snap = collector.snapshot()
        cpu.set(snap["cpu_usage_percent"])
        mem_used.set(snap["memory"]["used_bytes"])
        mem_avail.set(snap["memory"]["available_bytes"])
        io = snap["disk_io"]
        disk_read.set(io["read_bytes_total"])
        disk_write.set(io["write_bytes_total"])
        disk_read_ops.set(io["reads_total"])
        disk_write_ops.set(io["writes_total"])
        for d in snap["disks"]:
            disk_usage.labels(device=d["device"]).set(d["usage_percent"])
        load1.set(snap["loadavg"]["loadavg_1m"])
        load5.set(snap["loadavg"]["loadavg_5m"])
        load15.set(snap["loadavg"]["loadavg_15m"])

    _refresh()
    return gauges


def metrics_exporter(service_name: str) -> Any:
    """返回挂到 FastAPI 的 ``/metrics`` ASGI 子应用（FR-29）。

    先注册系统资源指标，再复用 ``observability_base.metrics_asgi_app``。
    未 ``init_metrics`` 时抛 ``RuntimeError`` 提示接线顺序。
    """
    from app.common.observability_base import get_registry, metrics_asgi_app

    registry = get_registry(service_name)
    register_system_metrics(registry, label=service_name)
    return metrics_asgi_app(service_name)


__all__ = [
    "SystemMetricsCollector",
    "collect_system_metrics",
    "register_system_metrics",
    "metrics_exporter",
]


def collect_system_metrics(proc_root: Optional[str] = None) -> dict[str, Any]:
    """一次性采集系统指标（便捷入口，供 CLI / 单测使用）。"""
    return SystemMetricsCollector(proc_root=proc_root).snapshot()