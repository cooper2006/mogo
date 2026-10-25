"""026 T052 — 性能配置加载与一致性校验（FR-10/FR-28/FR-30）。

读取 `config/performance.yaml`（声明清单）与 `benchmarks/perf_baselines/baselines.yaml`
（性能预算基线），校验两者关键阈值一致，并对齐环境变量默认值。

用法::

    python3 tools/perf/config_loader.py                       # 打印配置摘要
    python3 tools/perf/config_loader.py --check               # 一致性校验，非零退出码=不一致
    python3 tools/perf/config_loader.py --check --json        # 校验结果 JSON

设计: 纯标准库（yaml 可选，缺失时给出明确错误），不依赖服务启动。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

DEFAULT_PERF = Path("config/performance.yaml")
DEFAULT_BASELINES = Path("benchmarks/perf_baselines/baselines.yaml")


def _load(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML 未安装（pip install pyyaml）")
    if not path.exists():
        raise FileNotFoundError(f"配置不存在: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} 顶层必须是映射")
    return data


# 环境变量覆盖映射：performance.yaml 路径 → (env 名, 目标类型)
ENV_OVERRIDES: list[tuple[list[str], str]] = [
    (["database", "mongodb", "max_pool_size"], "MONGODB_MAX_POOL_SIZE"),
    (["database", "mongodb", "min_pool_size"], "MONGODB_MIN_POOL_SIZE"),
    (["database", "mongodb", "max_idle_time_ms"], "MONGODB_MAX_IDLE_TIME_MS"),
    (["database", "mongodb", "socket_timeout_ms"], "MONGODB_SOCKET_TIMEOUT_MS"),
    (["database", "mongodb", "slow_query_threshold_ms"], "MONGODB_SLOW_QUERY_THRESHOLD_MS"),
    (["cache", "default_ttl_seconds"], "MOGO_CACHE_DEFAULT_TTL"),
    (["cache", "redis", "maxmemory"], "REDIS_MAXMEMORY"),
    (["cache", "redis", "eviction_policy"], "REDIS_MAXMEMORY_POLICY"),
    (["rate_limit", "default_rps"], "RATE_LIMIT_RPS"),
    (["rate_limit", "default_burst"], "RATE_LIMIT_BURST"),
    (["rate_limit", "max_concurrent"], "RATE_LIMIT_MAX_CONCURRENT"),
    (["backpressure", "max_depth"], "BACKPRESSURE_MAX_DEPTH"),
    (["frontend", "admin_max_gzip_kb"], "ADMIN_MAX_GZIP_KB"),
    (["frontend", "user_max_gzip_kb"], "USER_MAX_GZIP_KB"),
]


def _dig(d: dict[str, Any], path: list[str], default: Any = None) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key, default)
    return cur


def apply_env_overrides(cfg: dict[str, Any]) -> dict[str, dict[str, str]]:
    """扫描环境变量覆盖，返回 {路径: 值}（不修改 cfg）。"""
    applied: dict[str, dict[str, str]] = {}
    for path, env in ENV_OVERRIDES:
        raw = os.getenv(env)
        if raw is None:
            continue
        current = _dig(cfg, path)
        # 仅当显式配置与默认不同才记录（避免噪音）
        if current is not None and str(current) != raw:
            applied[".".join(path)] = {"env": env, "declared": str(current), "effective": raw}
    return applied


def check_consistency(perf: dict[str, Any], base: dict[str, Any]) -> list[str]:
    """校验 performance.yaml 与 baselines.yaml 阈值一致，返回差异说明列表。"""
    issues: list[str] = []

    def cmp(name: str, perf_val: Any, base_val: Any, base_key: str) -> None:
        if perf_val is None or base_val is None:
            issues.append(f"{name}: performance.yaml 缺失该键")
            return
        try:
            if abs(float(perf_val) - float(base_val)) > 1e-9:
                issues.append(
                    f"{name}: performance.yaml={perf_val} vs baselines.yaml[{base_key}]={base_val}"
                )
        except (TypeError, ValueError):
            issues.append(f"{name}: 类型不可比（{perf_val!r} / {base_val!r}）")

    # 连接池
    perf_pool = _dig(perf, ["database", "mongodb"], {})
    base_pool = _dig(base, ["database", "pool"], {})
    cmp("max_pool_size", perf_pool.get("max_pool_size"), base_pool.get("max_pool_size"), "database.pool.max_pool_size")
    cmp("min_pool_size", perf_pool.get("min_pool_size"), base_pool.get("min_pool_size"), "database.pool.min_pool_size")
    # 连接池峰值利用率
    cmp("peak_utilization_max", _dig(perf, ["baselines", "peak_connections_max_utilization"]),
        base_pool.get("peak_utilization_max"), "database.pool.peak_utilization_max")
    # 慢查询阈值
    cmp("slow_query_threshold_ms", perf_pool.get("slow_query_threshold_ms"),
        _dig(base, ["database", "slow_query_ms"]), "database.slow_query_ms")
    # 限流 rps 与队列深度
    chat_tp = _dig(base, ["services", "chat-api", "throughput"], {})
    cmp("rate_limit.default_rps", _dig(perf, ["rate_limit", "default_rps"]),
        chat_tp.get("max_rps_per_instance"), "services.chat-api.throughput.max_rps_per_instance")
    cmp("backpressure.max_depth", _dig(perf, ["backpressure", "max_depth"]),
        _dig(base, ["concurrency", "queue_depth_max"]), "concurrency.queue_depth_max")
    # 前端预算
    cmp("frontend.admin_max_gzip_kb", _dig(perf, ["frontend", "admin_max_gzip_kb"]),
        _dig(base, ["frontend", "admin-web", "bundle_gzip_max_kb"]), "frontend.admin-web.bundle_gzip_max_kb")
    cmp("frontend.user_max_gzip_kb", _dig(perf, ["frontend", "user_max_gzip_kb"]),
        _dig(base, ["frontend", "user-web", "bundle_gzip_max_kb"]), "frontend.user-web.bundle_gzip_max_kb")
    # 资源利用率
    cmp("memory_max_utilization", _dig(perf, ["baselines", "memory_max_utilization"]),
        _dig(base, ["resources", "memory_max_utilization"], 0.8), "resources.memory_max_utilization")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="性能配置加载与一致性校验（T052）")
    parser.add_argument("--yaml", type=Path, default=DEFAULT_PERF)
    parser.add_argument("--baselines", type=Path, default=DEFAULT_BASELINES)
    parser.add_argument("--check", action="store_true", help="执行一致性校验")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    try:
        perf = _load(args.yaml)
        base = _load(args.baselines)
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        print(f"❌ {exc}")
        return 2

    overrides = apply_env_overrides(perf)
    issues = check_consistency(perf, base)

    if args.json:
        print(json.dumps({
            "performance_yaml": str(args.yaml),
            "baselines_yaml": str(args.baselines),
            "env_overrides": overrides,
            "consistency_issues": issues,
            "consistent": not issues,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"✓ 加载 config/performance.yaml：{args.yaml}")
        print(f"✓ 加载 baselines.yaml：{args.baselines}")
        print(f"环境变量覆盖 {len(overrides)} 项")
        for path, info in overrides.items():
            print(f"  - {path}: {info['env']}={info['effective']}（声明 {info['declared']}）")
        if issues:
            print(f"✗ 一致性差异 {len(issues)} 项：")
            for i in issues:
                print(f"  - {i}")
        else:
            print("✓ 与 baselines.yaml 关键阈值一致")

    if args.check and issues:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())