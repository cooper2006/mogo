"""023 T087 / T088 — 限流 + 背压接入（admin-api）。

中间件本体在 vendored 共享模块 :mod:`app.common.resilience_middleware`
（三服务共用一份权威源，见 `scripts/check_common_sync.py`）；本模块只负责
**服务侧接线**：读环境变量定阈值、持有进程内守卫实例、
把拒绝计数接到 prometheus 指标上（T088）。

阈值为何默认偏宽（200 qps / 200 并发 / 在途 1000）：
* 单机 Compose 形态下每副本各自计数（见 `RateLimiter` docstring 的口径说明），
  阈值过窄会在正常压测/批量任务下误伤；
* 真正生效的是**背压**（在途 1000）——过载时先拒绝而不是把队列堆到 OOM。
生产按 `MOGO_RATE_LIMIT_QPS` / `MOGO_RATE_LIMIT_MAX_CONCURRENT` /
`MOGO_BACKPRESSURE_MAX_DEPTH` 调整，或 `MOGO_RESILIENCE_MIDDLEWARE_ENABLED=0` 关闭。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.common.dependency_guard import BackpressureGuard, RateLimiter
from app.common.resilience_middleware import (
    BACKPRESSURE_CODE,
    RATE_LIMITED_CODE,
    ResilienceMiddleware,
)

logger = logging.getLogger(__name__)

SERVICE_NAME = "mogo-admin-api"


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("invalid %s=%r, fallback to %s", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, float(default)))


RATE_LIMIT_QPS = _env_float("MOGO_RATE_LIMIT_QPS", 200.0)
RATE_LIMIT_MAX_CONCURRENT = _env_int("MOGO_RATE_LIMIT_MAX_CONCURRENT", 200)
BACKPRESSURE_MAX_DEPTH = _env_int("MOGO_BACKPRESSURE_MAX_DEPTH", 1000)
ENABLED = os.getenv("MOGO_RESILIENCE_MIDDLEWARE_ENABLED", "1") not in {"0", "false", "False"}

#: 进程内守卫（单测可直接 import 这两个对象断言计数变化）。
rate_limiter = RateLimiter(qps=RATE_LIMIT_QPS, max_concurrent=RATE_LIMIT_MAX_CONCURRENT)
backpressure = BackpressureGuard(f"{SERVICE_NAME}:inbound", max_depth=BACKPRESSURE_MAX_DEPTH)

#: 由 lifespan 绑定，绑定前拒绝事件只记日志不计指标（中间件在启动前不会收到请求）。
_metrics: dict[str, Any] | None = None


def bind_metrics(metrics: dict[str, Any] | None) -> None:
    """把 ``register_resilience_metrics()`` 的返回字典接到拒绝计数钩子。"""
    global _metrics
    _metrics = metrics


def on_reject(code: str) -> None:
    """中间件拒绝回调：累加对应 counter（指标未绑定时静默跳过）。"""
    if _metrics is None:
        return
    try:
        if code == RATE_LIMITED_CODE:
            _metrics["rate_limit_rejections_total"].labels(reason=code).inc()
        elif code == BACKPRESSURE_CODE:
            _metrics["backpressure_rejections_total"].inc()
    except Exception:  # noqa: BLE001 - 指标异常不能反过来影响拒绝路径
        logger.debug("resilience metric increment failed", exc_info=True)


def middleware_kwargs() -> dict[str, Any]:
    """``app.add_middleware(ResilienceMiddleware, **middleware_kwargs())`` 的参数。"""
    return {
        "service_name": SERVICE_NAME,
        "rate_limiter": rate_limiter,
        "backpressure": backpressure,
        "enabled": ENABLED,
        "on_reject": on_reject,
    }


def reset_guards() -> None:
    """仅测试使用：清空在途计数与令牌桶，避免用例互相污染。"""
    backpressure.reset()
    for key in list(rate_limiter._inflight):  # noqa: SLF001 - 测试复位
        rate_limiter.forget(key)


__all__ = [
    "BACKPRESSURE_MAX_DEPTH",
    "ENABLED",
    "RATE_LIMIT_MAX_CONCURRENT",
    "RATE_LIMIT_QPS",
    "ResilienceMiddleware",
    "SERVICE_NAME",
    "backpressure",
    "bind_metrics",
    "middleware_kwargs",
    "on_reject",
    "rate_limiter",
    "reset_guards",
]
