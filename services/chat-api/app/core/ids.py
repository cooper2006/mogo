"""后端感知的主键归一化（MongoDB → PanWeiDB 迁移，T085）。

Mongo 的 ``_id`` 是 ``ObjectId``；PanWeiDB 侧落成 ``str(_id)`` 字符串（见
``docs/mongo-to-panweidb-migration-plan.md`` §4）。业务代码里 ``ObjectId(x)`` 的
构造与 ``ObjectId.is_valid`` 校验必须随之切换，否则 PanWeiDB 模式下用 ObjectId
查询会与字符串主键不匹配（``isinstance(_, ObjectId)`` 更是恒为 False）。

用 :func:`to_backend_id` / :func:`is_valid_backend_id` 取代直接 ``ObjectId(...)``
与 ``ObjectId.is_valid(...)``：

* mongo 模式行为与改造前**完全一致**（合法 24-hex → ObjectId）；
* panwei 模式一律用字符串（主键在库中即字符串）。

panwei 模式下的**存量兼容**：027 R1（commit 0f13656，2026-10-13）起
``pg_compat.insert_one`` 曾用 ``uuid4().hex``（32 位 hex）生成缺失的 ``_id``，
迁移期已产生一批 32-hex 主键（``end_users`` / ``end_user_sessions`` /
``chat_messages``）。迁移计划 §2.9/§4 约定主键统一为 ``str(ObjectId)``
（24-hex），故新 id 一律 24-hex；但存量的 32-hex 记录不能因此被守卫误杀
（否则新注册用户在 PanWeiDB 下完全无法登录），``is_valid_backend_id`` /
``to_backend_id_strict`` 在 panwei 模式下因此同时接受 24-hex 与 32-hex，
mongo 模式维持原语义（仅 24-hex 合法）。
"""

from __future__ import annotations

import re
from typing import Any

from bson import ObjectId

# 存量 PanWeiDB 32-hex 主键（commit 0f13656 的 uuid4().hex 遗留）。
_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")


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
    if ObjectId.is_valid(text):
        return True
    # 存量兼容：panwei 下迁移期 uuid4().hex 生成的 32-hex 主键仍需可查（见模块
    # docstring）；mongo 模式不接受 32-hex（其主键恒为 24-hex ObjectId）。
    return _is_panweidb() and bool(_HEX32.match(text))


def to_backend_id_strict(value: Any) -> Any:
    """同 :func:`to_backend_id`，但非法 id 抛 ``ValueError``。

    用于原先依赖 ``ObjectId(...)`` 构造抛错的调用点，保持其校验语义：
    mongo 下非法 24-hex 会抛错，panwei 下接受 24-hex（新建）与 32-hex
    （0f13656 存量）字符串主键，其余拒绝。
    """
    if value is None:
        raise ValueError("id 不能为空")
    if isinstance(value, ObjectId):
        return str(value) if _is_panweidb() else value
    text = str(value)
    if not is_valid_backend_id(text):
        raise ValueError(f"非法 id: {value!r}")
    return text if _is_panweidb() else ObjectId(text)
