"""阶段 2 终态：统一 32-hex 主键 helper 的单测。

旧语义（mongo=24-hex ObjectId / panwei=24+32 双读）已由
``docs/id-unification-hex32-runbook.md`` 描述的阶段 2 全库归一取代。
"""

from __future__ import annotations

import re

import pytest
from bson import ObjectId

from app.core import ids

HEX32 = "3522820df01b484fa94a9706a5adea25"
HEX24 = "507f1f77bcf86cd799439011"
HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def test_new_backend_id_shape_and_order():
    first = ids.new_backend_id()
    second = ids.new_backend_id()
    assert HEX32_RE.match(first)
    assert HEX32_RE.match(second)
    assert len(first) == 32
    # 12-hex 毫秒时间戳前缀，字典序≈时间序
    assert int(first[:12], 16) > 0
    assert int(second[:12], 16) >= int(first[:12], 16)


def test_new_backend_id_unique():
    assert len({ids.new_backend_id() for _ in range(200)}) == 200


def test_to_backend_id_only_stringifies():
    assert ids.to_backend_id(HEX32) == HEX32
    assert ids.to_backend_id("custom-key") == "custom-key"
    assert ids.to_backend_id(ObjectId(HEX24)) == HEX24
    assert ids.to_backend_id(None) is None
    # 不再把 24-hex 转成 ObjectId
    assert ids.to_backend_id(HEX24) == HEX24
    assert isinstance(ids.to_backend_id(HEX24), str)


def test_is_valid_backend_id_only_hex32():
    assert ids.is_valid_backend_id(HEX32) is True
    assert ids.is_valid_backend_id(HEX32.upper()) is True
    # 终态：ObjectId / 24-hex 明确不合法
    assert ids.is_valid_backend_id(HEX24) is False
    assert ids.is_valid_backend_id(ObjectId(HEX24)) is False
    assert ids.is_valid_backend_id("13000") is False
    assert ids.is_valid_backend_id("") is False
    assert ids.is_valid_backend_id(None) is False
    assert ids.is_valid_backend_id(HEX32[:31]) is False
    assert ids.is_valid_backend_id(HEX32 + "1") is False
    assert ids.is_valid_backend_id("zz" + HEX32[:30]) is False


def test_to_backend_id_strict():
    assert ids.to_backend_id_strict(HEX32) == HEX32
    with pytest.raises(ValueError):
        ids.to_backend_id_strict(HEX24)
    with pytest.raises(ValueError):
        ids.to_backend_id_strict(ObjectId(HEX24))
    with pytest.raises(ValueError):
        ids.to_backend_id_strict("not-an-id")
    with pytest.raises(ValueError):
        ids.to_backend_id_strict(None)
