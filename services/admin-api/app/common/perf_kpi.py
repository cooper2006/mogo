"""026 T012/T013 — 性能 KPI 采集器 + 埋点中间件（三服务共用，vendored 副本）。

权威源：`services/common/perf_kpi.py`。三服务 `app/common/perf_kpi.py` 是本文件的
字节一致 vendored 副本（同步脚本 `tools/perf/sync_common.py` 或手改后保持一致）。

设计要点：
* `RequestKPIStore` 是**进程内**滚动统计：延迟分位数、并发 gauge、吞吐 RPS/TPS。
  窗口与分桶参数可调（对齐 spec.md Clarify：P95 窗口/回归判定口径）。
* `PerfMiddleware` 用 `BaseHTTPMiddleware`（埋点开销本身会进分位数，需在 CI
  回归里留出噪声预算；如需 <5ms 开销请改用纯 ASGI，见 023 resilience 的注释）。
* 中间件与 store 解耦：store 由调用方注入（chat-api 复用
  `RuntimeKPIStore`，其 `enter_request/leave_request/latency_percentiles/
  throughput/perf_summary` 与本站点协议一致）。
* 埋点失败绝不影响业务响应（`finally` + 吞异常）。
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

PERF_WINDOW_SECONDS = 60            # 延迟/吞吐滚动窗口
PERF_BUCKET_SECONDS = 10            # 滚动窗口分桶粒度
PERF_MAX_SAMPLES_PER_BUCKET = 5000  # 单桶样本上限
PERF_CONCURRENCY_BUCKETS: Tuple[int, ...] = (1, 10, 50, 100)  # 并发分档


class RequestKPIStore:
    """进程内请求级 KPI 采集器（延迟分位数 / 并发 / 吞吐）。"""

    def __init__(
        self,
        *,
        window_seconds: int = PERF_WINDOW_SECONDS,
        bucket_seconds: int = PERF_BUCKET_SECONDS,
        max_samples_per_bucket: int = PERF_MAX_SAMPLES_PER_BUCKET,
    ) -> None:
        self._lock = asyncio.Lock()
        self._window = window_seconds
        self._bucket = bucket_seconds
        self._max_samples = max_samples_per_bucket
        self._latency_buckets: Dict[str, Dict[int, List[float]]] = {}
        self._request_count: Dict[str, float] = {}
        self._inflight = 0
        self._inflight_history: deque = deque(maxlen=4096)
        self._updated_at = datetime.now(tz=timezone.utc)

    # ── 埋点 ────────────────────────────────────────────────────────────────────

    async def enter_request(self, endpoint: str, method: str) -> None:
        async with self._lock:
            self._inflight += 1
            self._inflight_history.append((time.time(), self._inflight))

    async def leave_request(
        self,
        endpoint: str,
        method: str,
        latency_ms: float,
        *,
        status: int = 200,
    ) -> None:
        async with self._lock:
            self._inflight -= 1
            key = f"{endpoint}|{method}"
            buckets = self._latency_buckets.setdefault(key, {})
            bucket_ts = int(time.time()) // self._bucket * self._bucket
            bucket = buckets.setdefault(bucket_ts, [])
            if len(bucket) < self._max_samples:
                bucket.append(float(latency_ms))
            self._request_count[key] = float(self._request_count.get(key, 0.0) + 1)
            self._request_count[f"status:{status}"] = float(
                self._request_count.get(f"status:{status}", 0.0) + 1
            )
            cutoff = bucket_ts - self._window
            for stale in [ts for ts in buckets if ts < cutoff]:
                del buckets[stale]
            self._updated_at = datetime.now(tz=timezone.utc)

    # ── 读取 ────────────────────────────────────────────────────────────────────

    def latency_percentiles(self, endpoint: str, method: str) -> Dict[str, float]:
        buckets = self._latency_buckets.get(f"{endpoint}|{method}") or {}
        samples: List[float] = []
        for bucket in buckets.values():
            samples.extend(bucket)
        samples.sort()
        if not samples:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "p999": 0.0, "count": 0.0}
        n = len(samples)

        def _percentile(q: float) -> float:
            idx = int(round(q * (n - 1)))
            return float(samples[min(max(idx, 0), n - 1)])

        return {
            "p50": _percentile(0.50),
            "p95": _percentile(0.95),
            "p99": _percentile(0.99),
            "p999": _percentile(0.999),
            "count": float(n),
        }

    def throughput(self) -> Dict[str, Any]:
        total = sum(c for k, c in self._request_count.items() if not k.startswith("status:"))
        per_endpoint: Dict[str, float] = {}
        for key, count in self._request_count.items():
            if key.startswith("status:"):
                continue
            per_endpoint[key] = float(count) / self._window
        now = time.time()
        per_concurrency: Dict[str, float] = {}
        for ts, inflight in self._inflight_history:
            if ts < now - self._window:
                continue
            bucket = self._concurrency_bucket(inflight)
            per_concurrency[bucket] = float(per_concurrency.get(bucket, 0.0)) + 1
        return {
            "rps_total": total / self._window,
            "tps_total": total / self._window,
            "per_endpoint": per_endpoint,
            "rps_by_concurrency": {
                bucket: per_concurrency.get(bucket, 0.0) / self._window
                for bucket in self._concurrency_labels()
            },
        }

    def snapshot(self) -> Dict[str, float]:
        """与既有 `RuntimeKPIStore.snapshot()` 同形（含 updated_at）。"""
        data = {"updated_at": self._updated_at.timestamp()}
        return data

    def perf_summary(self) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "inflight": self._inflight,
            "request_count_total": sum(
                c for k, c in self._request_count.items() if not k.startswith("status:")
            ),
            "endpoints": len(self._latency_buckets),
            "updated_at": self._updated_at.timestamp(),
        }
        top: List[Tuple[float, str]] = sorted(
            (
                (float(c), k)
                for k, c in self._request_count.items()
                if not k.startswith("status:")
            ),
            reverse=True,
        )
        percentiles: Dict[str, Dict[str, float]] = {}
        for _, key in top[:20]:
            endpoint, method = key.rsplit("|", 1)
            percentiles[key] = self.latency_percentiles(endpoint, method)
        summary["endpoint_percentiles"] = percentiles
        summary["throughput"] = self.throughput()
        return summary

    @staticmethod
    def _concurrency_bucket(inflight: int) -> str:
        if inflight <= 1:
            return "1"
        if inflight <= 10:
            return "10"
        if inflight <= 50:
            return "50"
        return "100"

    @staticmethod
    def _concurrency_labels() -> Tuple[str, ...]:
        return tuple(str(b) for b in PERF_CONCURRENCY_BUCKETS)


def default_endpoint(request: Request) -> str:
    """端点标识：去掉 `/api/v1`（或 `/api`）前缀，便于与 baselines.yaml 对齐。"""
    path = request.url.path
    for prefix in ("/api/v1", "/api"):
        if path == prefix:
            return "/"
        if path.startswith(prefix + "/"):
            return path[len(prefix):]
    return path


class PerfMiddleware(BaseHTTPMiddleware):
    """请求延迟/并发/吞吐埋点中间件。`store` 实现
    `enter_request` / `leave_request`（鸭子类型，可由调用方替换）。"""

    def __init__(self, app: Any, store: Any) -> None:
        super().__init__(app)
        self._store = store

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        endpoint = default_endpoint(request)
        method = request.method
        start = time.perf_counter()
        try:
            await self._store.enter_request(endpoint, method)
        except Exception:  # noqa: BLE001
            pass
        status = 200
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            latency_ms = (time.perf_counter() - start) * 1000.0
            try:
                await self._store.leave_request(endpoint, method, latency_ms, status=status)
            except Exception:  # noqa: BLE001 — 埋点失败不阻断请求
                pass


# 兼容旧名
PerfMonitoringMiddleware = PerfMiddleware