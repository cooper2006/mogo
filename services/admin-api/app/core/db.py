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

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Any = None
_db: Any = None
_audit_db: Any = None

#: PanWeiDB 模式的业务库 / 审计库门面缓存（避免每次 get_db 重建集合缓存）。
_pg_db: Any = None
_pg_audit_db: Any = None


def is_panweidb_backend() -> bool:
    return settings.effective_data_backend == "panweidb"


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

    server_selection_timeout_ms = int(os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "5000"))
    connect_timeout_ms = int(os.getenv("MONGODB_CONNECT_TIMEOUT_MS", "5000"))
    socket_timeout_ms = int(os.getenv("MONGODB_SOCKET_TIMEOUT_MS", "10000"))
    _client = AsyncIOMotorClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=server_selection_timeout_ms,
        connectTimeoutMS=connect_timeout_ms,
        socketTimeoutMS=socket_timeout_ms,
    )
    _db = _client[settings.mongodb_db]


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
    global _client, _db, _audit_db
    if _client is not None:
        _client.close()
    _client = None
    _db = None
    _audit_db = None


async def close_backend() -> None:
    """按当前后端关闭连接资源（启动/关闭路径统一入口）。"""
    if is_panweidb_backend():
        global _pg_db, _pg_audit_db
        from app.core import pg

        await pg.close_async_pg()
        pg.close_pg()
        _pg_db = None
        _pg_audit_db = None
        return
    close_db()


def get_db() -> Any:
    """返回业务库句柄（mongo: motor Database；panweidb: 兼容门面）。"""
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
            _pg_db = PgDatabase(pool, settings.effective_panweidb_schema)
        return _pg_db

    if _db is None:
        init_db()
    if _db is None:
        raise RuntimeError("MongoDB is not initialized")
    return _db


def get_audit_db() -> Any:
    """022 FR-17（T044）：审计日志库。

    * mongo：独立 database（``ASKAI_ADMIN_AUDIT_DB``），未配置时回退业务库。
    * panweidb：独立 **schema**（``PANWEIDB_AUDIT_SCHEMA``），未配置时回退业务
      schema —— PG 侧的等价隔离手段。

    审计链需要独立的备份、权限与生命周期，避免业务运维误删或改写审计事件。
    """
    global _audit_db, _pg_audit_db
    if is_panweidb_backend():
        from app.core import pg
        from app.core.pg_compat import PgDatabase

        pool = pg.get_async_pool()
        if pool is None:
            raise RuntimeError(
                "PanWeiDB 连接池尚未初始化：启动时应 await app.core.db.init_backend()"
            )
        if _pg_audit_db is None:
            _pg_audit_db = PgDatabase(pool, settings.effective_panweidb_audit_schema)
        return _pg_audit_db

    if _audit_db is None:
        init_db()
        if _client is None:
            raise RuntimeError("MongoDB is not initialized")
        _audit_db = _client[settings.effective_audit_db or settings.effective_mongodb_db]
    return _audit_db
