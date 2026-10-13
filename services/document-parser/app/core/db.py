"""数据访问入口 —— 按 ``MOGO_DATA_BACKEND`` 在后端之间分派。

* ``mongo``（默认）：同步 ``pymongo``，行为与迁移前完全一致。
* ``panweidb``：psycopg3 同步连接池 + :mod:`app.core.pg_compat` 兼容门面，
  对外形状与 pymongo 的 ``Database`` 一致，使既有调用点无需改动。

迁移背景、表结构约定、覆盖范围与分阶段计划见
``docs/mongo-to-panweidb-migration-plan.md``。

本服务历史上只用同步 pymongo，因此这里不需要 admin-api / chat-api 那套
「异步池必须在事件循环内建立」的处理：``init_db()`` 直接建同步池即可。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Any = None
_db: Any = None

#: PanWeiDB 模式的门面缓存（避免每次 get_db 重建集合缓存）。
_pg_db: Any = None


def is_panweidb_backend() -> bool:
    return settings.effective_data_backend == "panweidb"


def init_db() -> None:
    """按当前后端初始化连接资源（幂等）。"""
    global _client, _db
    if is_panweidb_backend():
        from app.core import pg

        pg.init_pg()
        return

    if _db is not None:
        return
    if not settings.mongodb_uri:
        raise RuntimeError("MongoDB URI is not configured")
    from pymongo import MongoClient

    server_selection_timeout_ms = int(os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "5000"))
    connect_timeout_ms = int(os.getenv("MONGODB_CONNECT_TIMEOUT_MS", "5000"))
    socket_timeout_ms = int(os.getenv("MONGODB_SOCKET_TIMEOUT_MS", "10000"))
    _client = MongoClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=server_selection_timeout_ms,
        connectTimeoutMS=connect_timeout_ms,
        socketTimeoutMS=socket_timeout_ms,
    )
    _db = _client[settings.mongodb_db]


def close_db() -> None:
    """按当前后端关闭连接资源（幂等）。"""
    global _client, _db, _pg_db
    if is_panweidb_backend():
        from app.core import pg

        pg.close_pg()
        _pg_db = None
        return
    if _client is not None:
        _client.close()
    _client = None
    _db = None


# 与 admin-api / chat-api 对齐的统一入口别名。
# document-parser 走同步路径，二者是 init_db / close_db 的等价物。
def init_backend() -> None:
    init_db()


def close_backend() -> None:
    close_db()


def get_db() -> Any:
    """返回业务库句柄（mongo: pymongo Database；panweidb: 兼容门面）。"""
    global _pg_db
    if is_panweidb_backend():
        from app.core import pg
        from app.core.pg_compat import PgDatabase

        pool = pg.get_pool()
        if _pg_db is None:
            _pg_db = PgDatabase(pool, settings.effective_panweidb_schema)
        return _pg_db

    if _db is None:
        init_db()
    if _db is None:
        raise RuntimeError("MongoDB is not initialized")
    return _db
