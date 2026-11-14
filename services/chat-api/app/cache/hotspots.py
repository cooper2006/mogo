"""026 T029 (FR-13) — 四类热点数据接入缓存的门面。

session / config / permission / token 是系统最高频访问的四类热点数据。本模块
在 ``CacheManager`` 之上提供类型化访问门面 ``HotspotCache``：

* ``get/put/delete`` 按 `(kind, ident)` 生成稳定 key，统一 ``hotspot:{kind}:{ident}`` 前缀；
* ``put`` 走 ``TTLPolicy.jittered_ttl``（±10% 抖动，防雪崩，T027）；
* ``delete(kind)`` 走 ``forget_tag`` 事件驱动整类失效（T024）；
* ``invalidate_all`` 一键失效四类，供数据变更方（config/session 更新）主动失效。

权威源：``services/common/cache_hotspots.py``；vendored 到三服务
``app/cache/hotspots.py``（字节一致）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# vendored（三服务内）：走 app.cache 包；权威源直读（tools/tests）时走兄弟模块。
try:
    from app.cache.manager import CacheManager, build_manager_from_settings
    from app.cache.policies import TTLPolicy
except ImportError:  # pragma: no cover - services/common 直读路径
    from cache_manager import CacheManager, build_manager_from_settings  # type: ignore
    from cache_policies import TTLPolicy  # type: ignore

__all__ = [
    "HotspotCache",
    "build_hotspot_from_settings",
    "HOTSPOT_SESSION",
    "HOTSPOT_CONFIG",
    "HOTSPOT_PERMISSION",
    "HOTSPOT_TOKEN",
    "HOTSPOT_KINDS",
]

HOTSPOT_SESSION = "session"
HOTSPOT_CONFIG = "config"
HOTSPOT_PERMISSION = "permission"
HOTSPOT_TOKEN = "token"
HOTSPOT_KINDS: tuple = (HOTSPOT_SESSION, HOTSPOT_CONFIG, HOTSPOT_PERMISSION, HOTSPOT_TOKEN)

KEY_PREFIX = "hotspot"


class HotspotCache:
    """四类热点数据的缓存门面（FR-13）。"""

    #: 四类热点数据
    SESSION = HOTSPOT_SESSION
    CONFIG = HOTSPOT_CONFIG
    PERMISSION = HOTSPOT_PERMISSION
    TOKEN = HOTSPOT_TOKEN
    KINDS = HOTSPOT_KINDS

    def __init__(
        self,
        manager: CacheManager,
        *,
        ttl: Optional[float] = None,
        ttl_policy: Optional[TTLPolicy] = None,
    ) -> None:
        self._m = manager
        self._ttl = float(ttl) if ttl is not None else float(manager.default_ttl)
        self._ttl_policy = ttl_policy or TTLPolicy()

    # ---------- 构造 ----------

    @classmethod
    def from_settings(cls, settings: Any, *, ttl: Optional[float] = None) -> "HotspotCache":
        """从 Settings 构建（复用 ``build_manager_from_settings``）。"""
        return cls(build_manager_from_settings(settings), ttl=ttl)

    # ---------- key ----------

    def key(self, kind: str, ident: str) -> str:
        """生成稳定缓存 key：``hotspot:{kind}:{ident}``。"""
        if kind not in self.KINDS:
            raise ValueError(f"unknown hotspot kind: {kind!r} (expected one of {self.KINDS})")
        return f"{KEY_PREFIX}:{kind}:{ident}"

    def tag_for(self, kind: str) -> str:
        """该类型的事件失效 tag（``forget_tag`` 消费）。"""
        if kind not in self.KINDS:
            raise ValueError(f"unknown hotspot kind: {kind!r} (expected one of {self.KINDS})")
        return f"{KEY_PREFIX}:{kind}"

    # ---------- 访问 ----------

    def get(self, kind: str, ident: str, *, default: Any = None) -> Any:
        """读热点数据；未命中返回 `default`（不抛错）。"""
        value = self._m.get(self.key(kind, ident), default=None)
        return default if value is None else value

    def put(self, kind: str, ident: str, value: Any, *, ttl: Optional[float] = None) -> bool:
        """写热点数据；TTL 走 ±10% 抖动（未显式给定时），并挂 ``hotspot:{kind}`` tag。"""
        base = self._ttl if ttl is None else float(ttl)
        effective = self._ttl_policy.jittered_ttl(base)
        return self._m.set(self.key(kind, ident), value, ttl=effective, tags=(self.tag_for(kind),))

    def delete(self, kind: str, ident: Optional[str] = None) -> Any:
        """失效单条（`ident` 给定时）或整类（`ident=None` 时事件驱动整类失效）。"""
        if ident is None:
            return self._m.forget_tag(self.tag_for(kind))
        return self._m.delete(self.key(kind, ident))

    def invalidate_all(self, kinds: Optional[Sequence[str]] = None) -> int:
        """一键失效全部（或指定）热点类型，返回失效条目数。"""
        kinds = list(kinds) if kinds is not None else list(self.KINDS)
        total = 0
        for kind in kinds:
            total += int(self._m.forget_tag(self.tag_for(kind)))
        return total

    def stats(self) -> Dict[str, Any]:
        """透出命中率等指标（供 CacheMetricsReporter / 008 驾驶舱消费）。"""
        return self._m.stats()

    @property
    def manager(self) -> CacheManager:
        return self._m

    @property
    def ttl(self) -> float:
        return self._ttl


def build_hotspot_from_settings(settings: Any, *, ttl: Optional[float] = None) -> HotspotCache:
    """便捷工厂：从 Settings 直接构建 ``HotspotCache``。"""
    return HotspotCache.from_settings(settings, ttl=ttl)