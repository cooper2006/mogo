"""057 T007：pg_compat 能力清单常量单测。

tasks.md T007 原勾选但 ``tests/test_pg_compat_manifest.py`` 在磁盘上不存在
（上一轮核对时纠正为假勾选）。本文件补齐该缺口，断言：

1. ``SUPPORTED_AGGREGATION_STAGES`` 存在且为 ``frozenset[str]``，内容恰为当前
   处理器（``_AggregationCompiler._stage_*``）对应的阶段名。
2. 清单大小与 processor 数量一一对应（每个支持的阶段都有一个处理器）。
3. ``UNSUPPORTED_STAGE_EXPLANATIONS`` 为每个不支持阶段提供非空推荐替代方案。
4. supported 与 unsupported 两个集合不相交。
5. unsupported 的每个阶段经 ``compile()`` 均抛 ``PgCompatUnsupported``。

不连接数据库，纯常量/纯逻辑单测。
"""

from __future__ import annotations

import pytest

from app.core.pg_compat import (
    PgCompatUnsupported,
    SUPPORTED_AGGREGATION_STAGES,
    UNSUPPORTED_STAGE_EXPLANATIONS,
    _AggregationCompiler,
)

# 当前 7 个处理器对应的阶段名（与 pg_compat.py 的 _stage_* 一一对应）。
EXPECTED_SUPPORTED = frozenset({
    "match", "sort", "limit", "skip", "count", "group", "project",
})


def _stage_handler_names() -> set[str]:
    """从 _AggregationCompiler 上收集 ``_stage_<name>`` 处理器名（去前缀）。"""
    return {
        name[len("_stage_"):]
        for name in dir(_AggregationCompiler)
        if name.startswith("_stage_")
    }


def test_supported_stages_is_frozenset() -> None:
    assert isinstance(SUPPORTED_AGGREGATION_STAGES, frozenset)


def test_supported_stages_exact_expected_set() -> None:
    """清单与处理器实现完全一致（防新增处理器忘记登记清单）。"""
    assert SUPPORTED_AGGREGATION_STAGES == EXPECTED_SUPPORTED


def test_supported_size_matches_processor_count() -> None:
    """T007：大小与 processor 数量一致。"""
    handlers = _stage_handler_names()
    assert len(handlers) == len(SUPPORTED_AGGREGATION_STAGES)
    assert handlers == set(SUPPORTED_AGGREGATION_STAGES)


def test_every_unsupported_stage_has_nonempty_explanation() -> None:
    """T007：每阶段均有非空 explanation，且不与 supported 重叠。"""
    for stage, explanation in UNSUPPORTED_STAGE_EXPLANATIONS.items():
        assert explanation.strip(), f"{stage} 缺少推荐替代方案说明"
        assert stage not in SUPPORTED_AGGREGATION_STAGES, (
            f"{stage} 同时出现在 supported 与 unsupported，清单不一致"
        )


def test_supported_and_unsupported_disjoint() -> None:
    assert not (set(SUPPORTED_AGGREGATION_STAGES) & set(UNSUPPORTED_STAGE_EXPLANATIONS))


@pytest.mark.parametrize("stage", sorted(UNSUPPORTED_STAGE_EXPLANATIONS))
def test_unsupported_stage_raises_in_compile(stage: str) -> None:
    """T007 兜底：unsupported 阶段在编译期确实被拒绝，而非被静默放行。"""
    compiler = _AggregationCompiler("docs")
    with pytest.raises(PgCompatUnsupported):
        compiler.compile([{f"${stage}": {"field": 1}}])


def test_supported_stage_compiles_without_raise() -> None:
    """T007 对照：supported 阶段（如 $match）可正常编译，不抛。"""
    compiler = _AggregationCompiler("docs")
    sql = compiler.compile([{"$match": {"active": True}}])
    # $match 也经 CTE（ag1）产出，最终 SELECT 读 CTE 而非基表。
    assert sql.startswith("WITH ag1 AS (SELECT id, doc FROM docs WHERE")
    assert sql.endswith("SELECT doc FROM ag1")
