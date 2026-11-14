"""057 T015：运行时守卫——unsupported 阶段抛 PgCompatUnsupported 且 warning 含推荐替代。

tasks.md T015 原勾选但 ``tests/test_pg_compat_runtime_guard.py`` 在磁盘上不存在
（上一轮核对时纠正为假勾选）。本文件补齐该缺口，模拟传入含 ``$unwind`` 的管道：

1. ``compile()`` 抛出 ``PgCompatUnsupported``（不被静默放行）。
2. 同步发出 structured warning log，其 ``allowed_alternative`` 来自
   ``UNSUPPORTED_STAGE_EXPLANATIONS``（T014 要求带推荐替代方案）。

T014 的 ``allowed_alternative`` 此前因 ``name`` 带 ``$`` 前缀而恒为空串，
本测试固化该缺陷的修复（``name.lstrip("$")``）。
"""

from __future__ import annotations

import logging

import pytest

from app.core.pg_compat import (
    PgCompatUnsupported,
    UNSUPPORTED_STAGE_EXPLANATIONS,
    _AggregationCompiler,
)


def _compile_with_unwind() -> None:
    compiler = _AggregationCompiler("docs")
    compiler.compile([{"$unwind": "$items"}])


def test_unwind_pipeline_raises_pg_compat_unsupported() -> None:
    """T015-①：含 $unwind 的管道必须抛出 PgCompatUnsupported。"""
    with pytest.raises(PgCompatUnsupported):
        _compile_with_unwind()


def test_unwind_warning_contains_recommended_alternative(caplog) -> None:
    """T015-②：warning log 含推荐替代方案文本（来自 UNSUPPORTED_STAGE_EXPLANATIONS）。"""
    with caplog.at_level(logging.WARNING):
        with pytest.raises(PgCompatUnsupported):
            _compile_with_unwind()

    records = [
        r for r in caplog.records
        if r.getMessage() == "aggregation stage not supported in pg_compat"
    ]
    assert records, "未捕获到 unsupported 阶段的 structured warning"

    record = records[0]
    # T014 要求 allowed_alternative 来自 UNSUPPORTED_STAGE_EXPLANATIONS
    assert record.stage == "$unwind"
    assert record.allowed_alternative == UNSUPPORTED_STAGE_EXPLANATIONS["unwind"]
    assert record.allowed_alternative, "推荐替代方案不得为空"
