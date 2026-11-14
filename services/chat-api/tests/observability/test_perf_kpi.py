"""026 T012/T013 — 性能 KPI 采集器与埋点中间件测试。"""
from __future__ import annotations

import time
from typing import Any, Callable

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.common.perf_kpi import (
    PERF_WINDOW_SECONDS,
    PerfMiddleware,
    RequestKPIStore,
    default_endpoint,
)


def _make_app(store: RequestKPIStore, *, fail: bool = False) -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, str]:
        time.sleep(0.01)
        return {"ok": "yes"}

    @app.get("/api/v1/fail")
    async def fail_route() -> JSONResponse:
        return JSONResponse({"error": "boom"}, status_code=500)

    app.add_middleware(PerfMiddleware, store=store)
    return app


class TestRequestKPIStore:
    def test_latency_percentiles_empty(self) -> None:
        store = RequestKPIStore()
        got = store.latency_percentiles("/ping", "GET")
        assert got["count"] == 0.0
        assert got["p95"] == 0.0

    async def test_latency_percentiles_known_values(self) -> None:
        store = RequestKPIStore()
        for ms in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            await store.leave_request("/ping", "GET", ms, status=200)
        got = store.latency_percentiles("/ping", "GET")
        assert got["count"] == 10.0
        # 有序样本 [10..100]，n=10，idx = round(q*(n-1))：
        #   P50 → round(4.5)=4 → 50；P95 → round(8.55)=9 → 100；P99 → round(8.991)=9 → 100
        assert got["p50"] == pytest.approx(50.0)
        assert got["p95"] == pytest.approx(100.0)
        assert got["p99"] == pytest.approx(100.0)

    async def test_window_expires_old_samples(self) -> None:
        store = RequestKPIStore(window_seconds=5, bucket_seconds=5)
        # 写入一个当前桶样本
        await store.leave_request("/x", "GET", 1.0, status=200)
        # 模拟窗口滚动：写入一个远超窗口的桶时间戳（内部按 time.time() 分桶，
        # 无法直接注入历史桶，改为验证桶裁剪逻辑对旧桶生效）
        key = "/x|GET"
        store._latency_buckets[key][0] = [1.0]  # 确保有桶
        cutoff = int(time.time()) // store._bucket * store._bucket - store._window - 1
        store._latency_buckets[key][cutoff] = [9999.0]  # 注入过期桶
        await store.leave_request("/x", "GET", 2.0, status=200)
        buckets = store._latency_buckets[key]
        assert cutoff not in buckets
        assert len(buckets) >= 1

    async def test_inflight_gauge_and_concurrency_buckets(self) -> None:
        store = RequestKPIStore()
        await store.enter_request("/ping", "GET")
        await store.enter_request("/ping", "GET")
        assert store.snapshot()  # 无异常
        await store.leave_request("/ping", "GET", 5.0, status=200)
        await store.leave_request("/ping", "GET", 7.0, status=200)
        tp = store.throughput()
        assert tp["rps_total"] > 0
        # 并发分档键齐全
        assert set(tp["rps_by_concurrency"].keys()) == {"1", "10", "50", "100"}

    async def test_perf_summary_shape(self) -> None:
        store = RequestKPIStore()
        await store.enter_request("/a", "GET")
        await store.leave_request("/a", "GET", 3.0, status=200)
        summary = store.perf_summary()
        assert summary["inflight"] == 0
        assert summary["request_count_total"] == 1
        assert "/a|GET" in summary["endpoint_percentiles"]
        assert "throughput" in summary


class TestPerfMiddleware:
    def test_records_latency_and_endpoint(self) -> None:
        store = RequestKPIStore()
        client = TestClient(_make_app(store), raise_server_exceptions=False)
        resp = client.get("/api/v1/ping")
        assert resp.status_code == 200
        got = store.latency_percentiles("/ping", "GET")
        assert got["count"] >= 1
        assert got["p95"] > 0

    def test_records_error_status(self) -> None:
        store = RequestKPIStore()
        client = TestClient(_make_app(store), raise_server_exceptions=False)
        resp = client.get("/api/v1/fail")
        assert resp.status_code == 500
        got = store.latency_percentiles("/fail", "GET")
        assert got["count"] >= 1

    def test_default_endpoint_strips_prefix(self) -> None:
        class _Req:  # 轻量 Request 桩，避免 TestClient 依赖
            url = type("U", (), {"path": "/api/v1/chat/stream"})()

        assert default_endpoint(_Req()) == "/chat/stream"


class TestPerfMiddlewareIsolatesFailure:
    def test_store_failure_does_not_block(self) -> None:
        class BrokenStore:
            async def enter_request(self, *a: Any, **kw: Any) -> None:
                raise RuntimeError("boom")

            async def leave_request(self, *a: Any, **kw: Any) -> None:
                raise RuntimeError("boom")

        client = TestClient(_make_app(BrokenStore()), raise_server_exceptions=False)
        resp = client.get("/api/v1/ping")
        assert resp.status_code == 200