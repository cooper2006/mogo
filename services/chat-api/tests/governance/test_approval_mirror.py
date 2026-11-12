"""056 R-7 — approval_mirror 影子双写适配器单测（纯内存 fake，不依赖真实 Mongo）。

验证「迁移期旁路双写」的安全契约：
* APPROVAL_KERNEL_ENABLED 关 → 零写入、零副作用（可随时回退旧路径）；
* 开 → issue/decision 镜像到影子票据并写 gate_events，但不参与旧状态机判权；
* 任何底层异常都被吞掉，绝不改变旧路径返回值 / HTTP 契约（fail-open 降级）。
"""

from __future__ import annotations

import importlib
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# 以 chat-api 服务根为导入上下文，使 app.common.approval_mirror / approval_kernel 可解析。
_SERVICE_ROOT = str(Path(__file__).resolve().parents[2])
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

from app.common.approval_mirror import (  # noqa: E402
    approval_kernel_enabled,
    mirror_decision,
    mirror_issue,
)
import app.core.db as _db_mod  # noqa: E402


FIXED_NOW = datetime(2026, 11, 12, 9, 0, 0, tzinfo=timezone.utc)


class _Result:
    def __init__(self, modified_count: int = 0, inserted_id: str = "") -> None:
        self.modified_count = modified_count
        self.inserted_id = inserted_id


class _Cursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def to_list(self, length: int | None = None) -> list[dict]:
        rows = [dict(r) for r in self._rows]
        return rows[:length] if length else rows


def _matches(doc: dict, query: dict) -> bool:
    for key, cond in query.items():
        value = doc.get(key)
        if isinstance(cond, dict):
            if "$in" in cond and value not in cond["$in"]:
                return False
            if "$lt" in cond and not (value is not None and value < cond["$lt"]):
                return False
            if "$ne" in cond and value == cond["$ne"]:
                return False
            if not any(op.startswith("$") for op in cond) and value != cond:
                return False
        elif value != cond:
            return False
    return True


class FakeCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    async def insert_one(self, doc: dict) -> _Result:
        row = dict(doc)
        row.setdefault("_id", uuid.uuid4().hex)
        self.docs[row["_id"]] = row
        return _Result(inserted_id=row["_id"])

    async def find_one(self, query: dict) -> dict | None:
        for row in self.docs.values():
            if _matches(row, query):
                return dict(row)
        return None

    def find(self, query: dict) -> _Cursor:
        return _Cursor([r for r in self.docs.values() if _matches(r, query)])

    async def update_one(self, flt: dict, update: dict) -> _Result:
        for _id, row in self.docs.items():
            if not _matches(row, flt):
                continue
            for k, v in (update.get("$set") or {}).items():
                row[k] = v
            for k, v in (update.get("$inc") or {}).items():
                row[k] = int(row.get(k) or 0) + v
            return _Result(modified_count=1)
        return _Result(modified_count=0)


class FakeDB:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(_db_mod, "get_db", lambda: db)
    return db


def test_flag_default_off_and_toggle():
    # 不带任何环境变量时默认关闭（灰度期旧路径为主）。
    for name in ("APPROVAL_KERNEL_ENABLED", "MOGO_FLAG_APPROVAL_KERNEL_ENABLED"):
        import os

        os.environ.pop(name, None)
    assert approval_kernel_enabled() is False
    import os

    os.environ["APPROVAL_KERNEL_ENABLED"] = "true"
    assert approval_kernel_enabled() is True
    os.environ.pop("APPROVAL_KERNEL_ENABLED", None)


async def test_mirror_issue_then_decision_writes_shadow_ticket(fake_db, monkeypatch):
    monkeypatch.setenv("APPROVAL_KERNEL_ENABLED", "true")
    await mirror_issue(
        source="portal", source_id="req-1", tenant_id="t-1",
        actor_id="u-1", approver_id="admin-1",
        deadline=FIXED_NOW + timedelta(minutes=5),
    )
    tickets = fake_db["approval_tickets"]
    assert len(tickets.docs) == 1
    doc = next(iter(tickets.docs.values()))
    assert doc["shadow"] is True
    assert doc["source"] == "portal" and doc["source_id"] == "req-1"
    assert doc["token_hash"] == ""  # 影子票据不可被 Kernel.decide 消费
    assert doc["state"] == "pending"
    # 审计已落 gate_events
    assert len(fake_db["gate_events"].docs) == 1

    # decision 把影子票据推进终态
    await mirror_decision(
        source="portal", source_id="req-1", tenant_id="t-1",
        actor_id="admin-1", approved=True,
    )
    doc = next(iter(tickets.docs.values()))
    assert doc["state"] == "approved"
    # 再次 decision 应找不到可决策影子票（已终态，幂等无关）→ 不抛异常
    await mirror_decision(
        source="portal", source_id="req-1", tenant_id="t-1",
        actor_id="admin-1", approved=True,
    )


async def test_mirror_is_noop_when_flag_off(fake_db):
    # 开关关闭：不触碰数据库
    await mirror_issue(
        source="tool", source_id="a-1", tenant_id="t-1",
        actor_id="u-1", approver_id="",
    )
    await mirror_decision(
        source="tool", source_id="a-1", tenant_id="t-1",
        actor_id="u-1", approved=True,
    )
    assert len(fake_db["approval_tickets"].docs) == 0
    assert len(fake_db["gate_events"].docs) == 0


async def test_mirror_swallows_db_errors(fake_db, monkeypatch):
    monkeypatch.setenv("APPROVAL_KERNEL_ENABLED", "true")
    # get_db 抛异常也必须被吞掉，绝不冒泡到旧状态机调用方
    monkeypatch.setattr(_db_mod, "get_db", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    # 不应抛异常
    await mirror_issue(
        source="sop", source_id="r:n", tenant_id="t-1",
        actor_id="u-1", approver_id="u-1",
    )
    await mirror_decision(
        source="sop", source_id="r:n", tenant_id="t-1",
        actor_id="u-1", approved=False,
    )
