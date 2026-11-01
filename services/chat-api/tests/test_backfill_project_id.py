"""T019 (SC-004): 回填幂等性测试——构造 3 类会话，连跑两次断言第二次写入 0 条。

3 类会话：
1. 有绑定（agent_kernel_bindings 有 source_workspace_id）→ project_id = source_workspace_id
2. 无绑定 → project_id = "default"
3. 已回填（project_id 已存在且相同）→ 第二次跑时 skipped（written=0）
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from typing import Any
from unittest.mock import patch

import pytest


class _Cursor:
    def __init__(self, documents: list[dict]) -> None:
        self._documents = documents

    def sort(self, _field: str, _direction: int):
        return self

    def __aiter__(self):
        self._iterator = iter(self._documents)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _UpdateResult:
    def __init__(self, matched: int, modified: int) -> None:
        self.matched_count = matched
        self.modified_count = modified


class _FakeCollection:
    """Simulate a MongoDB collection with update_one tracking."""

    def __init__(self, documents: list[dict] | None = None) -> None:
        self.documents: list[dict] = list(documents or [])
        self.update_calls: list[tuple[dict, dict]] = []

    async def update_one(self, scope: dict, update: dict) -> _UpdateResult:
        self.update_calls.append((scope, update))
        matched = 0
        modified = 0
        for doc in self.documents:
            if all(doc.get(k) == v for k, v in scope.items()):
                matched += 1
                set_fields = update.get("$set", {})
                changed = False
                for key, value in set_fields.items():
                    if doc.get(key) != value:
                        doc[key] = value
                        changed = True
                if changed:
                    modified += 1
                break
        return _UpdateResult(matched, modified)

    def find(self, query: dict | None = None) -> _Cursor:
        docs = list(self.documents)
        if query:
            for key, condition in query.items():
                if isinstance(condition, dict) and "$gt" in condition:
                    docs = [d for d in docs if d.get(key, "") > condition["$gt"]]
        return _Cursor(docs)


class _FakeDb:
    def __init__(self, bindings: list[dict], sessions: list[dict]) -> None:
        self.agent_kernel_bindings = _FakeCollection(bindings)
        self.chat_sessions = _FakeCollection(sessions)


def _import_migration():
    """Import the migration script as a module."""
    import importlib.util
    from pathlib import Path

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "migrate_046_project_dimension.py"
    spec = importlib.util.spec_from_file_location("migrate_046", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["migrate_046"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(coro):
    return asyncio.run(coro)


def test_backfill_writes_project_id_for_bound_sessions() -> None:
    """有绑定的会话：project_id = source_workspace_id。"""
    migration = _import_migration()

    bindings = [
        {"_id": "b1", "kernel_session_id": "s1", "source_workspace_id": "proj-alpha"},
        {"_id": "b2", "kernel_session_id": "s2", "source_workspace_id": "proj-beta"},
    ]
    sessions = [
        {"_id": "sess1", "session_id": "s1", "project_id": None},
        {"_id": "sess2", "session_id": "s2", "project_id": None},
    ]
    db = _FakeDb(bindings, sessions)

    with patch.object(migration, "_get_db", return_value=db):
        result = _run(migration.backfill(dry_run=False, batch_size=500, resume_from=None))

    assert result["written"] == 2
    assert result["failed"] == 0
    assert sessions[0]["project_id"] == "proj-alpha"
    assert sessions[1]["project_id"] == "proj-beta"


def test_backfill_unbound_sessions_get_default() -> None:
    """无绑定的会话：project_id = "default"。"""
    migration = _import_migration()

    # 无绑定的会话不在 agent_kernel_bindings 中，backfill 只遍历 bindings
    # 所以无绑定的会话不会被 backfill 处理——它们在 --add-session-field 阶段落 default
    # 这里验证的是：backfill 只处理有绑定的，没有 source_workspace_id 的落 default
    bindings = [
        {"_id": "b1", "kernel_session_id": "s1", "source_workspace_id": None},
    ]
    sessions = [
        {"_id": "sess1", "session_id": "s1", "project_id": None},
    ]
    db = _FakeDb(bindings, sessions)

    with patch.object(migration, "_get_db", return_value=db):
        result = _run(migration.backfill(dry_run=False, batch_size=500, resume_from=None))

    assert result["written"] == 1
    assert sessions[0]["project_id"] == "default"


def test_backfill_is_idempotent_second_run_writes_zero() -> None:
    """SC-004：连跑两次，第二次写入 0 条（全部 skipped）。"""
    migration = _import_migration()

    bindings = [
        {"_id": "b1", "kernel_session_id": "s1", "source_workspace_id": "proj-alpha"},
        {"_id": "b2", "kernel_session_id": "s2", "source_workspace_id": "proj-beta"},
        {"_id": "b3", "kernel_session_id": "s3", "source_workspace_id": None},  # 无 workspace
    ]
    sessions = [
        {"_id": "sess1", "session_id": "s1", "project_id": None},
        {"_id": "sess2", "session_id": "s2", "project_id": None},
        {"_id": "sess3", "session_id": "s3", "project_id": None},
    ]
    db = _FakeDb(bindings, sessions)

    with patch.object(migration, "_get_db", return_value=db):
        # 第一次跑
        result1 = _run(migration.backfill(dry_run=False, batch_size=500, resume_from=None))
        assert result1["written"] == 3
        assert result1["failed"] == 0

        # 验证值
        assert sessions[0]["project_id"] == "proj-alpha"
        assert sessions[1]["project_id"] == "proj-beta"
        assert sessions[2]["project_id"] == "default"

        # 重置 update 计数
        db.chat_sessions.update_calls.clear()

        # 第二次跑（幂等）
        result2 = _run(migration.backfill(dry_run=False, batch_size=500, resume_from=None))
        assert result2["written"] == 0, f"second run should write 0, got {result2['written']}"
        assert result2["skipped"] == 3
        assert result2["failed"] == 0


def test_backfill_handles_archived_project_binding() -> None:
    """已归档项目的绑定：project_id 仍然回填（归档不影响历史归属）。"""
    migration = _import_migration()

    bindings = [
        {"_id": "b1", "kernel_session_id": "s1", "source_workspace_id": "proj-archived"},
    ]
    sessions = [
        {"_id": "sess1", "session_id": "s1", "project_id": None},
    ]
    db = _FakeDb(bindings, sessions)

    with patch.object(migration, "_get_db", return_value=db):
        result = _run(migration.backfill(dry_run=False, batch_size=500, resume_from=None))

    assert result["written"] == 1
    assert sessions[0]["project_id"] == "proj-archived"


def test_backfill_missing_session_records_failure() -> None:
    """binding 指向的 session 不存在：记为 failure 但不中断。"""
    migration = _import_migration()

    bindings = [
        {"_id": "b1", "kernel_session_id": "s-missing", "source_workspace_id": "proj-x"},
        {"_id": "b2", "kernel_session_id": "s2", "source_workspace_id": "proj-y"},
    ]
    sessions = [
        {"_id": "sess2", "session_id": "s2", "project_id": None},
    ]
    db = _FakeDb(bindings, sessions)

    with patch.object(migration, "_get_db", return_value=db):
        result = _run(migration.backfill(dry_run=False, batch_size=500, resume_from=None))

    assert result["written"] == 1  # s2 成功
    assert result["failed"] == 1  # s-missing 失败
    assert len(result["failures"]) == 1
    assert result["failures"][0]["session_id"] == "s-missing"
