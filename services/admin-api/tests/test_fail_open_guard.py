"""059 T005/T006 — 统一 fail-closed 守卫的单测。

``services/common/fail_open_guard.py`` 的 ``enforce_fail_closed``：

* 值 indeterminate（None）→ 默认拒绝（``False``）+ warning 日志；
* 显式豁免注释（``fail-open-exempt:``）→ 放行原始布尔值；
* 其余情况 coerce 成 ``bool`` 后返回。
"""

from __future__ import annotations

import logging

import pytest

from app.common.fail_open_guard import (
    DEFAULT_ALLOW,
    DEFAULT_DENY,
    FAIL_OPEN_EXEMPT_COMMENT,
    enforce_fail_closed,
)


def test_none_is_deny(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="app.common.fail_open_guard"):
        assert enforce_fail_closed(None, context="risk.cell") is False
    assert any("fail-closed" in r.message for r in caplog.records)


def test_true_is_allow() -> None:
    assert enforce_fail_closed(True) is True


def test_false_is_deny() -> None:
    assert enforce_fail_closed(False) is False


def test_exempt_marker_returns_original_value() -> None:
    # 显式豁免：放行原始布尔值（False 也返回 False，不再 coerce 成 deny）
    assert (
        enforce_fail_closed(False, exempt_comment=f"{FAIL_OPEN_EXEMPT_COMMENT} legacy")
        is False
    )
    assert (
        enforce_fail_closed(True, exempt_comment=f"{FAIL_OPEN_EXEMPT_COMMENT} legacy")
        is True
    )


def test_exempt_marker_with_none_returns_bool_of_none() -> None:
    # value=None 且带豁免标记 → 返回 bool(None)=False（绕过 deny 兜底）
    assert (
        enforce_fail_closed(None, exempt_comment=f"{FAIL_OPEN_EXEMPT_COMMENT} x")
        is False
    )


def test_constants() -> None:
    assert DEFAULT_DENY is True
    assert DEFAULT_ALLOW is False
