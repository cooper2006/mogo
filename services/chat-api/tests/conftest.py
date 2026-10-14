"""Test-session bootstrap for the chat-api test suite.

QF-106: Fix TZ/LANG to Asia/Shanghai and en_US.UTF-8 for test determinism.
"""
from __future__ import annotations

import os
import sys
import types

# QF-106: 显式固定时区与语言环境
os.environ.setdefault("TZ", "Asia/Shanghai")
os.environ.setdefault("LANG", "en_US.UTF-8")
os.environ.setdefault("LC_ALL", "en_US.UTF-8")

# The session-versioning / hooks / resilience tests exercise pure logic and only
# import Mongo-backed modules (or the DSH runtime package) for their constants. On
# interpreters where the pinned ``motor==2.5.1`` cannot be imported (e.g. Python
# 3.11+, where ``asyncio.coroutine`` was removed), those imports would fail at
# collection time even though the tests never touch a database.
#
# To keep such tests runnable everywhere, we install a minimal ``motor`` stub **only
# when the real driver is unavailable**. On a supported interpreter the real motor
# imports fine and this module does nothing.


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


import pytest


@pytest.fixture(autouse=True)
def _reset_db_state():
    """Reset module-level motor client/db state before & after every test.

    Some async tests initialise ``app.core.db`` (which captures the running
    event loop).  When pytest-asyncio closes that loop, later sync tests that
    call ``get_db()`` receive a stale ``_db`` whose motor client can no longer
    find a live event loop (Python 3.13: ``RuntimeError: There is no current
    event loop``).  Closing the client around each test restores the db-None
    path that pure-logic tests rely on.
    """
    from app.core.db import close_db

    close_db()
    yield
    close_db()


@pytest.fixture(autouse=True)
def _panwei_backend_stub(monkeypatch):
    """（迁移适配）PanWeiDB 模式下隔离 db 门面缓存，并给「不连真库」的单测提供
    惰性池替身。

    ``get_db()`` 在 panwei 模式、异步池未初始化时**显式 raise**——异步池须绑定
    事件循环，而本套单测多用 ``asyncio.run`` 各自建 loop，无法跨 loop 复用真池。
    这里让 ``get_async_pool`` **透传真池**（若已由 lifespan / async fixture 建好），
    否则返回 stub 使 ``get_db()`` 不 raise；真查询打到 stub 会**显式报错**（不静默
    返回空）。同时重置 db 门面缓存，避免跨测试拿到上一测试的池。仅 panwei 模式生效。
    """
    from app.core import pg

    if not pg.is_panweidb_backend():
        yield
        return

    from app.core import db

    db._pg_db = None
    db._pg_audit_db = None
    real = pg.get_async_pool

    class _StubPool:
        def connection(self, *args, **kwargs):  # pragma: no cover - 真查询即报错
            raise RuntimeError("test stub: 单测不连真实 PanWeiDB")

    monkeypatch.setattr(pg, "get_async_pool", lambda: real() or _StubPool())
    yield


@pytest.fixture(autouse=True)
async def _panwei_init_backend():
    """（迁移适配）PanWeiDB 模式下为 async 测试建立真池（绑定本测试事件循环），
    使需要真实查询的集成测试可用；teardown 关闭，供下个测试重建。仅 panwei 生效。
    """
    from app.core import pg

    if not pg.is_panweidb_backend():
        yield
        return

    from app.core import db

    await db.init_backend()
    yield
    await db.close_backend()


# --- DSH Runtime Host end-to-end tagging -----------------------------------
#
# These tests spawn the real Node Runtime Host (``dsh/runtime-host``) via
# subprocess and drive it over HTTP. They need a working Node toolchain and a
# free loopback port; when either is unavailable they fail with
# "DSH Runtime Host did not become healthy before the startup deadline", which
# is indistinguishable from a real regression in a red CI log.
#
# Tagging them lets CI separate "needs a Runtime Host" from "actually broken":
#   pytest -m "not dsh_host_e2e"   # unit + contract only (default local run)
#   pytest -m "dsh_host_e2e"       # requires the Runtime Host service
#
# The host probes itself over loopback, so the proxy environment must not
# intercept it; ``DshRuntimeHostManager`` already sets ``trust_env=False``.

_DSH_HOST_E2E_FILES = (
    "test_runtime_host_e2e.py",
    "test_model_profile_host_e2e.py",
    "test_step5_dsh_tool_e2e.py",
    "conversation_regression/test_conversation_capabilities.py",
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "dsh_host_e2e: requires a spawnable Node DSH Runtime Host (subprocess + loopback HTTP)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    for item in items:
        path = str(getattr(item, "fspath", ""))
        if any(path.endswith(name) for name in _DSH_HOST_E2E_FILES):
            item.add_marker(pytest.mark.dsh_host_e2e)
