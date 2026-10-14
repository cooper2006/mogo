"""T085：后端感知主键归一化 helper 的单测。"""

from __future__ import annotations

from bson import ObjectId

from app.core import ids

VALID = "507f1f77bcf86cd799439011"


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


def test_panwei_mode_uses_string(monkeypatch):
    monkeypatch.setattr(ids, "_is_panweidb", lambda: True)
    # 一律字符串：合法 24-hex、任意串、以及传入的 ObjectId 都归一为 str
    assert ids.to_backend_id(VALID) == VALID
    assert ids.to_backend_id("custom-id-1") == "custom-id-1"
    assert ids.to_backend_id(ObjectId(VALID)) == VALID
    assert ids.to_backend_id(None) is None
    # panwei 主键即字符串：任意非空即合法，空串不合法
    assert ids.is_valid_backend_id(VALID) is True
    assert ids.is_valid_backend_id("any-nonempty") is True
    assert ids.is_valid_backend_id("") is False
    assert ids.is_valid_backend_id(None) is False
