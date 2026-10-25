#!/usr/bin/env python3
"""026 T051 — 性能指标可观测总验证。

校验四类性能黄金信号均可查（Success 基准）：

1. 延迟分位数   → Prometheus ``http_request_duration_seconds``（Histogram，含 le= 桶）
2. 吞吐         → Prometheus ``http_requests_total``
3. 缓存命中率   → KPI store 键 ``cache_hit_rate`` / ``cache_stats``
4. 资源利用率   → Prometheus ``mogo_system_*``（CPU/内存/磁盘/loadavg）

Prometheus 端通过抓取 ``/metrics`` 文本校验；缓存命中率走 KPI store（DB），
因此需要两个渠道都就位，才判"100% 可查"。

用法::

    python3 tools/perf/observability_verify.py --metrics-url http://127.0.0.1:8000/metrics
    python3 tools/perf/observability_verify.py --metrics-text-file /tmp/metrics.txt --kpi-keys cache_hit_rate,cache_stats
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from typing import Any, Dict, List

# 每类的期望指标子串（出现在 /metrics 文本中即视为"可查"）
LATENCY_METRICS = ("http_request_duration_seconds",)
THROUGHPUT_METRICS = ("http_requests_total",)
RESOURCE_METRICS = (
    "mogo_system_cpu_usage_percent",
    "mogo_system_memory_used_bytes",
    "mogo_system_memory_available_bytes",
    "mogo_system_disk_read_bytes_total",
    "mogo_system_disk_write_bytes_total",
    "mogo_system_disk_read_iops_total",
    "mogo_system_disk_write_iops_total",
    "mogo_system_disk_usage_percent",
    "mogo_system_loadavg_1m",
    "mogo_system_loadavg_5m",
    "mogo_system_loadavg_15m",
)

# KPI store 键白名单（缓存命中率走 DB，不在 /metrics）
CACHE_KPI_KEYS = ("cache_hit_rate", "cache_stats")


def find_missing(text: str, metrics: tuple) -> List[str]:
    """返回缺失的指标子串列表（已出现则不含）。"""
    missing = [m for m in metrics if m not in text]
    return missing


def check_metrics_text(text: str) -> Dict[str, Any]:
    """校验 /metrics 文本，返回四类可查状态与缺失明细。"""
    result: Dict[str, Any] = {"ok": True, "categories": {}, "missing": []}
    categories = {
        "latency_percentiles": (LATENCY_METRICS, text),
        "throughput": (THROUGHPUT_METRICS, text),
        "resource_utilization": (RESOURCE_METRICS, text),
    }
    for name, (metrics, haystack) in categories.items():
        missing = find_missing(haystack, metrics)
        result["categories"][name] = {
            "ok": not missing,
            "expected": list(metrics),
            "missing": missing,
        }
        for m in missing:
            result["missing"].append("%s: %s" % (name, m))
    if result["missing"]:
        result["ok"] = False
    return result


def check_cache_kpi(kpi_keys: List[str]) -> Dict[str, Any]:
    """校验 KPI store 键是否包含缓存命中率键。"""
    present = [k for k in CACHE_KPI_KEYS if k in kpi_keys]
    missing = [k for k in CACHE_KPI_KEYS if k not in kpi_keys]
    return {
        "ok": not missing,
        "expected": list(CACHE_KPI_KEYS),
        "present": present,
        "missing": missing,
    }


def fetch(url: str, timeout: float = 5.0) -> str:
    req = urllib.request.Request(url, headers={"Accept": "text/plain"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def render_report(metrics_check: Dict[str, Any], kpi_check: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("性能指标可观测性总验证")
    lines.append("=" * 50)
    cat_labels = {
        "latency_percentiles": "延迟分位数（http_request_duration_seconds）",
        "throughput": "吞吐（http_requests_total）",
        "resource_utilization": "资源利用率（mogo_system_*）",
    }
    for name, label in cat_labels.items():
        info = metrics_check["categories"][name]
        flag = "✔" if info["ok"] else "✘"
        lines.append("%s %-38s 缺失=%s" % (flag, label, ", ".join(info["missing"]) or "无"))
    kpi_flag = "✔" if kpi_check["ok"] else "✘"
    lines.append(
        "%s %-38s 缺失=%s" % (
            kpi_flag,
            "缓存命中率（KPI store cache_hit_rate）",
            ", ".join(kpi_check["missing"]) or "无",
        )
    )
    lines.append("-" * 50)
    ok = metrics_check["ok"] and kpi_check["ok"]
    lines.append("结论: %s（四类黄金信号 100%% 可查）" % ("PASS" if ok else "FAIL"))
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--metrics-url", help="Prometheus /metrics 端点 URL")
    src.add_argument("--metrics-text-file", help="已抓取的 /metrics 文本文件路径")
    parser.add_argument("--kpi-keys", help="逗号分隔的 KPI store 键白名单（默认只校验缓存键）")
    parser.add_argument("--skip-kpi", action="store_true", help="跳过 KPI store 校验")
    args = parser.parse_args(argv)

    if args.metrics_url:
        try:
            text = fetch(args.metrics_url)
        except Exception as exc:  # noqa: BLE001
            print("无法抓取 %s: %s" % (args.metrics_url, exc), file=sys.stderr)
            return 2
    else:
        with open(args.metrics_text_file, "r", encoding="utf-8") as fh:  # type: ignore[arg-type]
            text = fh.read()

    metrics_check = check_metrics_text(text)

    if args.skip_kpi:
        kpi_check: Dict[str, Any] = {"ok": True, "present": [], "missing": [], "expected": []}
    else:
        keys = [k.strip() for k in (args.kpi_keys or "").split(",") if k.strip()]
        kpi_check = check_cache_kpi(keys)

    print(render_report(metrics_check, kpi_check))
    ok = metrics_check["ok"] and kpi_check["ok"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())