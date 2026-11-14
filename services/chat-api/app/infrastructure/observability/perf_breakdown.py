"""026 T008 — 外部依赖耗时拆分。

核心实现在 `app.infrastructure.observability.execution_trace`（026 T008 落点）。
本模块保留便捷导入路径（薄 re-export，不重复实现）。
"""
from __future__ import annotations

from app.infrastructure.observability.execution_trace import (  # noqa: F401
    KIND_ORDER,
    KIND_PATTERNS,
    PerfBreakdown,
    PerfBreakdownItem,
    dependency_breakdown,
    infer_span_kind,
)

__all__ = [
    "KIND_ORDER",
    "KIND_PATTERNS",
    "PerfBreakdown",
    "PerfBreakdownItem",
    "dependency_breakdown",
    "infer_span_kind",
]