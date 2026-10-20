"""T085：后端感知主键归一化 helper 的单测。"""

from __future__ import annotations

from bson import ObjectId

from app.core import ids

VALID = "507f1f77bcf86cd799439011"
# 0f13656 遗留：uuid4().hex 生成的 32-hex 主键（存量兼容样本）。
HEX32 = "3522820df01b484fa94a9706a5adea25"


def test_mongo_mode_converts_valid_id_to_objectid(monkeypatch):
    monkeypatch.setattr(ids, "_is_panweidb", lambda: False)
    assert ids.to_backend_id(VALID) == ObjectId(VALID)
    assert isinstance(ids.to_backend_id(VALID), ObjectId)
    # 非 24-hex 原样返回（与改造前 ObjectId 构造前的行为一致：不抛）
    assert ids.to_backend_id("not-an-id") == "not-an-id"
    assert ids.to_backend_id(None) is None
    assert ids.is_valid_backend_id(VALID) is True
    assert ids.is_valid_backend_id("nope") is False
    assert ids.is_valid_backend_id(None) is False
    # mongo 模式主键恒为 24-hex ObjectId，32-hex 不合法
    assert ids.is_valid_backend_id(HEX32) is False


def test_panwei_mode_uses_string(monkeypatch):
    monkeypatch.setattr(ids, "_is_panweidb", lambda: True)
    # 一律字符串：合法 24-hex、任意串、以及传入的 ObjectId 都归一为 str
    assert ids.to_backend_id(VALID) == VALID
    assert ids.to_backend_id("custom-id-1") == "custom-id-1"
    assert ids.to_backend_id(ObjectId(VALID)) == VALID
    assert ids.to_backend_id(None) is None
    # 合法性判定：mongo 语义（24-hex 合法）＋ 存量兼容（panwei 接受 32-hex）
    assert ids.is_valid_backend_id(VALID) is True
    assert ids.is_valid_backend_id(HEX32) is True
    assert ids.is_valid_backend_id("any-nonempty") is False
    assert ids.is_valid_backend_id("") is False
    assert ids.is_valid_backend_id(None) is False
    assert ids.is_valid_backend_id(ObjectId(VALID)) is True
    # 31 位 / 33 位 hex 不属于 24-hex / 32-hex，仍非法
    assert ids.is_valid_backend_id(VALID[:-1]) is False
    assert ids.is_valid_backend_id(HEX32 + "1") is False


def test_to_backend_id_strict_raises_on_invalid(monkeypatch):
    import pytest

    monkeypatch.setattr(ids, "_is_panweidb", lambda: False)
    assert ids.to_backend_id_strict(VALID) == ObjectId(VALID)
    with pytest.raises(ValueError):
        ids.to_backend_id_strict("not-an-id")
    with pytest.raises(ValueError):
        ids.to_backend_id_strict(None)
    # mongo 模式不接受 32-hex（存量 32-hex 只存在于 panwei）
    with pytest.raises(ValueError):
        ids.to_backend_id_strict(HEX32)


def test_to_backend_id_strict_panwei(monkeypatch):
    import pytest

    monkeypatch.setattr(ids, "_is_panweidb", lambda: True)
    assert ids.to_backend_id_strict(VALID) == VALID
    assert ids.to_backend_id_strict(ObjectId(VALID)) == VALID
    # 存量 32-hex 主键：panwei 模式下可查，不抛
    assert ids.to_backend_id_strict(HEX32) == HEX32
    with pytest.raises(ValueError):
        ids.to_backend_id_strict("not-an-id")
    with pytest.raises(ValueError):
        ids.to_backend_id_strict(None)


def test_panwei_32hex_boundary_lengths(monkeypatch):
    """32-hex 恰好 32 位才合法；31 / 33 位与非 hex 字符均拒。"""
    monkeypatch.setattr(ids, "_is_panweidb", lambda: True)
    assert ids.is_valid_backend_id(HEX32) is True
    assert ids.is_valid_backend_id(HEX32[:31]) is False      # 31 位
    assert ids.is_valid_backend_id(HEX32 + "1") is False      # 33 位
    assert ids.is_valid_backend_id("zz" + HEX32[:30]) is False  # 非 hex 字符


def test_mongo_strict_rejects_32hex(monkeypatch):
    """mongo 模式下 to_backend_id_strict 对 32-hex 仍抛 ValueError。"""
    import pytest

    monkeypatch.setattr(ids, "_is_panweidb", lambda: False)
    with pytest.raises(ValueError):
        ids.to_backend_id_strict(HEX32)
