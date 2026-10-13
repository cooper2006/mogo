#!/usr/bin/env python3
"""把 admin-api 的兼容层同步到另两个服务。

三个服务各自独立构建（构建上下文是 ``services/<svc>``），因此兼容层在仓库里有
三份副本 —— 与既有的 ``db.py`` / ``config.py`` 处理方式一致。手工维护三份必然漂移，
所以：

* **异步两份逐字节相同**：admin-api 与 chat-api 都用 motor，直接复制。
* **同步那份是异步版的机械变换结果**：document-parser 用 pymongo，把
  ``async def`` → ``def``、``async with`` → ``with``、``async for`` → ``for``、
  去掉 ``await``，并把两个游标类换成同步版本。

``to_sync()`` 是**唯一**的变换实现，``deploy/tests/test_pg_compat_parity.py``
直接 import 它做守卫，避免变换规则出现第二份来源。

用法::

    python scripts/pg/sync_pg_compat.py          # 同步
    python scripts/pg/sync_pg_compat.py --check  # 只检查是否漂移（CI 用）
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "services" / "admin-api" / "app" / "core" / "pg_compat.py"
ASYNC_TARGET = REPO_ROOT / "services" / "chat-api" / "app" / "core" / "pg_compat.py"
SYNC_TARGET = REPO_ROOT / "services" / "document-parser" / "app" / "core" / "pg_compat.py"

#: 同步 find 游标（替换异步版的 PgCursor）
SYNC_CURSOR_BLOCK = '''class PgCursor:
    """``find()`` 的返回物；支持 ``for doc in cursor`` 与 ``to_list()``。"""

    def __init__(self, collection: "PgCollection", filt: Mapping[str, Any] | None) -> None:
        self._collection = collection
        self._filter = filt or {}
        self._sort: list[tuple[str, int]] = []
        self._limit = 0
        self._skip = 0
        self.projection: Mapping[str, Any] | None = None

    def sort(self, key: Any, direction: int | None = None) -> "PgCursor":
        if isinstance(key, str):
            self._sort.append((key, 1 if direction is None else int(direction)))
        else:
            for field, order in key:
                self._sort.append((str(field), int(order)))
        return self

    def limit(self, count: int) -> "PgCursor":
        self._limit = int(count)
        return self

    def skip(self, count: int) -> "PgCursor":
        self._skip = int(count)
        return self

    def __iter__(self) -> Iterator[dict[str, Any]]:
        yield from self._collection._run_find(self)

    def __len__(self) -> int:
        return len(self._collection._run_find(self))

    def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        docs = self._collection._run_find(self)
        if length is not None and length >= 0:
            return docs[:length]
        return docs


'''

#: 同步聚合游标（替换异步版的 PgAggregationCursor）
SYNC_AGGREGATION_CURSOR_BLOCK = '''class PgAggregationCursor:
    """``aggregate()`` 的返回物；``to_list()`` 与 ``for`` 迭代均可用。

    pymongo 的 ``aggregate()`` 是**同步**方法（返回游标）；这里保持同样的形状。
    管道在首次取数时才执行，因此构造游标不会产生查询。
    """

    def __init__(self, collection: "PgCollection", pipeline: Any) -> None:
        self._collection = collection
        self._pipeline = pipeline
        self._docs: list[dict[str, Any]] | None = None

    def _load(self) -> list[dict[str, Any]]:
        if self._docs is None:
            self._docs = self._collection._run_aggregate(self._pipeline)
        return self._docs

    def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        docs = self._load()
        if length is not None and length >= 0:
            return docs[:length]
        return docs

    def __iter__(self) -> Iterator[dict[str, Any]]:
        yield from self._load()


'''


def to_sync(async_source: str) -> str:
    """把异步兼容层机械变换成同步版。"""
    text = async_source.replace(
        "from typing import Any, AsyncIterator, Iterable, Mapping, Sequence",
        "from typing import Any, Iterable, Iterator, Mapping, Sequence",
    )
    text = text.replace("async with ", "with ")
    text = text.replace("async for ", "for ")
    text = text.replace("async def ", "def ")
    text = re.sub(r"\bawait\s+", "", text)
    # 两个游标类需要手工替换（异步迭代 / 等待 → 同步迭代）
    text = text.replace(
        text[text.index("class PgCursor:"):text.index("class PgAggregationCursor:")],
        SYNC_CURSOR_BLOCK,
    )
    text = text.replace(
        text[text.index("class PgAggregationCursor:"):text.index("# ── 集合 ─")],
        SYNC_AGGREGATION_CURSOR_BLOCK,
    )
    return text.replace("**R1 已实现**", "**R1 已实现（同步 pymongo 子集）**")


def main() -> int:
    parser = argparse.ArgumentParser(description="同步三份兼容层副本")
    parser.add_argument("--check", action="store_true", help="只检查是否漂移，不写文件")
    args = parser.parse_args()

    source = SOURCE.read_text(encoding="utf-8")
    expected_sync = to_sync(source)

    targets = {"chat-api（异步副本）": (ASYNC_TARGET, source),
               "document-parser（同步变换）": (SYNC_TARGET, expected_sync)}
    drifted = []
    for label, (path, content) in targets.items():
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if current == content:
            print(f"  ✅ {label} 一致")
            continue
        drifted.append(label)
        if args.check:
            print(f"  ❌ {label} 已漂移：{path.relative_to(REPO_ROOT)}")
        else:
            path.write_text(content, encoding="utf-8")
            print(f"  ✏️  {label} 已更新：{path.relative_to(REPO_ROOT)}")

    if args.check and drifted:
        print("\n检测到漂移。运行 python scripts/pg/sync_pg_compat.py 修复。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
