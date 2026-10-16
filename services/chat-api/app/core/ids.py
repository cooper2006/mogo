"""后端感知的主键归一化（MongoDB → PanWeiDB 迁移，T085）。

Mongo 的 ``_id`` 是 ``ObjectId``；PanWeiDB 侧落成 ``str(_id)`` 字符串（见
``docs/mongo-to-panweidb-migration-plan.md`` §4）。业务代码里 ``ObjectId(x)`` 的
构造与 ``ObjectId.is_valid`` 校验必须随之切换，否则 PanWeiDB 模式下用 ObjectId
查询会与字符串主键不匹配（``isinstance(_, ObjectId)`` 更是恒为 False）。

用 :func:`to_backend_id` / :func:`is_valid_backend_id` 取代直接 ``ObjectId(...)``
与 ``ObjectId.is_valid(...)``：

* mongo 模式行为与改造前**完全一致**（合法 24-hex → ObjectId）；
* panwei 模式一律用字符串（主键在库中即字符串）。
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId


def _is_panweidb() -> bool:
    # 延迟导入：避免 ids ← db ← ... 的导入环，并让测试可 patch 后端开关。
    from app.core.db import is_panweidb_backend

    return is_panweidb_backend()


def to_backend_id(value: Any) -> Any:
    """把 id 值转成当前后端用于查询 / 存储的形式。

    * mongo：合法 24 位十六进制字符串 → ``ObjectId``，否则原样返回；
    * panwei：一律 ``str``（主键在库中是字符串）。
    """
    if value is None:
        return None
    if isinstance(value, ObjectId):
        return str(value) if _is_panweidb() else value
    if _is_panweidb():
        return str(value)
    text = str(value)
    return ObjectId(text) if ObjectId.is_valid(text) else value


def is_valid_backend_id(value: Any) -> bool:
    """当前后端下该值是否为可安全用于 ``_id`` 查询的合法主键。"""
    if value is None:
        return False
    if isinstance(value, ObjectId):
        return True
    text = str(value)
    # 两种后端的主键都由 ObjectId 生成（panwei 落成 str(_id) = 24-hex），故合法性
    # 判定一致，保持依赖 ObjectId.is_valid 的既有校验语义（invalid id 应被拒）。
    return ObjectId.is_valid(text)


def to_backend_id_strict(value: Any) -> Any:
    """同 :func:`to_backend_id`，但非法 id 抛 ``ValueError``。

    用于原先依赖 ``ObjectId(...)`` 构造抛错的调用点，保持其校验语义：
    mongo 下非法 24-hex 会抛错，panwei 下同样拒绝非法 id（主键即 24-hex 字符串）。
    """
    if value is None:
        raise ValueError("id 不能为空")
    if isinstance(value, ObjectId):
        return str(value) if _is_panweidb() else value
    text = str(value)
    if not ObjectId.is_valid(text):
        raise ValueError(f"非法 id: {value!r}")
    return text if _is_panweidb() else ObjectId(text)
