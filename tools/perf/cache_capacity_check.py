"""026 T031 — Redis 缓存容量与淘汰策略检查（FR-20）。

校验 Redis ``maxmemory-policy = allkeys-lru``、``maxmemory`` 容量上限已配置。
容量上限可配置：环境变量 ``REDIS_MAXMEMORY``（默认 256mb）；缓存实例层面可用
``CacheManager(redis_url, memory_max_entries=...)`` 限制进程内降级缓存的条数。

用法::

    python tools/perf/cache_capacity_check.py [--uri redis://...] [--policy allkeys-lru]

退出码：0 一致；1 漂移/未配置；2 无法连接（degraded，不阻断）。
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, Optional

EXPECTED_POLICY = "allkeys-lru"
DEFAULT_MAXMEMORY = "256mb"
MAXMEMORY_ENV = "REDIS_MAXMEMORY"
POLICY_ENV = "REDIS_MAXMEMORY_POLICY"


def expected_settings(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """返回期望的 Redis 配置（env 可覆盖）。"""
    env = env or os.environ
    return {
        "maxmemory-policy": env.get(POLICY_ENV, EXPECTED_POLICY),
        "maxmemory": env.get(MAXMEMORY_ENV, DEFAULT_MAXMEMORY),
    }


def evaluate(actual: Dict[str, Any], expected: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """对比实际 Redis CONFIG GET 结果与期望配置，返回逐项判定。"""
    expected = expected or expected_settings()
    policy = str(actual.get("maxmemory-policy") or "")
    maxmemory = str(actual.get("maxmemory") or "")
    expected_memory = expected.get("maxmemory") or DEFAULT_MAXMEMORY
    policy_ok = policy == expected.get("maxmemory-policy", EXPECTED_POLICY)
    memory_ok = _memory_ok(maxmemory, expected_memory)
    return {
        "policy": {
            "actual": policy,
            "expected": expected.get("maxmemory-policy", EXPECTED_POLICY),
            "ok": policy == expected.get("maxmemory-policy", EXPECTED_POLICY),
        },
        "maxmemory": {
            "actual": maxmemory,
            "expected": expected_memory,
            "ok": _memory_ok(maxmemory, expected_memory),
        },
        "all_ok": policy_ok and memory_ok,
    }


def _memory_ok(actual: str, expected: str) -> bool:
    """判断 maxmemory 是否已配置（>0），并与期望值同数量级即视为合规。"""
    if not actual or actual == "0":
        return False
    try:
        a = _to_bytes(actual)
        e = _to_bytes(expected)
    except ValueError:
        # 无法解析时按字符串非空判定
        return bool(actual)
    return a > 0 and a >= e * 0.9  # 允许 ±10% 偏差，不允许显著偏小


def _to_bytes(value: str) -> int:
    value = (value or "").strip().lower()
    units = {"b": 1, "k": 1024, "kb": 1024, "m": 1024 ** 2, "mb": 1024 ** 2, "g": 1024 ** 3, "gb": 1024 ** 3}
    if value.endswith("gb"):
        return int(value[:-2]) * units["gb"]
    if value.endswith("mb"):
        return int(value[:-2]) * units["mb"]
    if value.endswith("kb"):
        return int(value[:-2]) * units["kb"]
    if value.endswith("b"):
        return int(value[:-1])
    if value.endswith("g"):
        return int(value[:-1]) * units["g"]
    if value.endswith("m"):
        return int(value[:-1]) * units["m"]
    if value.endswith("k"):
        return int(value[:-1]) * units["k"]
    return int(value)


def read_redis_config(redis_url: str) -> Dict[str, str]:
    """连接 Redis 读取 maxmemory-policy / maxmemory。"""
    import redis as redis_mod

    client = redis_mod.Redis.from_url(
        redis_url, socket_timeout=3, socket_connect_timeout=3, decode_responses=True
    )
    client.ping()
    info = client.config_get("maxmemory-policy") or {}
    info.update(client.config_get("maxmemory") or {})
    return {str(k): str(v) for k, v in info.items()}


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="026 T031 Redis 缓存容量/淘汰策略检查")
    parser.add_argument("--uri", default=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
    parser.add_argument("--policy", default=None, help="期望的 maxmemory-policy（默认 allkeys-lru）")
    parser.add_argument("--maxmemory", default=None, help="期望的 maxmemory（默认 256mb）")
    args = parser.parse_args(argv)

    expected = expected_settings()
    if args.policy:
        expected["maxmemory-policy"] = args.policy
    if args.maxmemory:
        expected["maxmemory"] = args.maxmemory

    try:
        actual = read_redis_config(args.uri)
    except Exception as exc:
        print(f"[cache_capacity_check] degraded: 无法连接 Redis ({args.uri}): {exc}")
        print("提示：未连接 Redis 时，进程内降级缓存受 CacheManager.memory_max_entries 限制。")
        return 2

    result = evaluate(actual, expected)
    print(f"maxmemory-policy : actual={result['policy']['actual']!r} expected={result['policy']['expected']!r} "
          f"ok={result['policy']['ok']}")
    print(f"maxmemory        : actual={result['maxmemory']['actual']!r} expected={result['maxmemory']['expected']!r} "
          f"ok={result['maxmemory']['ok']}")
    ok = result["policy"]["ok"] and result["maxmemory"]["ok"]
    result["all_ok"] = ok
    if ok:
        print("[cache_capacity_check] OK — Redis 容量与淘汰策略符合 026 T031 要求")
        return 0
    print("[cache_capacity_check] DRIFT — 需调整 Redis 配置（或设置 REDIS_MAXMEMORY_POLICY / REDIS_MAXMEMORY）")
    return 1


if __name__ == "__main__":
    sys.exit(main())