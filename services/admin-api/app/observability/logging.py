"""023 T015 — admin-api 专属日志配置。

在 `common/observability_base.py::configure_logging` 基础上：
- 绑定 tenant_id / user_id 上下文变量（admin-api 有租户/用户维度）
- 导出 `get_admin_logger(name)` 便捷函数
"""
from __future__ import annotations

import logging
from typing import Any

from app.common.observability_base import configure_logging, get_logger

SERVICE_NAME = "mogo-admin-api"


def init_admin_logging(level: str | None = None, json_output: bool | None = None) -> None:
    """初始化 admin-api 结构化日志。

    幂等：重复调用只重配一次（由 `configure_logging` 保证）。
    """
    configure_logging(SERVICE_NAME, level=level, json_output=json_output)


def get_admin_logger(name: str) -> Any:
    """获取 admin-api logger（已绑定 service=mogo-admin-api）。"""
    return get_logger(name)


def bind_tenant_context(tenant_id: str | None = None, user_id: str | None = None) -> None:
    """绑定租户/用户上下文（请求级调用）。

    在请求中间件中调用，使后续日志自动带上 tenant_id / user_id 字段。
    """
    import structlog.contextvars

    if tenant_id:
        structlog.contextvars.bind_contextvars(tenant_id=tenant_id)
    if user_id:
        structlog.contextvars.bind_contextvars(user_id=user_id)
