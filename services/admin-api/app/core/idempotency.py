"""025 FR-7 (T015)：幂等键中间件（QF-218, QF-219, QF-220）。

支持 `Idempotency-Key` 请求头，对非安全方法（默认 POST/PUT/PATCH）生效。

- **首次请求**：透传下游，把完整响应（状态码 + 响应体 + Content-Type）缓存到
  Redis，key = ``idempotency:{tenant}:{route}:{key}``，TTL 24h。
- **相同 key 的重复请求**：直接返回缓存的响应体（不重放副作用），并追加
  ``Idempotency-Replayed: true`` 响应头。
- **相同 key 但请求体或路由不同** → **409** Conflict。
- Redis 不可用时降级为进程内存（单实例），与 ``app/core/rate_limiter.py`` 一致，
  并 ``logger.warning``；熔断器打开时按「不幂等」降级（放行下游）。

实现为纯 ASGI 中间件（不用 ``BaseHTTPMiddleware``）：先读完 body 计算指纹，
再用缓存流转发给下游，避免下游读不到 body。本轮**未挂载**到 admin-api app，
留待 T048 统一装配（避免影响现有测试）。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TTL = 24 * 60 * 60  # 24h
IDEMPOTENT_METHODS = ("POST", "PUT", "PATCH")
KEY_HEADER = b"idempotency-key"

# 不参与幂等缓存的响应头（逐请求变化或由传输层控制）
_NON_REPLAYABLE_HEADERS = (
    b"content-length",
    b"transfer-encoding",
    b"content-encoding",
)


def fingerprint_for(method: str, path: str, body: bytes) -> str:
    """计算请求指纹：方法 + 路由 + 请求体。body 相同视为同一逻辑请求。"""
    digest = hashlib.sha256()
    digest.update(method.upper().encode("utf-8"))
    digest.update(b"\x00")
    digest.update(path.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(body)
    return digest.hexdigest()


class IdempotencyStore:
    """幂等响应缓存：Redis 主用，进程内存后备（单实例）。"""

    def __init__(
        self,
        redis_url: str | None = None,
        ttl: int = DEFAULT_TTL,
        key_prefix: str = "idempotency:",
    ) -> None:
        self._ttl = ttl
        self._prefix = key_prefix
        self._redis: Any = None
        self._fallback: dict[str, tuple[float, dict[str, Any]]] = {}

        if redis_url:
            try:
                import redis as _redis_mod

                self._redis = _redis_mod.Redis.from_url(
                    redis_url,
                    socket_timeout=2,
                    socket_connect_timeout=2,
                    health_check_interval=30,
                )
                self._redis.ping()
                from app.core import resilience

                resilience.register_redis_pool(self._redis)
                logger.info("IdempotencyStore connected to Redis")
            except Exception:
                logger.warning(
                    "IdempotencyStore: Redis unavailable at %s, falling back to in-memory "
                    "(single-instance only — multi-instance deployment requires Redis)",
                    redis_url[:40],
                )
                self._redis = None

    @property
    def backend(self) -> str:
        return "redis" if self._redis else "memory"

    def get(self, route_key: str) -> dict[str, Any] | None:
        """读取缓存记录；不存在或已过期返回 ``None``。"""
        full_key = f"{self._prefix}{route_key}"
        if self._redis:
            from app.core import resilience

            raw = resilience.redis_call(self._redis.get, full_key)
            if not raw:
                return None
            try:
                record = json.loads(raw)
            except (TypeError, ValueError):
                return None
            return record if isinstance(record, dict) else None

        item = self._fallback.get(full_key)
        if item is None:
            return None
        stored_at, record = item
        if time.time() - stored_at > self._ttl:
            self._fallback.pop(full_key, None)
            return None
        return record

    def put(self, route_key: str, record: dict[str, Any]) -> None:
        """写入缓存记录并设置 TTL。"""
        full_key = f"{self._prefix}{route_key}"
        record = dict(record)
        record.setdefault("stored_at", time.time())
        if self._redis:
            from app.core import resilience

            payload = json.dumps(record, ensure_ascii=False).encode("utf-8")
            resilience.redis_call(self._redis.set, full_key, payload, ex=self._ttl)
            return
        self._fallback[full_key] = (time.time(), record)

    def delete(self, route_key: str) -> None:
        full_key = f"{self._prefix}{route_key}"
        if self._redis:
            from app.core import resilience

            try:
                resilience.redis_call(self._redis.delete, full_key)
            except Exception:  # 熔断/超时：忽略，仅影响清理
                logger.debug("IdempotencyStore.delete: redis call failed", exc_info=True)
            return
        self._fallback.pop(full_key, None)

    def close(self) -> None:
        if self._redis:
            try:
                self._redis.close()
            except Exception:
                pass
            self._redis = None


# ── 模块级默认实例（懒加载单例） ──────────────────────────────────────────

_default_store: IdempotencyStore | None = None


def get_default_store() -> IdempotencyStore:
    global _default_store
    if _default_store is None:
        from app.core.config import settings

        _default_store = IdempotencyStore(redis_url=settings.redis_url or None)
    return _default_store


def reset_default_store() -> None:
    """测试用：清空模块级单例。"""
    global _default_store
    _default_store = None


def tenant_of(scope: dict[str, Any]) -> str:
    """从 scope 状态里取租户；中间件层未注入时回退 ``anon``。"""
    state = scope.get("state") or {}
    return str(state.get("tenant_id") or "anon")


class IdempotencyMiddleware:
    """幂等键 ASGI 中间件。``store`` 未提供时用模块级默认实例。"""

    def __init__(
        self,
        app: Callable[[dict[str, Any], Any, Any], Awaitable[None]],
        store: IdempotencyStore | None = None,
        methods: tuple[str, ...] = IDEMPOTENT_METHODS,
    ) -> None:
        self.app = app
        self.store = store if store is not None else get_default_store()
        self._methods = {m.upper() for m in methods}
        # 进程内单飞锁：并发重复请求只在第一个进入时执行下游，
        # 其余在锁内读到已写入的缓存后直接重放（避免副作用重复）。
        # 多实例部署仍需 Redis 分布式锁，此处为单进程正确性兜底。
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, route_key: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(route_key)
            if lock is None:
                lock = threading.Lock()
                self._locks[route_key] = lock
            return lock

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = (scope.get("method") or "").upper()
        path = scope.get("path", "/")
        headers = dict(scope.get("headers") or [])
        raw_key = headers.get(KEY_HEADER)
        if method not in self._methods or not raw_key:
            await self.app(scope, receive, send)
            return
        key = raw_key.decode("utf-8", "replace").strip()
        if not key:
            await self.app(scope, receive, send)
            return

        # 先读完 body 计算指纹，再以缓存流转发下游。
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                await self.app(scope, receive, send)
                return
            body.extend(message.get("body", b""))
            if not message.get("more_body"):
                break
        payload = bytes(body)
        fingerprint = fingerprint_for(method, path, payload)
        route_key = f"{tenant_of(scope)}:{method} {path}:{key}"

        async def cached_receive() -> dict[str, Any]:
            return {"type": "http.request", "body": payload, "more_body": False}

        with self._lock_for(route_key):
            try:
                record = self.store.get(route_key)
            except Exception:  # Redis 不可达/熔断打开：按「不幂等」降级，放行下游
                logger.warning("IdempotencyMiddleware: store unavailable, degrading to pass-through")
                await self.app(scope, cached_receive, send)
                return
            if record is not None:
                if record.get("fingerprint") != fingerprint:
                    await _respond(send, 409, "Idempotency-Key 已被使用，但请求内容不同（冲突）")
                    return
                # 直接返回缓存的响应，不重放副作用。
                replay_headers = [(k, v) for k, v in (record.get("headers") or []) if k not in _NON_REPLAYABLE_HEADERS]
                replay_headers.append((b"idempotency-replayed", b"true"))
                body_out = base64.b64decode(record.get("body_base64") or "")
                await send(
                    {
                        "type": "http.response.start",
                        "status": int(record.get("status") or 200),
                        "headers": replay_headers,
                    }
                )
                await send({"type": "http.response.body", "body": body_out})
                return

            captured: dict[str, Any] = {}

            async def buffering_send(message: dict[str, Any]) -> None:
                if message["type"] == "http.response.start":
                    captured["status"] = message["status"]
                    captured["headers"] = list(message.get("headers") or [])
                    await send(message)
                elif message["type"] == "http.response.body":
                    captured.setdefault("chunks", bytearray()).extend(message.get("body", b""))
                    await send(message)

            await self.app(scope, cached_receive, buffering_send)

            status = captured.get("status") or 200
            chunks = captured.get("chunks") or bytearray()
            captured_headers = captured.get("headers") or []
            try:
                self.store.put(
                    route_key,
                    {
                        "fingerprint": fingerprint,
                        "status": status,
                        "headers": captured_headers,
                        "body_base64": base64.b64encode(bytes(chunks)).decode("ascii"),
                    },
                )
            except Exception:
                logger.warning("IdempotencyMiddleware: failed to cache response (non-fatal)")


async def _respond(send: Any, status_code: int, detail: str) -> None:
    payload = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(payload)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})