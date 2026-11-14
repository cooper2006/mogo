"""026 T025/T026/T027 — 缓存防护层（FR-15/16/17）。

* **穿透防护（T025, FR-15）**：布隆过滤器（Redis ``BF.*``，不可用时降级本地
  set）+ 空值缓存（TTL 60s），拦截「必然不存在」的请求。
* **击穿防护（T026, FR-16）**：互斥锁（``SET NX EX``，参考 ``runtime_lock``
  模式），热点键失效时单请求重建，其余请求等待后读新值。
* **雪崩防护（T027, FR-17）**：TTL 抖动 ±10%（随机），避免热点键同时失效。

本模块自包含，便于 vendored 副本独立校验。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

from cache_manager import CacheManager
from cache_policies import TTLPolicy

logger = logging.getLogger(__name__)

EMPTY_TTL_SECONDS = 60.0  # 空值缓存 TTL
LOCK_TTL_SECONDS = 10.0  # 互斥锁 TTL
LOCK_RETRY_SECONDS = 0.05
LOCK_MAX_WAIT_SECONDS = 1.0
BLOOM_MAX_ITEMS = 1_000_000
BLOOM_FALSE_POSITIVE = 0.01


class BloomFilterGuard:
    """缓存穿透防护：布隆过滤器 + 空值缓存。

    ``might_exist(key)`` 为 false 时直接返回空值，不触达底层数据源；
    返回 true 表示「可能存在」，仍需查缓存/数据源。Redis ``BF.*`` 不可用
    时降级进程内 set（单实例语义，与 session_affinity 一致）。
    """

    def __init__(
        self,
        manager: CacheManager,
        *,
        redis: Any = None,
        bloom_key_prefix: str = "mogo:bloom:cache:",
        memory_max_items: int = BLOOM_MAX_ITEMS,
        empty_ttl: float = EMPTY_TTL_SECONDS,
    ) -> None:
        self._manager = manager
        self._redis = redis
        self._prefix = bloom_key_prefix
        self._empty_ttl = float(empty_ttl)
        self._memory: set[str] = set()
        self._memory_max = int(memory_max_items)
        self._lock = threading.Lock()
        self._bf_available: Optional[bool] = None  # None=未探测
        self._null_hits = 0
        self._null_saves = 0

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def _redis_bf_ok(self) -> bool:
        if self._redis is None:
            return False
        if self._bf_available is None:
            try:
                self._redis.bf().EXISTS(self._key("__probe__"), "probe")
                self._bf_available = True
            except Exception:
                self._bf_available = False
        return bool(self._bf_available)

    def might_exist(self, key: str) -> bool:
        """判断 key 是否「可能存在」（False 可安全拦截）。"""
        if not key:
            return False
        if self._redis_bf_ok():
            try:
                return bool(self._redis.bf().EXISTS(self._key(key), key))
            except Exception:
                pass
        with self._lock:
            return key in self._memory

    def add(self, key: str) -> None:
        """登记 key 存在（写入成功或真实查询命中后调用）。"""
        if not key:
            return
        if self._redis_bf_ok():
            try:
                self._redis.bf().ADD(self._key(key), key)
                return
            except Exception:
                pass
        with self._lock:
            if len(self._memory) >= self._memory_max and key not in self._memory:
                self._memory.clear()
            self._memory.add(key)

    def get_or_load(
        self,
        key: str,
        producer: Callable[[], Any],
        *,
        ttl: Optional[float] = None,
        cache_key: Optional[str] = None,
    ) -> Any:
        """穿透防护的读取路径：布隆过滤 → 缓存 → 数据源 → 写缓存 + 登记。"""
        store_key = cache_key or key
        if not self.might_exist(key):
            self._null_hits += 1
            return None
        value = self._manager.get(store_key)
        if value is not None:
            # 命中空值缓存：视为「不存在」
            if value == _EMPTY_SENTINEL:
                self._null_hits += 1
                return None
            return value
        value = producer()
        if value is None:
            # 空值缓存：TTL 60s，避免穿透反复打数据源
            self._manager.set(store_key, _EMPTY_SENTINEL, ttl=self._empty_ttl)
            self._null_saves += 1
            return None
        self._manager.set(store_key, value, ttl=ttl)
        self.add(key)
        return value

    @property
    def null_hits(self) -> int:
        return self._null_hits

    @property
    def null_saves(self) -> int:
        return self._null_saves


# 空值哨兵：表示「查询过且不存在」，避免与 None 混用
_EMPTY_SENTINEL = "__EMPTY__"


class MutexGuard:
    """缓存击穿防护：互斥锁（SET NX EX）单请求重建。

    热点键失效时，只有一个请求拿到锁并重建缓存，其他请求轮询等待后读新值；
    锁 TTL 兜底防止持有者崩溃导致死锁。
    """

    def __init__(
        self,
        manager: CacheManager,
        *,
        lock_ttl: float = LOCK_TTL_SECONDS,
        retry_seconds: float = LOCK_RETRY_SECONDS,
        max_wait_seconds: float = LOCK_MAX_WAIT_SECONDS,
    ) -> None:
        self._manager = manager
        self._lock_ttl = float(lock_ttl)
        self._retry = float(retry_seconds)
        self._max_wait = float(max_wait_seconds)
        self._local_locks: dict[str, threading.Lock] = {}

    def _lock_key(self, key: str) -> str:
        return f"mogo:mutex:{self._manager.namespace}:{key}"

    def _local(self, key: str) -> threading.Lock:
        return self._local_locks.setdefault(key, threading.Lock())

    def acquire(self, key: str) -> bool:
        """尝试获取互斥锁，立即返回是否成功。"""
        if self._manager.backend == "memory":
            lock = self._local(key)
            return lock.acquire(blocking=False)
        return self._manager.set_if_absent(self._lock_key(key), "1", ttl=self._lock_ttl)

    def release(self, key: str) -> None:
        if self._manager.backend == "memory":
            lock = self._local_locks.get(key)
            if lock is not None and lock.locked():
                lock.release()
            return
        self._manager.delete(self._lock_key(key))

    def singleflight(
        self,
        key: str,
        producer: Callable[[], Any],
        *,
        ttl: Optional[float] = None,
        cache_key: Optional[str] = None,
    ) -> Any:
        """击穿防护的读取路径：先读缓存，未命中则单请求重建。

        - 拿锁成功 → 重建并写缓存 → 释放锁 → 返回新值。
        - 拿锁失败 → 轮询等待缓存出现；等待超时则直接调用 producer（兜底）。
        """
        store_key = cache_key or key
        cached = self._manager.get(store_key)
        if cached is not None:
            return cached
        if self.acquire(key):
            try:
                # 双检：等锁期间可能已被重建
                cached = self._manager.get(store_key)
                if cached is not None:
                    return cached
                value = producer()
                if value is not None:
                    self._manager.set(store_key, value, ttl=ttl)
                return value
            finally:
                self.release(key)
        # 未拿到锁：轮询等待
        deadline = time.monotonic() + self._max_wait
        while time.monotonic() < deadline:
            time.sleep(self._retry)
            cached = self._manager.get(store_key)
            if cached is not None:
                return cached
        return producer()


class AvalancheGuard:
    """缓存雪崩防护：TTL 抖动 ±10% 随机（配合 T024 TTLPolicy）。"""

    def __init__(
        self,
        manager: CacheManager,
        *,
        jitter_ratio: float = 0.10,
        policy: Optional[TTLPolicy] = None,
    ) -> None:
        self._manager = manager
        self._policy = policy or TTLPolicy(jitter_ratio=jitter_ratio)

    @property
    def policy(self) -> TTLPolicy:
        return self._policy

    def jittered_ttl(self, base_ttl: Optional[float] = None) -> float:
        """返回 ±10% 抖动的 TTL。"""
        return self._policy.jittered_ttl(base_ttl)

    def set_with_jitter(
        self,
        key: str,
        value: Any,
        *,
        base_ttl: Optional[float] = None,
        tags: Optional[list[str]] = None,
    ) -> float:
        """以抖动 TTL 写缓存，返回实际使用的 TTL。"""
        ttl = self.jittered_ttl(base_ttl)
        self._manager.set(key, value, ttl=ttl, tags=tags)
        return ttl


__all__ = [
    "BloomFilterGuard",
    "MutexGuard",
    "AvalancheGuard",
    "EMPTY_TTL_SECONDS",
    "LOCK_TTL_SECONDS",
    "LOCK_RETRY_SECONDS",
    "LOCK_MAX_WAIT_SECONDS",
    "BLOOM_MAX_ITEMS",
    "BLOOM_FALSE_POSITIVE",
]