#!/usr/bin/env python3
"""024 T105/T108 (FR-050)：业务量 → 资源需求换算，可复现的容量换算示例。

用法（示例输出见 docs/capacity-model.md §3）：
    python3 scripts/capacity_calc.py --users 1000 --qps 50 --data-gb-per-day 2
    python3 scripts/capacity_calc.py --users 5000 --qps 200 --data-gb-per-day 10 --days 30

参数：
    --users           日均活跃用户数（DAU）
    --qps             峰值 QPS
    --data-gb-per-day 日新增数据量（GiB）
    --days            预测天数（默认 30）
    --cpu-per-core-qps   单核可支撑 QPS（默认 80，经验值；见文档 §1）
    --mem-per-1000-users 每 1000 DAU 常驻内存（GiB，默认 1.5）
    --disk-now-gb    当前已用磁盘（GiB，默认 0）

输出：QPS 所需核数、内存、磁盘增长与到达水位阈值（80%/90%）的天数。
所有换算系数均为经验/示例值，真实部署用压测数据替换（见 T106，需远端环境）。
"""

import argparse


def human_gb(gb):
    if gb >= 1024:
        return f"{gb / 1024:.1f} TiB"
    return f"{gb:.1f} GiB"


def days_to_threshold(gb_per_day, now_gb, capacity_gb, threshold_pct):
    """从 now_gb 以 gb_per_day 增长到 capacity_gb * threshold_pct 所需天数。"""
    target = capacity_gb * threshold_pct / 100.0
    if now_gb >= target:
        return 0
    if gb_per_day <= 0:
        return None
    remaining = target - now_gb
    return remaining / gb_per_day


def main():
    p = argparse.ArgumentParser(description="容量换算示例（024 T105/T108）")
    p.add_argument("--users", type=int, default=1000)
    p.add_argument("--qps", type=int, default=50)
    p.add_argument("--data-gb-per-day", type=float, default=2.0)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--cpu-per-core-qps", type=int, default=80)
    p.add_argument("--mem-per-1000-users", type=float, default=1.5)
    p.add_argument("--disk-now-gb", type=float, default=0.0)
    p.add_argument("--disk-capacity-gb", type=float, default=500.0)
    args = p.parse_args()

    cores_for_qps = args.qps / args.cpu_per_core_qps
    cores_for_qps = max(cores_for_qps, 1)
    mem_gb = args.users / 1000.0 * args.mem_per_1000_users
    # 数据盘（mongo 卷）按增长率估算；warn=75% / crit=90%（watermarks.yml disk.data）
    warn_days = days_to_threshold(args.data_gb_per_day, args.disk_now_gb,
                                  args.disk_capacity_gb, 75)
    crit_days = days_to_threshold(args.data_gb_per_day, args.disk_now_gb,
                                  args.disk_capacity_gb, 90)

    print("业务量 → 资源需求换算（示例系数，真实值以压测为准）")
    print(f"  DAU            = {args.users} 人")
    print(f"  QPS            = {args.qps} req/s")
    print(f"  日增数据       = {args.data_gb_per_day} GiB/day")
    print("-- 换算结果 --")
    print(f"  所需 CPU 核数  = {cores_for_qps:.1f} 核 "
          f"({args.qps}/{args.cpu_per_core_qps} QPS/核)")
    print(f"  所需内存       = {mem_gb:.1f} GiB "
          f"({args.users}/1000 × {args.mem_per_1000_users} GiB)")
    print(f"  数据盘容量     = {args.disk_capacity_gb} GiB（当前 {args.disk_now_gb} GiB）")
    print(f"  到达 75%（warn）约 {warn_days if warn_days is not None else '∞'} 天")
    print(f"  到达 90%（crit）约 {crit_days if crit_days is not None else '∞'} 天")
    print("  扩容触发点：disk.data.used_percent 超过 warn(75) / crit(90)，"
          "见 deploy/monitoring/watermarks.yml")

    # 输出机器可读 JSON，供 CI / 文档校验复用（T108 可复现性）
    import json
    print("-- JSON --")
    print(json.dumps({
        "users": args.users, "qps": args.qps,
        "data_gb_per_day": args.data_gb_per_day,
        "cores": round(cores_for_qps, 1),
        "mem_gb": round(mem_gb, 1),
        "disk_warn_days": warn_days, "disk_crit_days": crit_days,
        "watermarks_warn_percent": 75, "watermarks_crit_percent": 90,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()