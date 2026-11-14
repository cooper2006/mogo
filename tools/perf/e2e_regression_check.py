#!/usr/bin/env python3
"""026 T057 — 性能回归判定端到端验证（CI 全链路）。

把三件事串成一条 CI 可调用的命令：

1. **基线采集**  ``PerfBaselineCollector.collect(spans)`` → PerfBaselineRecord
2. **预算检查**  ``PerfBudgetChecker.check(baseline)``        → breached 列表
3. **回归判定**  ``PerfBudgetChecker.check_regression(new, historical)``
                → 劣化 > 20%（baselines.yaml ``regression.p95_regression_ratio``）判回归

关键对齐：``check`` 与 ``check_regression`` 期望 ``{endpoint: {p95: ms, ...}}``
形状（或带 ``endpoint_percentiles`` 键的包裹），而采集器产出
``PerfBaselineRecord`` 列表 —— 中间转换由 ``records_to_percentiles`` 负责。

CI 用法::

    # 新构建的 span（JSON） + 上一发布的历史基线（JSON）
    python3 tools/perf/e2e_regression_check.py \
        --spans-json /tmp/new-spans.json \
        --historical-json /tmp/historical-baselines.json \
        --baselines-yaml benchmarks/perf_baselines/baselines.yaml

退出码：0 = 无预算违反且无回归；1 = 有预算违反；2 = 有性能回归。
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from app.infrastructure.observability.perf_baseline import (
    PerfBaselineCollector,
    PerfBaselineRecord,
)
from app.infrastructure.observability.perf_budget import PerfBudgetChecker


def records_to_percentiles(records: List[PerfBaselineRecord]) -> Dict[str, Dict[str, float]]:
    """把 PerfBaselineRecord 列表转成 check/check_regression 期望的百分位字典。

    ``{endpoint: {p50, p95, p99, count}}``。
    """
    out: Dict[str, Dict[str, float]] = {}
    for rec in records or []:
        out[rec.endpoint] = {
            "p50": float(rec.p50_ms),
            "p95": float(rec.p95_ms),
            "p99": float(rec.p99_ms),
            "count": float(rec.sample_count),
        }
    return out


async def run_chain(
    collector: PerfBaselineCollector,
    checker: PerfBudgetChecker,
    spans: List[Dict[str, Any]],
    historical_records: List[PerfBaselineRecord],
) -> Dict[str, Any]:
    """执行采集 → 预算检查 → 回归判定，返回结构化结果。"""
    new_records = await collector.collect(spans)
    new_pct = records_to_percentiles(new_records)
    hist_pct = records_to_percentiles(historical_records)

    baseline_payload = {"endpoint_percentiles": new_pct}
    breached = await checker.check(baseline_payload)
    regressions = await checker.check_regression(new_pct, hist_pct)

    return {
        "collected_endpoints": sorted(new_pct.keys()),
        "breached": [
            {
                "endpoint": t.endpoint,
                "metric": t.metric,
                "max_value": t.max_value,
                "current_value": t.current_value,
            }
            for t in breached
        ],
        "regressions": [
            {
                "endpoint": t.endpoint,
                "metric": t.metric,
                "max_value": t.max_value,
                "current_value": round(t.current_value, 4),
            }
            for t in regressions
        ],
    }


def format_report(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("性能回归判定端到端结果")
    lines.append("=" * 48)
    lines.append("采集端点: %s" % (", ".join(result["collected_endpoints"]) or "无"))
    lines.append("预算违反: %d 项" % len(result["breached"]))
    for item in result["breached"]:
        lines.append("  - %s %s 当前=%.1f 上限=%.1f" % (
            item["endpoint"], item["metric"], item["current_value"], item["max_value"]))
    lines.append("性能回归: %d 项" % len(result["regressions"]))
    for item in result["regressions"]:
        lines.append("  - %s p95 劣化倍数=%.2f 阈值=%.2f" % (
            item["endpoint"], item["current_value"], item["max_value"]))
    lines.append("-" * 48)
    if result["breached"]:
        lines.append("结论: FAIL（存在预算违反）")
    elif result["regressions"]:
        lines.append("结论: FAIL（存在性能回归）")
    else:
        lines.append("结论: PASS（无预算违反、无回归）")
    return "\n".join(lines)


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _records_from_dicts(items: List[Dict[str, Any]]) -> List[PerfBaselineRecord]:
    return [
        PerfBaselineRecord(
            endpoint=str(it["endpoint"]),
            method=str(it.get("method", "span")),
            p50_ms=float(it.get("p50_ms", 0.0)),
            p95_ms=float(it.get("p95_ms", 0.0)),
            p99_ms=float(it.get("p99_ms", 0.0)),
            rps=float(it.get("rps", 0.0)),
            tps=float(it.get("tps", 0.0)),
            sample_count=int(it.get("sample_count", 0)),
            collected_at=float(it.get("collected_at", 0.0)),
        )
        for it in items
    ]


def main(argv: List[str] | None = None) -> int:
    import asyncio

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spans-json", help="新构建的 span 记录 JSON 数组（{name,duration_ms,finished_at}）")
    parser.add_argument("--historical-json", help="历史基线 JSON（PerfBaselineRecord 列表）")
    parser.add_argument("--baselines-yaml", default="benchmarks/perf_baselines/baselines.yaml")
    parser.add_argument("--service", default="chat-api")
    args = parser.parse_args(argv)

    if not args.spans_json or not args.historical_json:
        print("需要 --spans-json 与 --historical-json。", file=sys.stderr)
        return 3

    spans = load_json(args.spans_json)
    historical = _records_from_dicts(load_json(args.historical_json))

    collector = PerfBaselineCollector()
    checker = PerfBudgetChecker(service_name=args.service)

    async def _load() -> None:
        await checker.load_thresholds(args.baselines_yaml)

    try:
        asyncio.run(_load())
    except FileNotFoundError as exc:
        print("缺少阈值文件: %s" % exc, file=sys.stderr)
        return 3

    result = asyncio.run(run_chain(collector, checker, spans, historical))
    print(format_report(result))
    if result["breached"]:
        return 1
    if result["regressions"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())