"""025 FR-7 (T015)：幂等键中间件行为测试（QF-218/219/220）。

只用进程内存 store（不依赖真实 Redis），通过 FastAPI TestClient 走真实 ASGI 链路，
验证：首次缓存、重复重放（含 `Idempotency-Replayed`）、冲突 409、非幂等方法/
无 key 透传、缓存过期、store 读写与指纹稳定性。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.idempotency import (
    DEFAULT_TTL,
    IdempotencyMiddleware,
    IdempotencyStore,
    fingerprint_for,
)


def _build_app(store: IdempotencyStore, hits: dict[str, int]) -> FastAPI:
    app = FastAPI()

    @app.post("/orders")
    async def create_order(payload: dict[str, Any]) -> dict[str, Any]:
        hits["count"] += 1
        return {"id": "o1", "name": payload.get("name", "?"), "tenant_id": "t1"}

    @app.post("/other")
    async def other(payload: dict[str, Any]) -> dict[str, Any]:
        hits["count"] += 1
        return {"id": "other"}

    @app.put("/orders/{order_id}")
    async def update_order(order_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        hits["count"] += 1
        return {"id": order_id, "name": payload.get("name")}

    app.add_middleware(IdempotencyMiddleware, store=store)
    return app


def _headers(key: str) -> dict[str, str]:
    return {"Idempotency-Key": key}


class TestFirstRequestCachesResponse:
    def test_first_request_reaches_downstream_and_returns_body(self) -> None:
        hits = {"count": 0}
        store = IdempotencyStore()
        client = TestClient(_build_app(store, hits))
        response = client.post("/orders", json={"name": "x"}, headers=_headers("k1"))
        assert response.status_code == 200
        assert response.json() == {"id": "o1", "name": "x", "tenant_id": "t1"}
        assert hits["count"] == 1

    def test_replay_returns_cached_body_without_rehitting_downstream(self) -> None:
        hits = {"count": 0}
        store = IdempotencyStore()
        client = TestClient(_build_app(store, hits))
        body = {"name": "x"}
        first = client.post("/orders", json=body, headers=_headers("k1"))
        assert first.status_code == 200
        second = client.post("/orders", json=body, headers=_headers("k1"))
        assert second.status_code == 200
        # 下游只被调用一次：副作用未重放
        assert hits["count"] == 1
        assert second.json() == first.json()
        assert second.headers.get("idempotency-replayed") == "true"
        assert first.headers.get("idempotency-replayed") is None


class TestConflict:
    def test_same_key_different_body_returns_409(self) -> None:
        hits = {"count": 0}
        store = IdempotencyStore()
        client = TestClient(_build_app(store, hits))
        client.post("/orders", json={"name": "x"}, headers=_headers("k1"))
        conflict = client.post("/orders", json={"name": "y"}, headers=_headers("k1"))
        assert conflict.status_code == 409
        assert "冲突" in conflict.json()["detail"]
        assert hits["count"] == 1  # 冲突请求未重放下游

    def test_different_route_has_independent_idempotency_space(self) -> None:
        """route 是幂等 key 的一部分：不同路由各自独立，永不互相冲突。"""
        hits = {"count": 0}
        store = IdempotencyStore()
        client = TestClient(_build_app(store, hits))
        client.post("/orders", json={"name": "x"}, headers=_headers("k1"))
        other = client.post("/other", json={"name": "x"}, headers=_headers("k1"))
        assert other.status_code == 200
        assert hits["count"] == 2  # 两条路由各执行一次


class TestPassThrough:
    def test_without_key_always_hits_downstream(self) -> None:
        hits = {"count": 0}
        store = IdempotencyStore()
        client = TestClient(_build_app(store, hits))
        for _ in range(2):
            assert client.post("/orders", json={"name": "x"}).status_code == 200
        assert hits["count"] == 2

    def test_blank_key_always_hits_downstream(self) -> None:
        hits = {"count": 0}
        store = IdempotencyStore()
        client = TestClient(_build_app(store, hits))
        for _ in range(2):
            assert client.post("/orders", json={"name": "x"}, headers=_headers("   ")).status_code == 200
        assert hits["count"] == 2

    def test_post_replay_does_not_rehit(self) -> None:
        hits = {"count": 0}
        store = IdempotencyStore()
        client = TestClient(_build_app(store, hits))
        client.post("/orders", json={"name": "x"}, headers=_headers("k1"))
        client.post("/orders", json={"name": "x"}, headers=_headers("k1"))
        assert hits["count"] == 1


class TestTtl:
    def test_expired_record_is_not_replayed(self) -> None:
        hits = {"count": 0}
        store = IdempotencyStore(ttl=1)
        client = TestClient(_build_app(store, hits))
        body = {"name": "x"}
        client.post("/orders", json=body, headers=_headers("k1"))
        assert hits["count"] == 1
        time.sleep(1.1)
        client.post("/orders", json=body, headers=_headers("k1"))
        assert hits["count"] == 2  # 缓存已过期，重新执行


class TestStore:
    def test_put_get_delete_roundtrip(self) -> None:
        store = IdempotencyStore()
        record = {"fingerprint": "abc", "status": 201, "headers": [], "body_base64": "e30="}
        assert store.get("t1:POST /orders:k") is None
        store.put("t1:POST /orders:k", record)
        got = store.get("t1:POST /orders:k")
        assert got is not None
        assert got["fingerprint"] == "abc"
        assert got["status"] == 201
        store.delete("t1:POST /orders:k")
        assert store.get("t1:POST /orders:k") is None

    def test_backend_is_memory_without_redis(self) -> None:
        assert IdempotencyStore().backend == "memory"

    def test_default_ttl_is_24h(self) -> None:
        assert DEFAULT_TTL == 24 * 60 * 60


class TestFingerprint:
    def test_stable_for_same_input(self) -> None:
        assert fingerprint_for("post", "/orders", b'{"a":1}') == fingerprint_for("POST", "/orders", b'{"a":1}')

    def test_differs_by_body_and_route(self) -> None:
        base = fingerprint_for("POST", "/orders", b'{"a":1}')
        assert fingerprint_for("POST", "/orders", b'{"a":2}') != base
        assert fingerprint_for("POST", "/other", b'{"a":1}') != base
        assert fingerprint_for("PUT", "/orders", b'{"a":1}') != base