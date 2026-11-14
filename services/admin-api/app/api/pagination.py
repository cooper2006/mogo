"""025 FR-6 (T017)：统一分页 schema + cursor 翻页助手（QF-213, QF-216）。

约定（snake_case，固定 5 个分页字段）：
    data        本页数据
    total       满足过滤条件的总条数
    page        当前页（从 1 起）
    page_size   每页条数
    has_next    是否还有下一页
    next_cursor 下一页游标（base64url 编码 `page|page_size`；没有下一页时为 None）

cursor 采用「页码 + 每页条数」编码（不是记录主键），实现**稳定翻页**：
在同一个查询参数快照下，用游标翻页不会因新写入的记录而错位
（offset = (page-1) * page_size，游标本身就是页码的加密化表示）。

用法：路由里用 `PageParams` 收参，查询后用 `PageResponse.build()` 组装响应。
"""

from __future__ import annotations

import base64
from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

# cursor 的合法字符集（base64url），避免游标里出现 `/` 干扰路径
_CURSOR_SEP = ":"


class PageParams(BaseModel):
    """分页请求参数。作为 query 参数注入：`params: PageParams = Depends()`。"""

    model_config = ConfigDict(extra="ignore")

    page: Annotated[int, Query(ge=1, description="页码，从 1 起")] = 1
    page_size: Annotated[int, Query(ge=1, le=200, description="每页条数")] = 20
    cursor: Annotated[
        str | None,
        Query(description="上一页返回的 next_cursor；提供时优先于 page"),
    ] = None

    def resolved_page(self) -> int:
        """优先使用游标；游标无效或缺失时回退到 page。"""
        if self.cursor:
            decoded = decode_cursor(self.cursor)
            if decoded is not None:
                return decoded[0]
        return self.page


def encode_cursor(page: int, page_size: int) -> str:
    """把 `page|page_size` 编码为 base64url 游标。"""
    raw = f"{int(page)}{_CURSOR_SEP}{int(page_size)}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[int, int] | None:
    """解码游标为 (page, page_size)；非法游标返回 None（调用方回退到 page 参数）。"""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception:
        return None
    parts = raw.split(_CURSOR_SEP)
    if len(parts) != 2:
        return None
    try:
        page = int(parts[0])
        page_size = int(parts[1])
    except ValueError:
        return None
    if page < 1 or page_size < 1 or page_size > 200:
        return None
    return page, page_size


class PageResponse(BaseModel, Generic[T]):
    """统一分页响应体（5 个分页字段，snake_case）。"""

    model_config = ConfigDict(extra="ignore")

    data: list[T] = Field(description="本页数据")
    total: int = Field(description="满足过滤条件的总条数")
    page: int = Field(description="当前页，从 1 起")
    page_size: int = Field(description="每页条数")
    has_next: bool = Field(description="是否还有下一页")
    next_cursor: str | None = Field(default=None, description="下一页游标；无下一页为 None")

    @classmethod
    def build(
        cls,
        data: list[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PageResponse[T]":
        """组装分页响应：根据本页条数与总数计算 has_next / next_cursor。

        - `has_next`：本页取满 `page_size` 条 且 已取到的位置未到 `total`。
          （`page * page_size < total` 是充分条件；若本页不满则必无下一页。）
        - `next_cursor`：仅当 `has_next` 时给出，编码 `page + 1`。
        """
        page = max(1, int(page))
        page_size = max(1, int(page_size))
        has_next = bool(data) and (page * page_size) < int(total)
        return cls(
            data=data,
            total=int(total),
            page=page,
            page_size=page_size,
            has_next=has_next,
            next_cursor=encode_cursor(page + 1, page_size) if has_next else None,
        )