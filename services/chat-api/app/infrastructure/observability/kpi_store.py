from __future__ import annotations

import asyncio
import time
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Tuple


# 026 性能采集参数（可按部署调优；对齐 spec.md Clarify：P95 回归判定窗口）
PERF_WINDOW_SECONDS = 60          # 延迟/吞吐滚动窗口
PERF_BUCKET_SECONDS = 10          # 滚动窗口分桶粒度
PERF_MAX_SAMPLES_PER_BUCKET = 5000  # 单桶样本上限（超限丢弃，避免内存无限增长）
PERF_INFLIGHT_WINDOW_SECONDS = 60    # 并发观测窗口

# 并发分档（spec.md T007：按并发 1 / 10 / 50 / 100 观测吞吐）
PERF_CONCURRENCY_BUCKETS: Tuple[int, ...] = (1, 10, 50, 100)


class RuntimeKPIStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._counters: Dict[str, float] = {
            "checkpoint_resume_success_rate": 0.0,
            "mean_steps_to_success": 0.0,
            "mean_retries_per_step": 0.0,
            "tool_denied_rate": 0.0,
            "suspend_to_resume_conversion": 0.0,
            "browser_action_failure_top_locators": 0.0,
            "exactly_once_reuse_rate": 0.0,
            "_tool_total": 0.0,
            "_tool_denied": 0.0,
            "_reuse_hit": 0.0,
            "_suspend_total": 0.0,
            "_resume_total": 0.0,
            "_success_steps": 0.0,
            "_success_runs": 0.0,
            "_checkpoint_resume_total": 0.0,
            "_checkpoint_resume_ok": 0.0,
            "_retry_total": 0.0,
            "_retry_steps": 0.0,
        }
        self._updated_at = datetime.now(tz=timezone.utc)
        # ── 026 性能采集状态（延迟分位数 / 并发 / 吞吐）────────────────────────────
        # key: f"{endpoint}|{method}"；inner: {bucket_ts: [latency_ms, ...]}
        self._latency_buckets: Dict[str, Dict[int, List[float]]] = {}
        # key: f"{endpoint}|{method}"；值 = 滚动窗口内总请求数
        self._request_count: Dict[str, float] = {}
        # 当前在处理请求数（gauge）
        self._inflight = 0
        # 瞬时并发观测 (ts, inflight)，用于按并发档聚合吞吐
        self._inflight_history: deque = deque(maxlen=4096)

    async def incr(self, key: str, value: float = 1.0) -> None:
        async with self._lock:
            self._counters[key] = float(self._counters.get(key, 0.0) + value)
            self._recompute()

    async def set_value(self, key: str, value: float) -> None:
        async with self._lock:
            self._counters[key] = float(value)
            self._recompute()

    async def snapshot(self) -> Dict[str, float]:
        async with self._lock:
            data = deepcopy(self._counters)
            data["updated_at"] = self._updated_at.timestamp()
            return data

    def _recompute(self) -> None:
        tool_total = max(1.0, float(self._counters.get("_tool_total", 0.0)))
        self._counters["tool_denied_rate"] = float(self._counters.get("_tool_denied", 0.0)) / tool_total
        self._counters["exactly_once_reuse_rate"] = float(self._counters.get("_reuse_hit", 0.0)) / tool_total
        suspend_total = max(1.0, float(self._counters.get("_suspend_total", 0.0)))
        self._counters["suspend_to_resume_conversion"] = float(self._counters.get("_resume_total", 0.0)) / suspend_total
        success_runs = max(1.0, float(self._counters.get("_success_runs", 0.0)))
        self._counters["mean_steps_to_success"] = float(self._counters.get("_success_steps", 0.0)) / success_runs
        resume_total = max(1.0, float(self._counters.get("_checkpoint_resume_total", 0.0)))
        self._counters["checkpoint_resume_success_rate"] = float(self._counters.get("_checkpoint_resume_ok", 0.0)) / resume_total
        retry_steps = max(1.0, float(self._counters.get("_retry_steps", 0.0)))
        self._counters["mean_retries_per_step"] = float(self._counters.get("_retry_total", 0.0)) / retry_steps
        self._updated_at = datetime.now(tz=timezone.utc)

    # ── 026 性能采集：延迟 / 并发 / 吞吐 ──────────────────────────────────────────

    async def enter_request(self, endpoint: str, method: str) -> None:
        """请求进入：并发 +1，并记录瞬时并发观测（供并发分档）。"""
        async with self._lock:
            self._inflight += 1
            self._inflight_history.append((time.time(), self._inflight))

    async def leave_request(
        self, endpoint: str, method: str, latency_ms: float, *, status: int = 200
    ) -> None:
        """请求离开：并发 -1，写入滚动延迟桶与请求计数。"""
        async with self._lock:
            self._inflight -= 1
            key = f"{endpoint}|{method}"
            buckets = self._latency_buckets.setdefault(key, {})
            bucket_ts = int(time.time()) // PERF_BUCKET_SECONDS * PERF_BUCKET_SECONDS
            bucket = buckets.setdefault(bucket_ts, [])
            if len(bucket) < PERF_MAX_SAMPLES_PER_BUCKET:
                bucket.append(float(latency_ms))
            self._request_count[key] = float(self._request_count.get(key, 0.0) + 1)
            # 状态码计数（`status:` 前缀键，供失败率统计）
            self._request_count[f"status:{status}"] = float(
                self._request_count.get(f"status:{status}", 0.0) + 1
            )
            self._prune_buckets(buckets)

    def _prune_buckets(self, buckets: Dict[int, List[float]]) -> None:
        """丢弃超出滚动窗口的桶。调用方须持锁。"""
        cutoff = int(time.time()) // PERF_BUCKET_SECONDS * PERF_BUCKET_SECONDS - PERF_WINDOW_SECONDS
        stale = [ts for ts in buckets if ts < cutoff]
        for ts in stale:
            del buckets[ts]

    def latency_percentiles(self, endpoint: str, method: str) -> Dict[str, float]:
        """滚动窗口内某端点的延迟分位数（P50/P95/P99/P999）+ 样本数。

        同步方法（调用方持锁）；无样本返回全 0 且 count=0。
        """
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

    def throughput(self, endpoint: str | None = None) -> Dict[str, float]:
        """滚动窗口吞吐（RPS 按端点；TPS 近似 = RPS，因单请求单事务）。

        concurrency 分档：按并发 1 / 10 / 50 / 100 观测（spec.md T007）。
        """
        now = time.time()
        window_start = now - PERF_WINDOW_SECONDS
        rps_total = 0.0
        per_concurrency: Dict[str, float] = {}
        for key, count in self._request_count.items():
            if key.startswith("status:"):
                continue
            rps_total += float(count)
            if endpoint and not key.startswith(f"{endpoint}|"):
                continue
        per_endpoint: Dict[str, float] = {}
        for key, count in self._request_count.items():
            if key.startswith("status:"):
                continue
            per_endpoint[key] = float(count) / PERF_WINDOW_SECONDS
        # 并发分档：取滚动窗口内每个并发档位观测到的最大瞬时并发，并统计该档请求
        for ts, inflight in self._inflight_history:
            if ts < window_start:
                continue
            bucket = self._concurrency_bucket(inflight)
            per_concurrency[bucket] = float(per_concurrency.get(bucket, 0.0)) + 1
        return {
            "rps_total": rps_total / PERF_WINDOW_SECONDS,
            "tps_total": rps_total / PERF_WINDOW_SECONDS,
            "per_endpoint": per_endpoint,
            "rps_by_concurrency": {
                bucket: per_concurrency.get(bucket, 0.0) / PERF_WINDOW_SECONDS
                for bucket in self._concurrency_labels()
            },
        }

    @staticmethod
    def _concurrency_bucket(inflight: int) -> str:
        """把瞬时并发映射到最近的不超过它的档位标签。"""
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

    def perf_summary(self) -> Dict[str, object]:
        """性能摘要（供 debug/kpi 端点与告警读取）。"""
        summary: Dict[str, object] = {
            "inflight": self._inflight,
            "request_count_total": sum(
                c for k, c in self._request_count.items() if not k.startswith("status:")
            ),
            "endpoints": len(self._latency_buckets),
            "updated_at": self._updated_at.timestamp(),
        }
        # 端点延迟分位数（最多取 20 个端点，避免 debug 端点输出膨胀）
        top: List[Tuple[float, str]] = []
        for key, count in self._request_count.items():
            if key.startswith("status:"):
                continue
            top.append((float(count), key))
        top.sort(reverse=True)
        percentiles: Dict[str, Dict[str, float]] = {}
        for _, key in top[:20]:
            endpoint, method = key.rsplit("|", 1)
            percentiles[key] = self.latency_percentiles(endpoint, method)
        summary["endpoint_percentiles"] = percentiles
        summary["throughput"] = self.throughput()
        return summary
