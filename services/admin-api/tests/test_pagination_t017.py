"""025 FR-6 (T017) — 统一分页 schema + cursor 翻页助手行为测试。

验证 `app/api/pagination.py`：
- cursor 编解码往返一致，非法游标安全返回 None
- PageResponse.build() 的 has_next / next_cursor 边界
- 响应 JSON 字段名为 snake_case 的 5 个分页字段
- PageParams 优先使用 cursor，回退到 page
"""

from __future__ import annotations

import json

from app.api.pagination import (
    PageParams,
    PageResponse,
    decode_cursor,
    encode_cursor,
)


class TestCursor:
    def test_roundtrip(self) -> None:
        cursor = encode_cursor(3, 25)
        assert decode_cursor(cursor) == (3, 25)

    def test_cursor_has_no_slash(self) -> None:
        # base64url 不允许 `/`，否则游标无法安全放进路径/query
        assert "/" not in encode_cursor(1, 20)

    def test_invalid_cursor_returns_none(self) -> None:
        for bad in ("", "!!!", "abc", "bm90LWEtcGFnZQ", "OjE="):
            assert decode_cursor(bad) is None, bad

    def test_out_of_range_rejected(self) -> None:
        cursor = encode_cursor(999, 201)
        assert decode_cursor(cursor) is None
        cursor = encode_cursor(0, 20)
        assert decode_cursor(cursor) is None


class TestBuild:
    def test_middle_page_has_next(self) -> None:
        resp = PageResponse.build(data=[1, 2, 3], total=100, page=2, page_size=20)
        assert resp.has_next is True
        assert decode_cursor(resp.next_cursor) == (3, 20)

    def test_last_page_no_next(self) -> None:
        resp = PageResponse.build(data=[1, 2, 3], total=43, page=3, page_size=20)
        assert resp.has_next is False
        assert resp.next_cursor is None

    def test_partial_page_no_next(self) -> None:
        resp = PageResponse.build(data=[1, 2], total=42, page=3, page_size=20)
        assert resp.has_next is False
        assert resp.next_cursor is None

    def test_empty_data_no_next(self) -> None:
        resp = PageResponse.build(data=[], total=0, page=1, page_size=20)
        assert resp.has_next is False
        assert resp.next_cursor is None

    def test_exact_fill_then_exhausted(self) -> None:
        # total 恰好 40，page 2 取满 20 条：已到末尾，无下一页
        resp = PageResponse.build(data=list(range(20)), total=40, page=2, page_size=20)
        assert resp.has_next is False
        assert resp.next_cursor is None


class TestResponseShape:
    def test_json_keys_are_snake_case_5_fields(self) -> None:
        resp = PageResponse.build(data=[{"id": 1}], total=1, page=1, page_size=20)
        payload = json.loads(resp.model_dump_json())
        assert set(payload) == {
            "data",
            "total",
            "page",
            "page_size",
            "has_next",
            "next_cursor",
        }


class TestPageParams:
    def test_cursor_takes_priority(self) -> None:
        params = PageParams(page=1, cursor=encode_cursor(7, 10))
        assert params.resolved_page() == 7

    def test_falls_back_to_page_on_bad_cursor(self) -> None:
        params = PageParams(page=4, cursor="not-a-valid-cursor")
        assert params.resolved_page() == 4

    def test_defaults(self) -> None:
        params = PageParams()
        assert params.page == 1
        assert params.page_size == 20
        assert params.cursor is None
        assert params.resolved_page() == 1