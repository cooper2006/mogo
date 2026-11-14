"""026 T024 — 缓存失效策略（FR-14）。

三种失效机制：
* **TTL**：默认 300s（可配），可选 ±ratio 抖动（T027 雪崩防护的 TTL 抖动也在此）。
* **事件驱动失效**：数据变更时通过 ``tag`` 主动失效关联缓存（配合 CacheManager.forget_tag）。
* **版本戳**：读取时校验版本，写入侧 ``bump`` 使旧版本立即失效。

本模块自包含，便于 vendored 副本独立校验。
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

DEFAULT_TTL_SECONDS = 300.0
DEFAULT_JITTER_RATIO = 0.10  # ±10%
DEFAULT_VERSION_TTL_SECONDS = 3600.0


class TTLPolicy:
    """TTL 策略：默认 300s 可配，支持 ±ratio 随机抖动（防雪崩）。"""

    def __init__(
        self,
        default_ttl: float = DEFAULT_TTL_SECONDS,
        *,
        jitter_ratio: float = DEFAULT_JITTER_RATIO,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.default_ttl = float(default_ttl)
        self.jitter_ratio = float(jitter_ratio)
        self._rng = rng or random.Random()

    def ttl_for(self, namespace: str, key: str, *, base_ttl: Optional[float] = None) -> float:
        """返回某键的 TTL（秒）。``base_ttl`` 缺省用 default_ttl。"""
        base = float(base_ttl) if base_ttl is not None else self.default_ttl
        return base

    def jittered_ttl(self, base_ttl: Optional[float] = None) -> float:
        """返回带 ±jitter_ratio 随机抖动的 TTL（雪崩防护）。"""
        base = float(base_ttl) if base_ttl is not None else self.default_ttl
        delta = base * self.jitter_ratio
        return max(1.0, base + self._rng.uniform(-delta, delta))

    def is_expired(self, expires_at: float, *, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        return now >= expires_at


class EventInvalidationPolicy:
    """事件驱动失效：登记 tag → 变更事件，变更时主动失效关联缓存。

    用于数据变更（如配置/权限/会话状态更新）后立刻清除旧缓存。
    """

    def __init__(self, manager: Any) -> None:
        self._manager = manager
        self._tag_handlers: Dict[str, Callable[[Any], Any]] = {}

    def register(self, tag: str, handler: Optional[Callable[[Any], Any]] = None) -> None:
        """为 tag 注册失效处理器（可选，缺省用 manager.forget_tag）。"""
        if handler is not None:
            self._tag_handlers[tag] = handler

    def notify(self, tag: str, payload: Any = None) -> int:
        """数据变更通知：失效该 tag 关联缓存，返回失效条数。"""
        if not tag:
            return 0
        handler = self._tag_handlers.get(tag)
        if handler is not None:
            try:
                result = handler(payload)
                return int(result) if result is not None else 0
            except Exception:
                # 处理器失败时兜底走 manager.forget_tag
                pass
        return int(self._manager.forget_tag(tag) or 0)

    def forget_all(self, tags: Sequence[str]) -> int:
        total = 0
        for tag in tags or ():
            total += self.notify(tag)
        return total


class VersionStampPolicy:
    """版本戳：写入侧 bump 使旧版本缓存立即失效。

    用于「读取时校验版本」场景：缓存值携带版本号，读到旧版本即视为失效。
    """

    def __init__(
        self,
        manager: Any,
        *,
        version_key_prefix: str = "mogo:cache:ver:",
        ttl_seconds: float = DEFAULT_VERSION_TTL_SECONDS,
    ) -> None:
        self._manager = manager
        self._prefix = version_key_prefix
        self._ttl = ttl_seconds

    def _version_key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def current_version(self, key: str) -> int:
        raw = self._manager.get(self._version_key(key), default=None)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def bump(self, key: str) -> int:
        """版本 +1，使旧版本缓存立即失效。"""
        version = self.current_version(key) + 1
        self._manager.set(self._version_key(key), version, ttl=self._ttl)
        return version

    def validate(self, key: str, cached_version: Any) -> bool:
        """校验缓存版本是否与当前版本一致。"""
        try:
            cached = int(cached_version)
        except (TypeError, ValueError):
            return False
        return cached == self.current_version(key)


class CacheTag:
    """缓存标签常量：按领域聚合失效范围。"""

    SESSION = "session"
    CONFIG = "config"
    PERMISSION = "permission"
    TOKEN = "token"
    DOCUMENT = "document"
    KNOWLEDGE = "knowledge"


__all__ = [
    "TTLPolicy",
    "EventInvalidationPolicy",
    "VersionStampPolicy",
    "CacheTag",
    "DEFAULT_TTL_SECONDS",
    "DEFAULT_JITTER_RATIO",
    "DEFAULT_VERSION_TTL_SECONDS",
]