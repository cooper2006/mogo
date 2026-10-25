"""026 T018/T020/T021 — 索引策略助手与访问模式扫描器测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.perf.db_write_scanner import (
    KNOWN_BULK_WRITTEN,
    QUERY_METHODS,
    WRITE_METHODS,
    is_known_bulk_written,
    render_report,
    scan_file,
    scan_tree,
)
from tools.perf.index_advisor import (
    SUGGESTED_INDEXES,
    plan_diffs,
    suggested_index_specs,
)

# 批量预取 / 批量写入 helper（services/common/batch_prefetch.py）
from services.common.batch_prefetch import (
    BULK_UPDATE,
    build_bulk_write,
    chunked,
    index_by,
    prefetch_many,
)


class TestSuggestedIndexes:
    def test_has_critical_collections(self) -> None:
        # FR-8：session/config/permission/token/document collections 应有建议索引
        names = set(SUGGESTED_INDEXES.keys())
        assert {"chat_sessions", "chat_messages", "memories", "permissions", "admin_tokens", "document_jobs"} <= names

    def test_specs_shape(self) -> None:
        specs = suggested_index_specs("chat_sessions")
        assert len(specs) >= 1
        first = specs[0]
        assert "key" in first and "name" in first
        for key, direction in first["key"]:
            assert key
            assert direction in (1, -1)

    def test_plan_diffs_reports_missing(self) -> None:
        diffs = plan_diffs({"chat_sessions": ["_id_"]})
        names = {d["name"] for d in diffs if d["collection"] == "chat_sessions"}
        assert "idx_sessions_tenant_updated" in names

    def test_plan_diffs_no_diffs(self) -> None:
        # 所有建议索引都存在 → 无 diff
        existing = {
            col: [s["name"] for s in specs]
            for col, specs in SUGGESTED_INDEXES.items()
        }
        assert plan_diffs(existing) == []


class TestDbWriteScanner:
    def test_scan_file_detects_n_plus_one(self, tmp_path: Path) -> None:
        f = tmp_path / "mod.py"
        f.write_text(
            "import asyncio\n"
            "async def handle(ids, db):\n"
            "    out = []\n"
            "    for i in ids:\n"
            "        row = await db['coll'].find_one({'id': i})\n"
            "        out.append(row)\n"
            "    return out\n",
            encoding="utf-8",
        )
        cands = scan_file(f)
        nplus = [c for c in cands if c["kind"] == "n_plus_one"]
        assert len(nplus) == 1
        assert nplus[0]["method"] == "find_one"
        assert nplus[0]["loop"] == "for"
        assert "mod.py" in nplus[0]["file"]

    def test_scan_file_detects_loop_write(self, tmp_path: Path) -> None:
        f = tmp_path / "mod.py"
        f.write_text(
            "async def write_all(db, rows):\n"
            "    for r in rows:\n"
            "        await db['c'].update_one({'_id': r['_id']}, {'$set': r})\n",
            encoding="utf-8",
        )
        cands = scan_file(f)
        writes = [c for c in cands if c["kind"] == "loop_write"]
        assert len(writes) == 1
        assert writes[0]["method"] == "update_one"

    def test_scan_file_outside_loop_not_reported(self, tmp_path: Path) -> None:
        f = tmp_path / "mod.py"
        f.write_text(
            "async def single(db):\n"
            "    return await db['c'].find_one({'a': 1})\n",
            encoding="utf-8",
        )
        assert scan_file(f) == []

    def test_scan_tree_skips_tests(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "mod.py").write_text("x = 1\n", encoding="utf-8")
        (pkg / "test_mod.py").write_text("x = 1\n", encoding="utf-8")
        report = scan_tree(pkg)
        assert report == {"n_plus_one": [], "loop_write": []}

    def test_known_bulk_written_filter(self) -> None:
        assert is_known_bulk_written("app/memory/lifecycle.py") is True
        assert is_known_bulk_written("app/other.py") is False
        assert KNOWN_BULK_WRITTEN

    def test_render_report(self) -> None:
        text = render_report(
            Path("services"),
            nplusone=[{"file": "a.py", "line": 10, "method": "find_one", "loop": "for"}],
            loop_write=[{"file": "b.py", "line": 20, "method": "update_one", "loop": "for"}],
        )
        assert "N+1" in text
        assert "`bulk_write`" in text
        assert "a.py" in text and "b.py" in text


class TestMethodRegistry:
    def test_query_methods_noise_filtered(self) -> None:
        # `get` 不属 DB 单点查询，避免 dict.get 噪声
        assert "get" not in QUERY_METHODS
        assert {"find_one", "find", "count_documents"} == QUERY_METHODS

    def test_write_methods(self) -> None:
        assert "bulk_write" not in WRITE_METHODS  # bulk 已是目标，不重复报告
        assert {"insert_one", "update_one", "replace_one", "delete_one"} == WRITE_METHODS


class TestBatchPrefetch:
    """批量预取 / 批量写入 helper（T020/T021 改法落地工具）。"""

    def test_index_by(self) -> None:
        assert index_by([{"_id": "a"}, {"_id": "b"}]) == {"a": {"_id": "a"}, "b": {"_id": "b"}}

    def test_prefetch_many_empty_ids(self) -> None:
        assert prefetch_many([], "_id", []) == {}

    def test_prefetch_many_indexes(self) -> None:
        docs = [{"_id": "a", "v": 1}, {"_id": "b", "v": 2}]
        by_id = prefetch_many(docs, "_id", ["a", "b", "c"])
        assert by_id["a"]["v"] == 1
        assert "c" not in by_id

    def test_build_bulk_write(self) -> None:
        reqs = build_bulk_write(
            [{"op": BULK_UPDATE, "filter": {"_id": "a"}, "update": {"$set": {"v": 1}}}]
        )
        assert reqs[0]["op"] == "update"
        assert reqs[0]["update"] == {"$set": {"v": 1}}

    def test_build_bulk_write_unknown_op(self) -> None:
        with pytest.raises(ValueError):
            build_bulk_write([{"op": "nope"}])

    def test_chunked(self) -> None:
        chunks = list(chunked(list(range(7)), 3))
        assert chunks == [[0, 1, 2], [3, 4, 5], [6]]