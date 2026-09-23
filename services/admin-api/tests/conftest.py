"""Test-session bootstrap for the admin-api test suite.

The governance / dashboard aggregation tests exercise pure logic and only import
Mongo-backed modules for their constants. On interpreters where the pinned
``motor==2.5.1`` cannot be imported (e.g. Python 3.11+, where
``asyncio.coroutine`` was removed), those imports would fail at collection time
even though the tests never touch a database.

To keep such tests runnable everywhere, we install a minimal ``motor`` stub **only
when the real driver is unavailable**. On a supported interpreter the real motor
imports fine and this module does nothing.
"""

from __future__ import annotations

import sys
import types


def _ensure_motor_available() -> None:
    try:
        import motor.motor_asyncio  # noqa: F401

        return
    except Exception:
        pass

    motor_module = types.ModuleType("motor")
    frameworks = types.ModuleType("motor.frameworks")
    asyncio_framework = types.ModuleType("motor.frameworks.asyncio")
    motor_asyncio = types.ModuleType("motor.motor_asyncio")

    class _AsyncIOMotorClient:  # pragma: no cover - placeholder only
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError("motor stub: no database in this test environment")

    class _AsyncIOMotorDatabase:  # pragma: no cover - placeholder only
        pass

    motor_asyncio.AsyncIOMotorClient = _AsyncIOMotorClient
    motor_asyncio.AsyncIOMotorDatabase = _AsyncIOMotorDatabase
    motor_module.motor_asyncio = motor_asyncio
    motor_module.frameworks = frameworks

    sys.modules.setdefault("motor", motor_module)
    sys.modules.setdefault("motor.frameworks", frameworks)
    sys.modules.setdefault("motor.frameworks.asyncio", asyncio_framework)
    sys.modules.setdefault("motor.motor_asyncio", motor_asyncio)


_ensure_motor_available()
