"""Tests for the platform super-admin bootstrap (Phase 3 / T014 + T055).

The env-var bootstrap (``ASKAI_ADMIN_PLATFORM_ADMIN_PASSWORD``) was removed:
the platform admin is created only via the ``/setup`` wizard and its
credentials live in ``admin_accounts``. ``bootstrap_platform_admin`` therefore
only checks existence and warns, never creates an account.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from app.services import platform_bootstrap


class _Collection:
    def __init__(self, doc) -> None:
        self._doc = doc

    async def find_one(self, *args, **kwargs):
        return self._doc


class _DB:
    def __init__(self, doc) -> None:
        self._collection = _Collection(doc)

    def __getitem__(self, name: str) -> _Collection:
        return self._collection


def test_platform_admin_exists_true(monkeypatch) -> None:
    monkeypatch.setattr(platform_bootstrap, "get_db", lambda: _DB({"_id": "x"}))
    assert asyncio.run(platform_bootstrap.platform_admin_exists()) is True


def test_platform_admin_exists_false(monkeypatch) -> None:
    monkeypatch.setattr(platform_bootstrap, "get_db", lambda: _DB(None))
    assert asyncio.run(platform_bootstrap.platform_admin_exists()) is False


def test_bootstrap_warns_when_missing(monkeypatch) -> None:
    """No platform admin → warn, never create (no env-var bootstrap anymore)."""
    monkeypatch.setattr(platform_bootstrap, "get_db", lambda: _DB(None))
    ensure = AsyncMock(return_value={})
    monkeypatch.setattr(platform_bootstrap, "ensure_platform_admin", ensure)

    asyncio.run(platform_bootstrap.bootstrap_platform_admin())

    ensure.assert_not_awaited()


def test_bootstrap_is_single_admin(monkeypatch) -> None:
    """Decision 19: never create a second platform admin when one exists."""
    monkeypatch.setattr(platform_bootstrap, "get_db", lambda: _DB({"_id": "existing"}))
    ensure = AsyncMock(return_value={})
    monkeypatch.setattr(platform_bootstrap, "ensure_platform_admin", ensure)

    asyncio.run(platform_bootstrap.bootstrap_platform_admin())

    ensure.assert_not_awaited()
