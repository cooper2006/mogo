"""026 T001 — chat-api 缓存管理器骨架。

占位模块，Phase 2（US3 缓存与减少冗余计算）填充实现。
接口：get / set / delete / lock，复用既有 Redis 客户端。
"""
from __future__ import annotations

from typing import Any, Optional


class CacheManager:
    """Redis 缓存管理器占位。

    Phase 2 实现时接入 `DSH_KERNEL_REDIS_URL` 配置的 Redis 客户端。
    """

    def __init__(self, redis_url: Optional[str] = None) -> None:
        self._redis_url = redis_url
        self._redis: Any = None

    async def get(self, key: str) -> Optional[Any]:
        """占位：返回 None。"""
        return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """占位：无操作。"""

    async def delete(self, key: str) -> None:
        """占位：无操作。"""

    async def lock(self, key: str, ttl: int = 30) -> bool:
        """占位：返回 False（未获取锁）。"""
        return False


# 模块级单例占位（Phase 2 改为延迟初始化）
_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> CacheManager:
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager
