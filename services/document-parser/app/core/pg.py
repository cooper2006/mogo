"""PanWeiDB（openGauss 内核 / PostgreSQL 兼容线协议）连接池。

与 :mod:`app.core.db` 的 MongoDB 路径并列存在，由 ``MOGO_DATA_BACKEND``
开关选择（``mongo`` 默认 / ``panweidb``）。设计细节与分阶段计划见
``docs/mongo-to-panweidb-migration-plan.md``。

本服务（document-parser）历史上只用 **同步** ``pymongo``，因此这里只提供同步池；
admin-api / chat-api 走异步 motor，另有 ``init_async_pg``。

实测环境（2026-10-13）：PanWeiDB 3.2.0 / ``sql_compatibility=A`` / 端口 5432 /
``password_encryption_type=1``（MD5）。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_sync_pool: Any = None
_lock = threading.Lock()

#: 本服务名，写入 libpq ``application_name``，便于在 PanWeiDB 侧排查连接来源。
APPLICATION_NAME = "mogo-document-parser"


def is_panweidb_backend() -> bool:
    """当前是否选中 PanWeiDB 后端。"""
    return settings.effective_data_backend == "panweidb"


def connection_kwargs() -> dict[str, Any]:
    """组装 libpq 连接参数。"""
    kwargs: dict[str, Any] = {
        "host": settings.effective_panweidb_host,
        "port": settings.effective_panweidb_port,
        "user": settings.effective_panweidb_user,
        "dbname": settings.effective_panweidb_db,
        "connect_timeout": settings.panweidb_connect_timeout,
        "application_name": APPLICATION_NAME,
        # 中文内容必须显式声明 UTF8，避免服务端按 SQL_ASCII 落库。
        "client_encoding": "UTF8",
    }
    password = settings.effective_panweidb_password
    if password:
        kwargs["password"] = password
    schema = settings.effective_panweidb_schema
    if schema:
        kwargs["options"] = f"-c search_path={schema}"
    if settings.panweidb_sslmode:
        kwargs["sslmode"] = settings.panweidb_sslmode
    return kwargs


def describe_target() -> str:
    """返回可安全打印的连接目标（不含口令）。"""
    kw = connection_kwargs()
    return f"panweidb://{kw['user']}@{kw['host']}:{kw['port']}/{kw['dbname']}"


def init_pg() -> Any:
    """初始化并打开同步连接池，返回池对象（幂等）。"""
    global _sync_pool
    with _lock:
        if _sync_pool is not None:
            return _sync_pool
        import psycopg_pool  # 延迟导入：MongoDB 模式下不引入该依赖的开销

        pool = psycopg_pool.ConnectionPool(
            kwargs=connection_kwargs(),
            min_size=settings.panweidb_pool_min_size,
            max_size=settings.panweidb_pool_max_size,
            name=f"{APPLICATION_NAME}-sync",
            open=False,
        )
        pool.open(wait=True, timeout=settings.panweidb_connect_timeout)
        _sync_pool = pool
        logger.info("PanWeiDB 同步连接池已就绪：%s", describe_target())
        return _sync_pool


def get_pool() -> Any:
    """返回同步池；未初始化时按需初始化。"""
    if _sync_pool is None:
        return init_pg()
    return _sync_pool


def close_pg() -> None:
    """关闭同步池（幂等）。"""
    global _sync_pool
    with _lock:
        if _sync_pool is not None:
            try:
                _sync_pool.close()
            except Exception:  # pragma: no cover - 关闭失败不应阻断进程退出
                logger.warning("关闭 PanWeiDB 同步连接池失败", exc_info=True)
            _sync_pool = None


def ping_sync(timeout: float = 2.0) -> bool:
    """健康探测：成功返回 True，任何异常都收敛为 False。"""
    try:
        pool = get_pool()
        with pool.connection(timeout=timeout) as conn:
            with conn.cursor() as cur:
                cur.execute("select 1")
                cur.fetchone()
        return True
    except Exception:
        logger.warning("PanWeiDB 探测失败", exc_info=True)
        return False


def health_payload() -> dict[str, Any]:
    """给 ``/health`` 用的后端信息快照（非阻塞、不抛异常）。"""
    backend = settings.effective_data_backend
    payload: dict[str, Any] = {"backend": backend}
    if backend == "panweidb":
        payload["target"] = describe_target()
        payload["reachable"] = ping_sync()
    return payload
