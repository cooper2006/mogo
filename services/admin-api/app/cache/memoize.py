"""026 T028 — 记忆化装饰器 ``@cache_result``（FR-19）。

对纯函数调用自动缓存结果：首次调用后缓存返回值，后续命中直接返回缓存，
跳过重算。支持 TTL、tag（事件驱动失效）、跳过不可序列化返回值。

用法::

    @cache_result(manager, ttl=60.0, tags=["config"])
    def expensive(query: str) -> dict:
        ...

装饰器按 ``(func.__qualname__, args, kwargs)`` 生成缓存 key，保证同一函数
不同参数不串值。

本模块自包含（stdlib + typing），便于 vendored 副本独立校验。
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import time
from functools import wraps
from typing import Any, Callable, Dict, Optional, Sequence, TypeVar, Union

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 不参与缓存的返回类型（如流、文件句柄）
NON_CACHEABLE_TYPES = (type(None), type(...))


def _serialize(value: Any) -> str:
    """把参数序列化为稳定 key 片段。"""
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return repr(value)


def _make_key(fn: Callable, args: tuple, kwargs: dict) -> str:
    qualname = getattr(fn, "__qualname__", getattr(fn, "__name__", "fn"))
    parts = [_serialize(a) for a in args]
    parts += [f"{k}={_serialize(v)}" for k, v in sorted(kwargs.items())]
    raw = f"{qualname}::{'|'.join(parts)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _extract_cache_key_arg(args: tuple, kwargs: dict) -> Optional[str]:
    """支持 ``cache_key`` 显式指定 key。"""
    return kwargs.pop("cache_key", None) if isinstance(kwargs, dict) else None


def cache_result(
    manager: Any,
    *,
    ttl: Optional[float] = None,
    tags: Optional[Sequence[str]] = None,
    key_prefix: str = "memo",
    key_from_args: bool = True,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """把函数结果缓存到 ``manager``，命中时跳过重算。

    参数:
        manager: CacheManager 实例（get/set）。
        ttl: 缓存 TTL（秒），缺省用 manager.default_ttl。
        tags: 缓存标签，配合 EventInvalidationPolicy 事件驱动失效。
        key_prefix: 缓存 key 前缀。
        key_from_args: False 时忽略参数差异（只适合无参纯函数）。

    返回: 装饰后的函数（带 ``cache_clear`` 属性用于手动清除）。
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        signature = inspect.signature(fn)
        cache_key_attr = getattr(signature, "cache_key", None)

        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # 支持显式 cache_key 参数
            if "cache_key" in kwargs:
                key_value = kwargs.pop("cache_key")
                cache_key = f"{key_prefix}:{key_value}"
            elif cache_key_attr is not None and cache_key_attr in kwargs:
                key_value = kwargs.pop(cache_key_attr)
                cache_key = f"{key_prefix}:{key_value}"
            elif key_from_args:
                raw_key = _make_key(fn, args, kwargs)
                cache_key = f"{key_prefix}:{raw_key}"
            else:
                cache_key = f"{key_prefix}:{getattr(fn, '__qualname__', fn.__name__)}"

            cached = manager.get(cache_key)
            if cached is not None:
                return cached  # type: ignore[return-value]

            result = fn(*args, **kwargs)
            if not _is_cacheable(result):
                return result
            manager.set(cache_key, result, ttl=ttl, tags=tags)
            return result

        def clear() -> bool:
            return bool(manager.delete(f"{key_prefix}:{_make_key(fn, (), {})}"))

        wrapper.cache_clear = clear  # type: ignore[attr-defined]
        wrapper.cache_manager = manager  # type: ignore[attr-defined]
        return wrapper

    return decorator


def _is_cacheable(value: Any) -> bool:
    """判断返回值是否适合缓存（排除流式/句柄类对象）。"""
    if value is None:
        return False
    for kind in NON_CACHEABLE_TYPES:
        if isinstance(value, kind):
            return False
    # 生成器/迭代器不缓存
    if inspect.isgenerator(value):
        return False
    return True


__all__ = ["cache_result"]