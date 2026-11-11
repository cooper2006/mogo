"""统一 32-hex 字符串主键（阶段 2/3 终态）。

历史背景：Mongo 侧 ``_id`` 曾是 ``ObjectId``（24-hex），PanWeiDB 迁移期
``pg_compat.insert_one`` 曾用 ``uuid4().hex``（32-hex）补齐缺失主键，两套形态
长期并存，导致 ``_safe_oid`` / ``ObjectId.is_valid`` 守卫对 32-hex 主键抛 400。
2026-11-10 的阶段 2 全库归一（``scripts/migrate_ids_to_hex32.py``，见
``docs/id-unification-hex32-runbook.md``）之后，终态约定为：

* 所有**系统生成的实体主键**一律是 32 位十六进制字符串；
* ``is_valid_backend_id`` / ``to_backend_id_strict`` **只认 32-hex**，不再接受
  ``ObjectId`` 实例或 24-hex 字符串；
* ``to_backend_id`` 只做字符串化（``ObjectId`` → ``str``），不再把 24-hex 转成
  ``ObjectId`` 用于查询；旧格式传入后查不到数据，等同于被拒绝；
* **业务自然键**（组织编码 ``"13000"``、状态单例 ``"singleton"``、复合键
  ``"<doc_id>:raw:raw_000001"`` 等）不是实体 ID，不经过本模块守卫，由各自
  调用点处理，白名单见迁移脚本的 ``NATURAL_KEY_COLLECTIONS``。

新 ID 形如 ``12-hex 毫秒时间戳 + 20-hex 随机数``：字典序≈创建时间序，保留
``_id`` 作为高水位游标（skill quality collector）与分页游标（member directory）
的既有语义，避免 ``uuid4().hex`` 导致的顺序倒退。
"""

from __future__ import annotations

import re
import secrets
import time
from typing import Any

from bson import ObjectId

#: 终态唯一合法的实体主键形态。
HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")

_TIMESTAMP_HEX_LEN = 12
_RANDOM_HEX_LEN = 20


def new_backend_id() -> str:
    """生成时间有序的 32-hex 主键。

    12 位 hex 毫秒时间戳（48 bit，可用到公元 10889 年）+ 20 位 hex 随机数。
    写入路径由 :mod:`app.core.hex32_db` 统一注入，业务代码无需自己生成。
    """
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    return f"{ms:0{_TIMESTAMP_HEX_LEN}x}{secrets.token_hex(_RANDOM_HEX_LEN // 2)}"


def to_backend_id(value: Any) -> str | None:
    """把 id 值转成字符串形式用于查询 / 存储（**不校验**）。

    终态库里主键就是字符串，因此这里只做 ``str()``。传入 ``ObjectId`` 会得到
    24-hex 字符串，在终态库中查不到任何记录——即旧格式被静默拒绝，而不会像
    ``ObjectId(...)`` 那样抛异常打断调用链。需要显式拒绝时请用
    :func:`is_valid_backend_id` 或 :func:`to_backend_id_strict`。
    """
    if value is None:
        return None
    return str(value)


def is_valid_backend_id(value: Any) -> bool:
    """终态守卫：只有 32-hex 字符串是合法实体主键。"""
    if value is None or isinstance(value, ObjectId):
        return False
    return bool(HEX32_RE.match(str(value)))


def to_backend_id_strict(value: Any) -> str:
    """同 :func:`to_backend_id`，但非 32-hex 一律抛 ``ValueError``。"""
    if not is_valid_backend_id(value):
        raise ValueError(f"非法 id（终态只接受 32-hex）: {value!r}")
    return str(value)
