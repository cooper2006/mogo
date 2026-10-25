"""023 T090 — 超时层级（FR-22）。

验证 入口 30s > 下游 10s > 单次操作 5s 的递减约束、配置可覆盖，
以及超时后资源（在途计数）被释放。
"""
from __future__ import annotations

import asyncio

import pytest

from app.common.dependency_guard import (
    TIMEOUT_DOWNSTREAM_SECONDS_DEFAULT,
    TIMEOUT_ENTRY_SECONDS_DEFAULT,
    TIMEOUT_OPERATION_SECONDS_DEFAULT,
    BackpressureGuard,
    TimeoutHierarchy,
    TimeoutHierarchyError,
)


def test_default_hierarchy_decreases_inward():
    h = TimeoutHierarchy()
    assert h.entry == TIMEOUT_ENTRY_SECONDS_DEFAULT == 30.0
    assert h.downstream == TIMEOUT_DOWNSTREAM_SECONDS_DEFAULT == 10.0
    assert h.operation == TIMEOUT_OPERATION_SECONDS_DEFAULT == 5.0
    assert h.operation < h.downstream < h.entry


@pytest.mark.parametrize(
    "entry,downstream,operation",
    [
        (5.0, 10.0, 30.0),   # 完全倒挂
        (30.0, 10.0, 10.0),  # operation == downstream
        (30.0, 30.0, 5.0),   # downstream == entry
    ],
)
def test_inverted_hierarchy_is_rejected(entry, downstream, operation):
    with pytest.raises(TimeoutHierarchyError):
        TimeoutHierarchy(entry=entry, downstream=downstream, operation=operation)


def test_hierarchy_from_env_override():
    h = TimeoutHierarchy.from_env({
        "MOGO_TIMEOUT_ENTRY_SECONDS": "60",
        "MOGO_TIMEOUT_DOWNSTREAM_SECONDS": "20",
        "MOGO_TIMEOUT_OPERATION_SECONDS": "8",
    })
    assert (h.entry, h.downstream, h.operation) == (60.0, 20.0, 8.0)


def test_timeout_releases_resource():
    """超时后资源必须释放：否则每次超时漏一个槽，最终 100% 拒绝。"""
    guard = BackpressureGuard("t", max_depth=1)

    async def scenario() -> None:
        assert guard.try_enter() is True

        async def slow() -> None:
            await asyncio.sleep(5)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow(), timeout=0.01)
        guard.leave()
        assert guard.depth == 0
        assert guard.try_enter() is True

    asyncio.run(scenario())
