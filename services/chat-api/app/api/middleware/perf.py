"""026 T004/T012 — 性能埋点中间件。

真实实现位于 `app.common.perf_kpi.PerfMiddleware`（vendored 副本，权威源
`services/common/perf_kpi.py`）。本模块保留原路径导出，兼容 Phase 1 已引用的调用方。
"""
from __future__ import annotations

from app.common.perf_kpi import (  # noqa: F401  (re-export)
    PerfMiddleware,
    PerfMonitoringMiddleware,
    RequestKPIStore,
    default_endpoint,
)

__all__ = ["PerfMiddleware", "PerfMonitoringMiddleware", "RequestKPIStore", "default_endpoint"]