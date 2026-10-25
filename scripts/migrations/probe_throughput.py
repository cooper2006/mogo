#!/usr/bin/env python3
"""024 T059 (FR-031)：迁移执行不阻塞线上验证。

迁移进行期间持续对线上服务发探测请求，统计每分钟吞吐（成功请求数/分钟）。
当前窗口吞吐低于基线窗口 (1 - threshold) 比例即判定"迁移阻塞了线上"，中止迁移。

用法：
  probe_throughput.py --url http://localhost:8000/health [--interval 1.0] [--window 60]
                      [--baseline-seconds 180] [--threshold 0.2] [--duration 120]
                      [--migration-cmd "python3 scripts/migrations/0001_x.py"]
                      [--dry-run] [--json]

--dry-run：不实际发请求，用模拟延迟生成吞吐，用于验证脚本判定逻辑。
退出码：0 通过（未检测到阻塞）；1 检测到阻塞（应中止迁移）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request


def _request_once(url: str, timeout: float = 3.0) -> bool:
    """返回一次探测是否成功（2xx 视为成功）。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _simulate(interval: float, total_seconds: float):
    """模拟基线：成功率 0.98，延迟略随机，供 --dry-run 用。"""
    import random
    start = time.time()
    ok = 0
    n = 0
    while time.time() - start < total_seconds:
        n += 1
        if random.random() < 0.98:
            ok += 1
        time.sleep(interval * random.uniform(0.9, 1.1))
    return ok, n


def main() -> int:
    ap = argparse.ArgumentParser(description="迁移期间线上吞吐探测（FR-031）")
    ap.add_argument("--url", help="探测端点（GET，2xx 计成功）")
    ap.add_argument("--interval", type=float, default=1.0, help="探测间隔秒（默认 1）")
    ap.add_argument("--window", type=float, default=60.0, help="吞吐统计窗口秒（默认 60）")
    ap.add_argument("--baseline-seconds", type=float, default=180.0, help="基线窗口秒（默认 180）")
    ap.add_argument("--threshold", type=float, default=0.2, help="允许吞吐下降比例（默认 0.2）")
    ap.add_argument("--duration", type=float, default=120.0, help="迁移期总探测时长秒（默认 120）")
    ap.add_argument("--migration-cmd", help="并行运行的迁移命令（可选，用于真实演练）")
    ap.add_argument("--dry-run", action="store_true", help="模拟吞吐，不发真实请求")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if not args.dry_run and not args.url:
        ap.error("--url 必填（或使用 --dry-run）")

    baseline_ok, baseline_n = 0.0, 0.0
    if args.dry_run:
        ok, n = _simulate(args.interval, args.baseline_seconds)
        baseline_ok, baseline_n = float(ok), float(n)
    else:
        start = time.time()
        while time.time() - start < args.baseline_seconds:
            if _request_once(args.url):
                baseline_ok += 1
            time.sleep(args.interval)

    baseline_rate = baseline_ok / max(baseline_seconds := max(args.baseline_seconds, 1e-6), 1e-6)

    # 启动迁移（若有）
    migration_proc = None
    if args.migration_cmd:
        migration_proc = subprocess.Popen(args.migration_cmd, shell=True)

    windows = []
    start = time.time()
    window_count = 0
    window_ok = 0
    window_start = time.time()
    blocked = False
    while time.time() - start < args.duration:
        if args.dry_run:
            time.sleep(args.interval * 0.99)
            window_ok += 1
        else:
            if _request_once(args.url):
                window_ok += 1
        now = time.time()
        if now - window_start >= args.window:
            rate = window_ok / args.window
            windows.append({"window": window_count, "throughput_per_min": round(window_ok / (args.window / 60.0), 2),
                            "rate_per_sec": round(rate, 3)})
            window_count += 1
            window_ok = 0
            window_start = now
            # 当前窗口速率与基线比较
            if rate < baseline_rate * (1 - args.threshold):
                blocked = True
                break
        time.sleep(args.interval * 0.1 if args.dry_run else 0)

    if migration_proc is not None:
        migration_proc.terminate()
        try:
            migration_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            migration_proc.kill()

    result = {
        "baseline_rate_per_sec": round(baseline_rate, 3),
        "threshold_drop": args.threshold,
        "blocked": blocked,
        "windows": windows,
        "verdict": "PASS 迁移未阻塞线上" if not blocked else "FAIL 迁移阻塞线上（应中止）",
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"基线吞吐: {result['baseline_rate_per_sec']} 请求/秒，允许下降 {args.threshold*100:.0f}%")
        for w in windows:
            print(f"  窗口{w['window']}: {w['throughput_per_min']} 请求/分 ({w['rate_per_sec']} req/s)")
        print("结论: " + result["verdict"])

    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())