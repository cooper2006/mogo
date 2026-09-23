"""Test-session bootstrap for the chat-api test suite.

The session-versioning / hooks / resilience tests exercise pure logic and only
import Mongo-backed modules (or the DSH runtime package) for their constants. On
interpreters where the pinned ``motor==2.5.1`` cannot be imported (e.g. Python
3.11+, where ``asyncio.coroutine`` was removed), those imports would fail at
collection time even though the tests never touch a database.

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


def _lighten_dsh_runtime_package() -> None:
    """Avoid loading the heavy DSH runtime package init for pure-logic tests.

    ``app.dsh_runtime.__init__`` eagerly imports gateway / host manager / profile
    machinery, which in turn pulls the LLM factory and its driver deps. Tests for
    ``app.dsh_runtime.hooks`` only need the subpackage, so when that eager chain
    cannot be imported we register ``app.dsh_runtime`` as a *namespace* package
    (same ``__path__``, no ``__init__`` side effects).
    """
    try:
        import app.dsh_runtime  # noqa: F401

        return
    except Exception:
        pass

    import importlib.util
    import pathlib

    package_dir = pathlib.Path(__file__).resolve().parents[1] / "app" / "dsh_runtime"
    if not package_dir.is_dir():
        return
    spec = importlib.util.spec_from_loader("app.dsh_runtime", loader=None, is_package=True)
    if spec is None:
        return
    module = importlib.util.module_from_spec(spec)
    module.__path__ = [str(package_dir)]  # type: ignore[attr-defined]
    sys.modules["app.dsh_runtime"] = module


_ensure_motor_available()
_lighten_dsh_runtime_package()
