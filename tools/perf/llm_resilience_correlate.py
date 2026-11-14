#!/usr/bin/env python3
"""026 T053 — LLM 耗时占比与 007 韧性事件交叉归因。

将 chat-api 的外部依赖耗时拆分（``execution_trace.PerfBreakdown``，kind="llm"）
与 ``token_usage_logs`` 中 007 写入的韧性事件字段（``resilience_events``:
failover_from/failover_to/degradation_step）通过 ``trace_id`` 关联，回答：

- 哪些请求的 LLM 耗时占比异常高，且同时发生了 failover/降级？
- 降级发生时 LLM 耗时占比是否有系统性抬升（韧性事件是否影响性能）？

纯函数设计，便于单测与 CI 复用；DB 访问仅通过可选 ``load_token_records``
（需 motor client，未提供时 CLI 走 JSON 文件输入）。

用法::

    python3 tools/perf/llm_resilience_correlate.py --records-json r.json --breakdown-json b.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 判定"高 LLM 耗时占比"的阈值（LLM 占总耗时 share）
HIGH_LLM_SHARE = 0.5

# 韧性事件字段（007 FR-7，落 token_usage_logs.resilience_events）
RESILIENCE_KEYS = ("failover_from", "failover_to", "degradation_step")


@dataclass
class CorrelationRow:
    """单条交叉归因结果。"""

    trace_id: str
    request_id: str
    llm_share: float
    llm_ms: float
    request_ms: float
    resilience_events: Dict[str, Any] = field(default_factory=dict)
    high_llm_share: bool = False


def pick_llm_item(breakdown: Any) -> Optional[Any]:
    """从 PerfBreakdown 中取 kind=="llm" 的统计项。"""
    for item in getattr(breakdown, "items", []) or []:
        if getattr(item, "kind", "") == "llm":
            return item
    return None


def llm_share_from_breakdown(breakdown: Any) -> float:
    """LLM 耗时占比 [0,1]；无 llm 项返回 0.0。"""
    item = pick_llm_item(breakdown)
    if item is None:
        return 0.0
    return float(getattr(item, "share", 0.0) or 0.0)


def correlate(
    breakdowns: Dict[str, Any],
    token_records: List[Dict[str, Any]],
    *,
    high_llm_share: float = HIGH_LLM_SHARE,
) -> List[CorrelationRow]:
    """按 trace_id 关联耗时占比与韧性事件。

    ``breakdowns``：``{trace_id: PerfBreakdown}``（trace_id 空串忽略）。
    ``token_records``：``token_usage_logs`` 行字典，仅含 ``resilience_events``
    非空且 ``trace_id`` 命中的行会产生结果。
    """
    rows: List[CorrelationRow] = []
    for record in token_records or []:
        trace_id = str(record.get("trace_id") or "").strip()
        if not trace_id:
            continue
        events = record.get("resilience_events") or {}
        if not isinstance(events, dict) or not events:
            continue
        breakdown = breakdowns.get(trace_id)
        share = llm_share_from_breakdown(breakdown) if breakdown is not None else None
        llm_ms = 0.0
        request_ms = 0.0
        if breakdown is not None:
            llm_item = pick_llm_item(breakdown)
            llm_ms = float(getattr(llm_item, "total_ms", 0.0) or 0.0)
            request_ms = float(getattr(breakdown, "request_duration_ms", 0.0) or 0.0)
        rows.append(
            CorrelationRow(
                trace_id=trace_id,
                request_id=str(record.get("request_id") or ""),
                llm_share=share if share is not None else -1.0,
                llm_ms=llm_ms,
                request_ms=request_ms,
                resilience_events=dict(events),
                high_llm_share=share is not None and share >= high_llm_share,
            )
        )
    return rows


def summarize(rows: List[CorrelationRow]) -> Dict[str, Any]:
    """汇总交叉归因结论。"""
    total = len(rows)
    high = [r for r in rows if r.high_llm_share]
    degraded = [r for r in rows if r.resilience_events.get("degradation_step") is not None]
    steps: Dict[str, int] = {}
    for r in degraded:
        key = str(r.resilience_events.get("degradation_step"))
        steps[key] = steps.get(key, 0) + 1
    shares = [r.llm_share for r in rows if r.llm_share >= 0]
    avg_share = (sum(shares) / len(shares)) if shares else 0.0
    return {
        "correlated_rows": total,
        "high_llm_share_rows": len(high),
        "degraded_rows": len(degraded),
        "degradation_step_distribution": steps,
        "avg_llm_share": round(avg_share, 4),
        "high_share_threshold": HIGH_LLM_SHARE,
    }


def format_report(rows: List[CorrelationRow], summary: Dict[str, Any]) -> str:
    """人类可读报告。"""
    lines: List[str] = []
    lines.append("LLM 耗时占比 × 韧性事件交叉归因报告")
    lines.append("=" * 46)
    lines.append(
        "高 LLM 占比阈值: share ≥ %.2f" % summary["high_share_threshold"]
    )
    lines.append("关联命中: %d 行 | 高占比: %d | 降级: %d | 平均 share: %.2f" % (
        summary["correlated_rows"],
        summary["high_llm_share_rows"],
        summary["degraded_rows"],
        summary["avg_llm_share"],
    ))
    lines.append("")
    for row in rows:
        flag = "[高]" if row.high_llm_share else "    "
        lines.append(
            "%s trace=%s share=%.2f llm_ms=%.0f req_ms=%.0f events=%s" % (
                flag,
                row.trace_id or "(空)",
                row.llm_share,
                row.llm_ms,
                row.request_ms,
                json.dumps(row.resilience_events, ensure_ascii=False),
            )
        )
    return "\n".join(lines)


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records-json", help="token_usage_logs 行 JSON 数组（含 trace_id/resilience_events）")
    parser.add_argument("--breakdown-json", help="{trace_id: PerfBreakdown dict} JSON")
    parser.add_argument("--demo", action="store_true", help="打印内置示例并退出")
    args = parser.parse_args(argv)

    if args.demo:
        demo_rows = [
            CorrelationRow(
                trace_id="trace-a",
                request_id="llm_abc",
                llm_share=0.82,
                llm_ms=4100,
                request_ms=5000,
                resilience_events={"failover_from": "model-a", "degradation_step": 2},
                high_llm_share=True,
            ),
            CorrelationRow(
                trace_id="trace-b",
                request_id="llm_def",
                llm_share=0.15,
                llm_ms=150,
                request_ms=1000,
                resilience_events={},
            ),
        ]
        print(format_report(demo_rows, summarize(demo_rows)))
        return 0

    if not args.records_json or not args.breakdown_json:
        print("需要 --records-json 与 --breakdown-json（或 --demo）。", file=sys.stderr)
        return 2

    records = load_json(args.records_json)
    raw_breakdowns = load_json(args.breakdown_json)

    # JSON 输入转为轻量对象（与 PerfBreakdown 鸭子类型兼容）
    class _Item:
        def __init__(self, d: Dict[str, Any]) -> None:
            self.kind = d.get("kind")
            self.total_ms = d.get("total_ms", 0.0)
            self.share = d.get("share", 0.0)

    class _Breakdown:
        def __init__(self, d: Dict[str, Any]) -> None:
            self.items = [_Item(x) for x in d.get("items", [])]
            self.request_duration_ms = d.get("request_duration_ms")

    breakdowns = {tid: _Breakdown(d) for tid, d in (raw_breakdowns or {}).items()}
    rows = correlate(breakdowns, records)
    print(format_report(rows, summarize(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())