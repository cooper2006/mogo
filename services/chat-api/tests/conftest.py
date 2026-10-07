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
