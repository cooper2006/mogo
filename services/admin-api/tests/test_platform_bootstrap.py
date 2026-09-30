"""Tests for the platform super-admin bootstrap (Phase 3 / T014 + T055)."""

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


def test_bootstrap_skips_without_password(monkeypatch) -> None:
    monkeypatch.setattr(platform_bootstrap, "get_db", lambda: _DB(None))
    monkeypatch.setattr(platform_bootstrap.settings, "platform_admin_password", "")
    ensure = AsyncMock(return_value={})
    monkeypatch.setattr(platform_bootstrap, "ensure_platform_admin", ensure)

    asyncio.run(platform_bootstrap.bootstrap_platform_admin())

    ensure.assert_not_awaited()


def test_bootstrap_creates_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(platform_bootstrap, "get_db", lambda: _DB(None))
    monkeypatch.setattr(platform_bootstrap.settings, "platform_admin_password", "secret12345")
    monkeypatch.setattr(platform_bootstrap.settings, "platform_admin_username", "platform")
    monkeypatch.setattr(platform_bootstrap.settings, "platform_admin_display_name", "平台管理员")
    ensure = AsyncMock(return_value={})
    monkeypatch.setattr(platform_bootstrap, "ensure_platform_admin", ensure)

    asyncio.run(platform_bootstrap.bootstrap_platform_admin())

    ensure.assert_awaited_once_with(
        username="platform",
        password="secret12345",
        display_name="平台管理员",
    )


def test_bootstrap_is_single_admin(monkeypatch) -> None:
    """Decision 19: never create a second platform admin when one exists."""
    monkeypatch.setattr(platform_bootstrap, "get_db", lambda: _DB({"_id": "existing"}))
    monkeypatch.setattr(platform_bootstrap.settings, "platform_admin_password", "secret12345")
    ensure = AsyncMock(return_value={})
    monkeypatch.setattr(platform_bootstrap, "ensure_platform_admin", ensure)

    asyncio.run(platform_bootstrap.bootstrap_platform_admin())

    ensure.assert_not_awaited()
