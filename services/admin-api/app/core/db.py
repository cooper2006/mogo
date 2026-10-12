from __future__ import annotations

import os

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None
_audit_db: AsyncIOMotorDatabase | None = None


def init_db() -> None:
    global _client, _db
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


def close_db() -> None:
    global _client, _db, _audit_db
    if _client is not None:
        _client.close()
    _client = None
    _db = None
    _audit_db = None


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        init_db()
    if _db is None:
        raise RuntimeError("MongoDB is not initialized")
    return _db


def get_audit_db() -> AsyncIOMotorDatabase:
    """022 FR-17（T044）：审计日志库。

    与业务库分离 —— 审计链需要独立的备份、权限与生命周期，
    避免业务运维误删或改写审计事件。未配置 ``ASKAI_ADMIN_AUDIT_DB``
    （或 ``MONGODB_AUDIT_DB``）时回退到业务库，保证既有部署可用。
    """
    if _audit_db is None:
        init_db()
        if _client is None:
            raise RuntimeError("MongoDB is not initialized")
        _audit_db = _client[settings.effective_audit_db or settings.effective_mongodb_db]
    return _audit_db
