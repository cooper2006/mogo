"""026 T023 — 缓存管理器（FR-13）。

Redis 连接复用模式与 ``dsh_runtime/session_affinity.py`` 一致（``from_url`` +
``ping()`` 探测，失败降级进程内内存），保证在 Redis 不可用时仍具备缓存语义。
命中率等指标由 ``stats()`` 暴露，供 T030 命中率监控消费。

序列化：JSON 字符串（Redis ``decode_responses=True``）。memory 降级路径
使用 LRU + TTL，避免进程内缓存无限增长。

本模块自包含（不 import 兄弟 vendored 模块），以保证三服务 vendored
副本可独立校验。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 300.0
DEFAULT_MAX_ENTRIES = 100_000
DEFAULT_MEMORY_MAX_ENTRIES = 10_000
KEY_PREFIX = "mogo:cache:"
TAG_INDEX_SUFFIX = "::tag"


class CacheEntry:
    """一条缓存记录（含过期时间与标签，便于事件驱动失效）。"""

    __slots__ = ("value", "expires_at", "tags")

    def __init__(self, value: Any, expires_at: float, tags: Tuple[str, ...] = ()) -> None:
        self.value = value
        self.expires_at = expires_at
        self.tags = tuple(tags or ())

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self.expires_at

    @property
    def ttl(self) -> float:
        return max(0.0, self.expires_at - time.monotonic())


class CacheLock:
    """基于缓存 SET NX EX 的命名锁（兼容 T001 声明的 lock 接口）。"""

    def __init__(self, manager: "CacheManager", name: str, *, ttl: float = 10.0) -> None:
        self._manager = manager
        self._name = name
        self._ttl = float(ttl)
        self._acquired = False

    def acquire(self, blocking: bool = False, timeout: float = 0.0) -> bool:
        if self._acquired:
            return True
        if blocking:
            deadline = time.monotonic() + timeout
            while True:
                if self._manager.set_if_absent(self._name, "1", ttl=self._ttl):
                    self._acquired = True
                    return True
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.02)
        ok = self._manager.set_if_absent(self._name, "1", ttl=self._ttl)
        self._acquired = bool(ok)
        return self._acquired

    def release(self) -> None:
        if self._acquired:
            self._manager.delete(self._name)
            self._acquired = False

    def __enter__(self) -> "CacheLock":
        self.acquire(blocking=True, timeout=1.0)
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


class CacheManager:
    """``get/set/delete`` 缓存管理器，Redis 优先、内存降级。"""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        *,
        namespace: str = "default",
        default_ttl: float = DEFAULT_TTL_SECONDS,
        memory_max_entries: int = DEFAULT_MEMORY_MAX_ENTRIES,
    ) -> None:
        self._namespace = namespace
        self._default_ttl = float(default_ttl)
        self._memory_max = int(memory_max_entries)
        self._redis: Any = None
        # memory 降级：key -> (entry, order) 使用 dict + order 单调计数实现 LRU
        self._memory: Dict[str, CacheEntry] = {}
        self._order: Dict[str, int] = {}
        self._counter = 0
        # 指标
        self._hits = 0
        self._misses = 0
        self._writes = 0
        self._evictions = 0
        if redis_url:
            try:
                import redis as _redis_mod

                self._redis = _redis_mod.Redis.from_url(
                    redis_url,
                    socket_timeout=2,
                    socket_connect_timeout=2,
                    health_check_interval=30,
                    decode_responses=True,
                )
                self._redis.ping()
                logger.info(
                    "cache manager connected to Redis",
                    extra={"event": "cache.redis_ready", "cache_namespace": namespace},
                )
            except Exception:
                logger.warning(
                    "cache manager: Redis unavailable, falling back to in-process memory",
                    extra={"event": "cache.redis_unavailable", "cache_namespace": namespace},
                )
                self._redis = None

    # ---------- backend 属性 ----------

    @property
    def backend(self) -> str:
        return "redis" if self._redis is not None else "memory"

    @property
    def namespace(self) -> str:
        return self._namespace

    @property
    def default_ttl(self) -> float:
        return self._default_ttl

    # ---------- key 构造 ----------

    def _key(self, key: str) -> str:
        return f"{KEY_PREFIX}{self._namespace}:{key}"

    def _tag_key(self, tag: str) -> str:
        return f"{KEY_PREFIX}{self._namespace}{TAG_INDEX_SUFFIX}:{tag}"

    # ---------- 读 ----------

    def get(self, key: str, *, default: Any = None) -> Any:
        """读取缓存；命中失败返回 ``default``（不抛异常）。"""
        if not key:
            return default
        full = self._key(key)
        if self._redis is not None:
            try:
                raw = self._redis.get(full)
            except Exception:
                logger.warning("cache read failed; treating as miss", extra={"event": "cache.read_failed"})
                raw = None
            if raw is None:
                self._misses += 1
                return default
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                self._misses += 1
                return default
            self._hits += 1
            return payload.get("value", default)
        # memory 降级
        entry = self._memory.get(full)
        if entry is None or entry.expired:
            if entry is not None:
                self._drop_memory(full)
            self._misses += 1
            return default
        self._touch_memory(full)
        self._hits += 1
        return entry.value

    # ---------- 写 ----------

    def set(
        self,
        key: str,
        value: Any,
        *,
        ttl: Optional[float] = None,
        tags: Optional[Sequence[str]] = None,
    ) -> bool:
        """写入缓存；``ttl`` 缺省用 default_ttl，``tags`` 支持事件驱动失效。"""
        if not key:
            return False
        full = self._key(key)
        ttl_seconds = float(ttl) if ttl is not None else self._default_ttl
        expires_at = time.monotonic() + ttl_seconds
        tags_tuple = tuple(tags or ())
        payload = json.dumps(
            {"v": value, "e": ttl_seconds, "t": list(tags_tuple)}, ensure_ascii=False
        )
        if self._redis is not None:
            try:
                self._redis.set(full, payload, ex=max(1, int(ttl_seconds)))
                for tag in tags_tuple:
                    self._redis.sadd(self._tag_key(tag), full)
                self._writes += 1
                return True
            except Exception:
                logger.warning(
                    "cache write failed; using in-process memory",
                    extra={"event": "cache.write_failed"},
                )
        self._memory[full] = CacheEntry(value, expires_at, tags_tuple)
        self._counter += 1
        self._order[full] = self._counter
        self._writes += 1
        self._enforce_limit()
        return True

    # ---------- 删 ----------

    def delete(self, key: str) -> bool:
        if not key:
            return False
        full = self._key(key)
        if self._redis is not None:
            try:
                self._redis.delete(full)
                return True
            except Exception:
                logger.warning("cache delete failed", extra={"event": "cache.delete_failed"})
        self._drop_memory(full)
        return True

    def forget_tag(self, tag: str) -> int:
        """事件驱动失效：删除某 tag 关联的所有缓存键。返回删除数量。"""
        if not tag:
            return 0
        tag_key = self._tag_key(tag)
        if self._redis is not None:
            try:
                members = self._redis.smembers(tag_key)
                if members:
                    self._redis.delete(*members)
                self._redis.delete(tag_key)
                return int(len(members or ()))
            except Exception:
                logger.warning("cache forget_tag failed", extra={"event": "cache.forget_tag_failed"})
        # memory：按 tags 扫描
        dropped = 0
        for full, entry in list(self._memory.items()):
            if tag in entry.tags:
                self._drop_memory(full)
                dropped += 1
        return dropped

    def keys_for_tag(self, tag: str) -> List[str]:
        """返回某 tag 关联的原始 key（不含前缀）。"""
        if not tag:
            return []
        tag_key = self._tag_key(tag)
        if self._redis is not None:
            try:
                members = self._redis.smembers(tag_key)
                prefix = self._key("")
                return [m[len(prefix):] for m in (members or ()) if m.startswith(prefix)]
            except Exception:
                return []
        prefix = self._key("")
        return [
            full[len(prefix):] for full, entry in self._memory.items() if tag in entry.tags
        ]

    # ---------- 原子写（供 T025/T026 防护层使用）----------

    def set_if_absent(self, key: str, value: Any, *, ttl: Optional[float] = None) -> bool:
        """``SET NX EX``：仅当 key 不存在时写入。返回是否写入成功。"""
        if not key:
            return False
        full = self._key(key)
        ttl_seconds = float(ttl) if ttl is not None else self._default_ttl
        payload = json.dumps({"v": value, "e": ttl_seconds, "t": []}, ensure_ascii=False)
        if self._redis is not None:
            try:
                ok = self._redis.set(full, payload, ex=max(1, int(ttl_seconds)), nx=True)
                if ok:
                    self._writes += 1
                return bool(ok)
            except Exception:
                logger.warning("cache set_if_absent failed", extra={"event": "cache.setnx_failed"})
        if full in self._memory and not self._memory[full].expired:
            return False
        self._memory[full] = CacheEntry(value, time.monotonic() + ttl_seconds, ())
        self._counter += 1
        self._order[full] = self._counter
        self._writes += 1
        self._enforce_limit()
        return True

    # ---------- 锁（T001 接口：get/set/delete/lock）----------

    def lock(self, name: str, *, ttl: float = 10.0) -> "CacheLock":
        """返回一个命名锁（SET NX EX 语义），支持 ``with`` 使用。"""
        return CacheLock(self, name, ttl=ttl)

    # ---------- 指标 ----------

    def stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        return {
            "backend": self.backend,
            "namespace": self._namespace,
            "hits": self._hits,
            "misses": self._misses,
            "requests": total,
            "hit_rate": (self._hits / total) if total else 0.0,
            "writes": self._writes,
            "evictions": self._evictions,
            "memory_entries": len(self._memory),
        }

    def reset_stats(self) -> None:
        self._hits = 0
        self._misses = 0
        self._writes = 0
        self._evictions = 0

    # ---------- memory LRU ----------

    def _touch_memory(self, full: str) -> None:
        self._counter += 1
        self._order[full] = self._counter

    def _drop_memory(self, full: str) -> None:
        self._memory.pop(full, None)
        self._order.pop(full, None)

    def _enforce_limit(self) -> None:
        while len(self._memory) > self._memory_max:
            if not self._order:
                break
            oldest = min(self._order, key=self._order.get)
            self._drop_memory(oldest)
            self._evictions += 1


def build_manager_from_settings(settings: Any) -> CacheManager:
    """从 Settings 对象构建缓存管理器（读 REDIS_URL/CACHE_NAMESPACE/CACHE_DEFAULT_TTL）。"""
    redis_url = getattr(settings, "REDIS_URL", None) or getattr(settings, "redis_url", None)
    namespace = (
        getattr(settings, "CACHE_NAMESPACE", None)
        or getattr(settings, "cache_namespace", None)
        or "default"
    )
    ttl = getattr(settings, "CACHE_DEFAULT_TTL", None) or getattr(settings, "cache_default_ttl", None)
    return CacheManager(redis_url, namespace=namespace, default_ttl=float(ttl) if ttl else DEFAULT_TTL_SECONDS)


__all__ = [
    "CacheManager",
    "CacheEntry",
    "build_manager_from_settings",
    "DEFAULT_TTL_SECONDS",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MEMORY_MAX_ENTRIES",
    "KEY_PREFIX",
]