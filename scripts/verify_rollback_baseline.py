#!/usr/bin/env python3
"""024 T048 (FR-026)：回滚后指标是否恢复基线的可核验校验器。

用法：
  verify_rollback_baseline.py --baseline-file <json> --post-file <json> [--tolerance 10]
  verify_rollback_baseline.py --url <prometheus> --metric <name> --before-window 5m --after-window 5m [--tolerance 10] [--json]

基线/回滚后指标文件形如：
  {"error_rate": 0.01, "p95_latency_ms": 320, "5xx_rate": 0.0005, "timeout_rate": 0.001, "availability": 0.999}

判定：|post - baseline| / |baseline| <= tolerance%（容差）。任一指标越界 → exit 1。
配合 deploy/cli/auto-rollback.sh 使用：回滚后调用本脚本确认指标已回到基线，闭环 FR-026。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.parse
import urllib.request


def _load_metrics(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _fetch_prom(url: str, metric: str, window: str) -> dict | None:
    """对 Prometheus 一个指标取最近窗口内的平均值（avg_over_time 语义近似）。"""
    query = f"avg_over_time({metric}[{window}])"
    params = urllib.parse.urlencode({"query": query, "time": int(time.time())})
    req = urllib.request.Request(f"{url.rstrip('/')}/api/v1/query?{params}", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
        res = data["data"]["result"]
        if not res:
            return None
        try:
            return float(res[0]["value"][1])
        except (TypeError, ValueError):
            return None
    except Exception:
        return None


def check(baseline: dict, post: dict, tolerance: float) -> dict:
    results = {}
    all_ok = True
    for key, base_val in baseline.items():
        if key not in post:
            results[key] = {"baseline": base_val, "post": None, "delta_pct": None, "ok": False, "reason": "missing in post"}
            all_ok = False
            continue
        post_val = post[key]
        if base_val in (None, 0) or math.isclose(base_val, 0.0):
            delta = None if post_val is None else (abs(post_val - base_val) if base_val != 0 else abs(post_val))
            ok = delta is not None and delta <= tolerance / 100.0 if base_val == 0 else delta is not None
            results[key] = {"baseline": base_val, "post": post_val, "delta_pct": None if post_val is None else round(delta * 100, 4), "ok": ok, "reason": "zero-baseline"}
            all_ok = all_ok and ok
            continue
        if post_val is None:
            results[key] = {"baseline": base_val, "post": None, "delta_pct": None, "ok": False, "reason": "post is null"}
            all_ok = False
            continue
        delta_pct = abs(post_val - base_val) / abs(base_val) * 100.0
        ok = delta_pct <= tolerance
        results[key] = {"baseline": base_val, "post": post_val, "delta_pct": round(delta_pct, 4), "ok": ok, "reason": ""}
        all_ok = all_ok and ok
    return {"ok": all_ok, "tolerance_pct": tolerance, "metrics": results}


def main() -> int:
    ap = argparse.ArgumentParser(description="校验回滚后指标是否回到基线（FR-026）")
    ap.add_argument("--baseline-file", help="回滚前基线指标 JSON 文件")
    ap.add_argument("--post-file", help="回滚后指标 JSON 文件")
    ap.add_argument("--url", help="Prometheus 地址（如 http://prometheus:9090）")
    ap.add_argument("--metric", help="--url 模式下要查询的单个指标名（PromQL 表达式）")
    ap.add_argument("--before-window", default="5m", help="回滚前窗口（--url 模式）")
    ap.add_argument("--after-window", default="5m", help="回滚后窗口（--url 模式）")
    ap.add_argument("--tolerance", type=float, default=10.0, help="允许的相对偏差百分比（默认 10）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if args.baseline_file and args.post_file:
        baseline = _load_metrics(args.baseline_file)
        post = _load_metrics(args.post_file)
    elif args.url and args.metric:
        baseline = {args.metric: _fetch_prom(args.url, args.metric, args.before_window)}
        post = {args.metric: _fetch_prom(args.url, args.metric, args.after_window)}
    else:
        ap.error("需要 --baseline-file/--post-file，或 --url/--metric")

    verdict = check(baseline, post, args.tolerance)
    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
    else:
        print(f"回滚后指标基线校验（容差 {args.tolerance}%）")
        for name, m in verdict["metrics"].items():
            mark = "OK  " if m["ok"] else "FAIL"
            print(f"  {mark} {name}: baseline={m['baseline']} post={m['post']} delta={m['delta_pct']}% {m['reason']}")
        print("结论: " + ("全部恢复基线，FR-026 通过" if verdict["ok"] else "存在越界指标，回滚未完全恢复"))

    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())