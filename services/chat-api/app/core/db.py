from __future__ import annotations

import os

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def init_db() -> None:
    global _client, _db
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


def close_db() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None


def get_db() -> AsyncIOMotorDatabase | None:
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
