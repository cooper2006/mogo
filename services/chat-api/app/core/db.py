"""数据访问入口 —— 按 ``MOGO_DATA_BACKEND`` 在后端之间分派。

* ``mongo``（默认）：motor（异步 MongoDB），行为与迁移前完全一致。
* ``panweidb``：psycopg3 异步连接池 + :mod:`app.core.pg_compat` 兼容门面，
  对外形状与 motor 的 ``Database`` 一致，使既有调用点无需改动。

迁移背景、表结构约定、覆盖范围与分阶段计划见
``docs/mongo-to-panweidb-migration-plan.md``。

**为什么异步池不在 ``init_db()`` 里建**：``psycopg`` 的异步连接会绑定当前
事件循环，``init_db()`` 是同步函数、可能被无循环的调用方（CLI、单测）触发。
因此启动路径统一走 :func:`init_backend`（异步），``init_db()`` 在 PanWeiDB
模式下显式失败而不是半初始化。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_client: Any = None
_db: Any = None

#: PanWeiDB 模式的门面缓存（避免每次 get_db 重建集合缓存）。
_pg_db: Any = None


def is_panweidb_backend() -> bool:
    return get_settings().effective_data_backend == "panweidb"


def init_db() -> None:
    """初始化 **MongoDB** 客户端（同步）。

    PanWeiDB 模式请使用 :func:`init_backend` —— 异步连接必须在事件循环内建立。
    """
    global _client, _db
    if is_panweidb_backend():
        raise RuntimeError(
            "MOGO_DATA_BACKEND=panweidb 时不能调用 init_db()："
            "psycopg 的异步连接必须在事件循环内建立，请改为 await init_backend()。"
        )
    from motor.motor_asyncio import AsyncIOMotorClient

    settings = get_settings()
    server_selection_timeout_ms = int(os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "5000"))
    connect_timeout_ms = int(os.getenv("MONGODB_CONNECT_TIMEOUT_MS", "5000"))
    socket_timeout_ms = int(os.getenv("MONGODB_SOCKET_TIMEOUT_MS", "10000"))
    _client = AsyncIOMotorClient(
        settings.MONGODB_URI,
        serverSelectionTimeoutMS=server_selection_timeout_ms,
        connectTimeoutMS=connect_timeout_ms,
        socketTimeoutMS=socket_timeout_ms,
    )
    _db = _client[settings.MONGODB_DB]


async def init_backend() -> None:
    """按 ``MOGO_DATA_BACKEND`` 初始化数据后端（启动路径统一入口）。"""
    if not is_panweidb_backend():
        init_db()
        return
    from app.core import pg

    await pg.init_async_pg()
    logger.info("数据后端 = panweidb（%s）", pg.describe_target())


def close_db() -> None:
    """关闭 MongoDB 客户端（幂等）。"""
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None


async def close_backend() -> None:
    """按当前后端关闭连接资源（关闭路径统一入口）。"""
    if is_panweidb_backend():
        global _pg_db
        from app.core import pg

        await pg.close_async_pg()
        pg.close_pg()
        _pg_db = None
        return
    close_db()


def get_db() -> Any:
    """返回业务库句柄（mongo: motor Database；panweidb: 兼容门面）。

    MongoDB 分支保留原有的「无事件循环返回 None」语义：同步调用方（单测、
    CLI）会走 ``db is None`` 的降级路径，而不是抛 "no current event loop"。
    """
    global _pg_db
    if is_panweidb_backend():
        from app.core import pg
        from app.core.pg_compat import PgDatabase

        pool = pg.get_async_pool()
        if pool is None:
            raise RuntimeError(
                "PanWeiDB 连接池尚未初始化：启动时应 await app.core.db.init_backend()"
            )
        if _pg_db is None:
            _pg_db = PgDatabase(pool, get_settings().effective_panweidb_schema)
        return _pg_db

    if _db is None:
        # Do not auto-initialise motor outside an async context: the driver
        # captures the running event loop, and sync callers (unit tests,
        # CLI scripts) have no loop to give it.  Returning None lets them
        # fall through to the db-None path instead of raising
        # "There is no current event loop".
        try:
            import asyncio

            asyncio.get_running_loop()
        except RuntimeError:
            return None
        init_db()
    if _db is None:
        raise RuntimeError("MongoDB is not initialized")
    return _db
