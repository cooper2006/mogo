"""058 T008 — 统一 32-hex 主键生成器的单测。

``generate_hex32_id`` 是 ``new_backend_id`` 的别名
（``services/chat-api/app/core/ids.py:79``）。真实保证：

* 形状为 32 位十六进制；
* 12-hex 毫秒时间戳前缀随时间单调不降（字典序≈创建时间序）；
* 高唯一性（10000 次生成碰撞率 < 1/65536）。

注意：同一毫秒内的多次生成由 20-hex 随机数区分，因此「完整 32-hex 的严格全局
单调」并不保证（随机后缀可能小于上一条）；本测试只断言时间戳前缀的单调不降与
整体唯一性，这是对业务（高水位游标 / 分页游标）真正有意义的保证。
"""

from __future__ import annotations

import time

from app.core.ids import HEX32_RE, generate_hex32_id, new_backend_id


def test_generate_hex32_id_is_alias_of_new_backend_id() -> None:
    assert generate_hex32_id is new_backend_id


def test_generate_hex32_id_shape_and_format() -> None:
    value = generate_hex32_id()
    assert HEX32_RE.match(value)
    assert len(value) == 32
    # 前缀 12-hex = 毫秒时间戳，必然 > 0
    assert int(value[:12], 16) > 0


def test_generate_hex32_id_unique_over_10000() -> None:
    ids = [generate_hex32_id() for _ in range(10000)]
    unique = set(ids)
    # 碰撞率 < 1/65536（这里要求零碰撞）
    assert len(ids) - len(unique) == 0
    assert (len(ids) - len(unique)) < (len(ids) / 65536)


def test_generate_hex32_id_timestamp_prefix_monotonic_non_decreasing() -> None:
    """时间戳前缀随时间单调不降（足够慢以致跨越毫秒边界则严格递增）。"""
    ids = [generate_hex32_id() for _ in range(500)]
    prefixes = [int(i[:12], 16) for i in ids]
    assert prefixes == sorted(prefixes)


def test_generate_hex32_id_prefix_reflects_current_time() -> None:
    before = int(time.time() * 1000)
    value = generate_hex32_id()
    after = int(time.time() * 1000)
    prefix_ms = int(value[:12], 16)
    assert before - 1 <= prefix_ms <= after + 1
