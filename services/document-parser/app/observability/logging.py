"""023 T022 — document-parser 专属日志配置。

在 `common/observability_base.py::configure_logging` 基础上：
- 导出 `get_doc_parser_logger(name)` 便捷函数
"""
from __future__ import annotations

from typing import Any

from app.common.observability_base import configure_logging, get_logger

SERVICE_NAME = "mogo-document-parser"


def init_doc_parser_logging(level: str | None = None, json_output: bool | None = None) -> None:
    """初始化 document-parser 结构化日志。

    幂等：重复调用只重配一次（由 `configure_logging` 保证）。
    """
    configure_logging(SERVICE_NAME, level=level, json_output=json_output)


def get_doc_parser_logger(name: str) -> Any:
    """获取 document-parser logger（已绑定 service=mogo-document-parser）。"""
    return get_logger(name)
