"""PanWeiDB（openGauss 内核 / PostgreSQL 兼容线协议）连接池。

与 :mod:`app.core.db` 的 MongoDB 路径并列存在，由 ``MOGO_DATA_BACKEND``
开关选择（``mongo`` 默认 / ``panweidb``）。设计细节与分阶段计划见
``docs/mongo-to-panweidb-migration-plan.md``。

设计要点：

* **惰性初始化**：只有真正走到 PanWeiDB 分支时才建池，MongoDB 模式零开销。
* **同步 + 异步双池**：MongoDB 侧同时存在 ``pymongo``（同步）与 ``motor``
  （异步）两套用法，迁移后对应 ``psycopg`` 的同步连接与 ``AsyncConnection``。
* **不自动建池**：异步池必须在事件循环内创建（``psycopg`` 会绑定当前循环），
  同步调用方（CLI、单测）拿不到循环时应显式失败而不是静默降级。

实测环境（2026-10-13）：PanWeiDB 3.2.0 / ``sql_compatibility=A`` / 端口 5432 /
``password_encryption_type=1``（MD5）。psycopg3 的同步、异步、连接池、JSONB、
参数绑定均已验证通过。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

# psycopg_pool 的连接池对象；None 表示尚未初始化。
_sync_pool: Any = None
_async_pool: Any = None
_lock = threading.Lock()

#: 本服务名，写入 libpq ``application_name``，便于在 PanWeiDB 侧排查连接来源。
APPLICATION_NAME = "mogo-admin-api"


def is_panweidb_backend() -> bool:
    """当前是否选中 PanWeiDB 后端。"""
    return settings.effective_data_backend == "panweidb"


def connection_kwargs() -> dict[str, Any]:
    """组装 libpq 连接参数。

    未显式配置 ``PANWEIDB_*`` 时回退到本地默认值，方便开发者直接对接
    OrbStack 里跑起来的 PanWeiDB 容器。
    """
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
        # openGauss 支持通过 libpq options 设置 search_path。
        kwargs["options"] = f"-c search_path={schema}"
    sslmode = settings.panweidb_sslmode
    if sslmode:
        kwargs["sslmode"] = sslmode
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
            # 池名便于日志排查；open=False 后显式 open，避免构造函数里隐式建连。
            name=f"{APPLICATION_NAME}-sync",
            open=False,
        )
        pool.open(wait=True, timeout=settings.panweidb_connect_timeout)
        _sync_pool = pool
        logger.info("PanWeiDB 同步连接池已就绪：%s", describe_target())
        return _sync_pool


async def init_async_pg() -> Any:
    """初始化并打开异步连接池，返回池对象（幂等）。

    必须在事件循环内调用：``psycopg`` 的异步连接会绑定当前循环。
    """
    global _async_pool
    if _async_pool is not None:
        return _async_pool
    import psycopg_pool

    pool = psycopg_pool.AsyncConnectionPool(
        kwargs=connection_kwargs(),
        min_size=settings.panweidb_pool_min_size,
        max_size=settings.panweidb_pool_max_size,
        name=f"{APPLICATION_NAME}-async",
        open=False,
    )
    await pool.open(wait=True, timeout=settings.panweidb_connect_timeout)
    _async_pool = pool
    logger.info("PanWeiDB 异步连接池已就绪：%s", describe_target())
    return _async_pool


def get_pool() -> Any:
    """返回同步池；未初始化时按需初始化。"""
    if _sync_pool is None:
        return init_pg()
    return _sync_pool


def get_async_pool() -> Any:
    """返回异步池；未初始化时返回 None。

    与 :func:`app.core.db.get_db` 的取舍一致：不在非异步上下文里偷偷建异步池，
    让同步调用方走 ``db is None`` 的降级路径，而不是抛
    "no current event loop"。
    """
    return _async_pool


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


async def close_async_pg() -> None:
    """关闭异步池（幂等）。"""
    global _async_pool
    if _async_pool is not None:
        try:
            await _async_pool.close()
        except Exception:  # pragma: no cover
            logger.warning("关闭 PanWeiDB 异步连接池失败", exc_info=True)
        _async_pool = None


def ping_sync(timeout: float = 2.0) -> bool:
    """同步健康探测：成功返回 True，任何异常都收敛为 False。"""
    try:
        pool = get_pool()
        with pool.connection(timeout=timeout) as conn:
            with conn.cursor() as cur:
                cur.execute("select 1")
                cur.fetchone()
        return True
    except Exception:
        logger.warning("PanWeiDB 同步探测失败", exc_info=True)
        return False


async def ping_async(timeout: float = 2.0) -> bool:
    """异步健康探测：成功返回 True，任何异常都收敛为 False。"""
    try:
        pool = _async_pool or await init_async_pg()
        async with pool.connection(timeout=timeout) as conn:
            async with conn.cursor() as cur:
                await cur.execute("select 1")
                await cur.fetchone()
        return True
    except Exception:
        logger.warning("PanWeiDB 异步探测失败", exc_info=True)
        return False


async def health_payload() -> dict[str, Any]:
    """给 ``/health`` 用的后端信息快照（不抛异常）。

    异步探测：本服务是异步进程，用同步池做健康检查会额外创建一组同步连接，
    属于纯粹的浪费。MongoDB 模式不引入任何额外连接开销。
    """
    backend = settings.effective_data_backend
    payload: dict[str, Any] = {"backend": backend}
    if backend == "panweidb":
        payload["target"] = describe_target()
        payload["reachable"] = await ping_async()
    return payload
