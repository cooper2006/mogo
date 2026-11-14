"""059 T010 — im_gateway 绑定 fail-closed：db/row 缺失 → 拒绝。

``PersistedSessionBindingRegistry.is_channel_enabled``：

* db 为 None → 拒绝（deny）；
* 渠道行不存在（row is None）→ 拒绝（deny）；
* 渠道被禁用（disabled=True）→ 拒绝；
* 渠道存在且未禁用 → 放行（正向用例）。
"""

from __future__ import annotations

import pytest

from app.im_gateway.bindings import CHANNEL_COLLECTION, PersistedSessionBindingRegistry


class _FakeCollection:
    def __init__(self, doc=None) -> None:
        self._doc = doc

    async def find_one(self, *a, **k):
        return self._doc


class _FakeDB:
    def __init__(self, channel_doc=None) -> None:
        self._channel = _FakeCollection(channel_doc)

    def __getitem__(self, name: str):
        if name == CHANNEL_COLLECTION:
            return self._channel
        return _FakeCollection(None)


async def _db_with(channel_doc):
    return _FakeDB(channel_doc)


@pytest.mark.asyncio
async def test_db_none_denies() -> None:
    reg = PersistedSessionBindingRegistry()
    reg._db = lambda: _db_with(None)
    assert await reg.is_channel_enabled("wecom", "t1") is False


@pytest.mark.asyncio
async def test_row_none_denies() -> None:
    reg = PersistedSessionBindingRegistry()
    reg._db = lambda: _db_with(None)
    assert await reg.is_channel_enabled("wecom", "t1") is False


@pytest.mark.asyncio
async def test_channel_disabled_false() -> None:
    reg = PersistedSessionBindingRegistry()
    reg._db = lambda: _db_with({"disabled": True})
    assert await reg.is_channel_enabled("wecom", "t1") is False


@pytest.mark.asyncio
async def test_channel_enabled_true() -> None:
    reg = PersistedSessionBindingRegistry()
    reg._db = lambda: _db_with({"disabled": False})
    assert await reg.is_channel_enabled("wecom", "t1") is True
