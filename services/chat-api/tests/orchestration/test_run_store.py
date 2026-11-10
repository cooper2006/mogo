"""run_store 契约测试（050 T021）：checkpoint 完整性 / 定义版本锁定 / 状态机迁移 / 租约。

使用内存假集合（与 ``test_orchestration_canvas_api._Database`` 同模式），
验证 ``RunStore`` 不依赖真 Mongo 即可测试，且 027 双后端共享同一代码路径。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.orchestration.run_store import (
    RUN_AWAITING,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_NEEDS_REVIEW,
    RUN_RUNNING,
    RUN_TIMEOUT,
    RunStore,
    RunStoreError,
    utcnow,
)
from tests.orchestration.fixtures.memory_db import FakeDatabase as _Database


def _document(orchestration_id: str = "demo") -> dict:
    return {
        "orchestration": {"id": orchestration_id, "version": "2", "mode": "graph"},
        "nodes": [{"id": "a"}, {"id": "approve", "type": "human_approval", "approver": "u-approver", "depends_on": ["a"]}, {"id": "b", "depends_on": ["approve"]}],
        "edges": [{"source": "a", "target": "approve"}, {"source": "approve", "target": "b"}],
    }


def test_create_run_locks_definition_version() -> None:
    async def scenario() -> None:
        store = RunStore(_Database())
        run = await store.create_run(document=_document(), tenant_id="t1", user_id="u1")
        assert run["status"] == RUN_RUNNING
        assert run["definition_version"] == "2"
        assert run["definition_document"]["orchestration"]["id"] == "demo"
        assert run["pending_approvals"] == {}
        assert run["revision"] == 0

    asyncio.run(scenario())


def test_checkpoint_increments_revision_and_persists() -> None:
    async def scenario() -> None:
        store = RunStore(_Database())
        run = await store.create_run(document=_document(), tenant_id="t1", user_id="u1")
        revision = await store.checkpoint(
            run["run_id"], node_id="a",
            outcome={"node_id": "a", "state": "completed", "output": {"v": 1}},
            context={"a": {"v": 1}},
        )
        assert revision == 1
        loaded = await store.get_run(run["run_id"])
        assert loaded["outcomes"]["a"]["state"] == "completed"
        assert loaded["context"]["a"]["v"] == 1
        assert loaded["revision"] == 1

    asyncio.run(scenario())


def test_checkpoint_optimistic_conflict_raises() -> None:
    async def scenario() -> None:
        store = RunStore(_Database())
        run = await store.create_run(document=_document(), tenant_id="t1", user_id="u1")
        with pytest.raises(RunStoreError):
            await store.checkpoint(
                run["run_id"], node_id="a",
                outcome={"node_id": "a", "state": "completed"},
                context={}, expected_revision=999,
            )

    asyncio.run(scenario())


def test_suspend_and_claim_pending_one_time() -> None:
    async def scenario() -> None:
        store = RunStore(_Database())
        run = await store.create_run(document=_document(), tenant_id="t1", user_id="u1")
        todo = {"approver": "u-a", "deadline": (utcnow() + timedelta(hours=1)).isoformat(), "resume_token": "tok"}
        await store.suspend(run["run_id"], node_id="approve", todo=todo)
        loaded = await store.get_run(run["run_id"])
        assert loaded["status"] == RUN_AWAITING
        assert loaded["pending_approvals"]["approve"]["approver"] == "u-a"

        claimed = await store.claim_pending(run["run_id"], "approve")
        assert claimed["resume_token"] == "tok"
        with pytest.raises(RunStoreError):
            await store.claim_pending(run["run_id"], "approve")

    asyncio.run(scenario())


def test_lease_resume_and_release() -> None:
    async def scenario() -> None:
        store = RunStore(_Database())
        run = await store.create_run(document=_document(), tenant_id="t1", user_id="u1")
        await store.suspend(run["run_id"], node_id="approve", todo={"approver": "u-a", "deadline": "2099-01-01T00:00:00+00:00", "resume_token": "t"})
        resumed = await store.resume(run["run_id"], worker_id="w1")
        assert resumed["status"] == RUN_RUNNING
        assert resumed["lease_owner"] == "w1"
        # 租约被占用 → 第二个 worker 拿不到。
        with pytest.raises(RunStoreError):
            await store.resume(run["run_id"], worker_id="w2")
        await store.release_lease(run["run_id"], worker_id="w1", status=RUN_AWAITING)
        again = await store.resume(run["run_id"], worker_id="w2")
        assert again["lease_owner"] == "w2"

    asyncio.run(scenario())


def test_scan_timeouts_flags_and_blocks() -> None:
    async def scenario() -> None:
        store = RunStore(_Database())
        run = await store.create_run(document=_document(), tenant_id="t1", user_id="u1")
        await store.suspend(run["run_id"], node_id="approve", todo={"approver": "u-a", "deadline": (utcnow() - timedelta(minutes=1)).isoformat(), "resume_token": "t"})
        expired = await store.scan_timeouts()
        assert len(expired) == 1
        assert expired[0]["node_id"] == "approve"
        loaded = await store.get_run(run["run_id"])
        assert loaded["status"] == RUN_TIMEOUT
        assert loaded["outcomes"]["approve"]["state"] == "failed"

    asyncio.run(scenario())


def test_scan_interrupted_marks_needs_review() -> None:
    async def scenario() -> None:
        store = RunStore(_Database())
        run = await store.create_run(document=_document(), tenant_id="t1", user_id="u1")
        now = utcnow()
        await store._col.update_one(
            {"run_id": run["run_id"]},
            {"$set": {"status": RUN_RUNNING, "lease_owner": "w-dead", "lease_until": now - timedelta(minutes=5)}},
        )
        flagged = await store.scan_interrupted()
        assert len(flagged) == 1
        loaded = await store.get_run(run["run_id"])
        assert loaded["status"] == RUN_NEEDS_REVIEW

    asyncio.run(scenario())


def test_cleanup_terminal_respects_retention() -> None:
    async def scenario() -> None:
        store = RunStore(_Database())
        run = await store.create_run(document=_document(), tenant_id="t1", user_id="u1")
        old = utcnow() - timedelta(days=400)
        await store._col.update_one(
            {"run_id": run["run_id"]},
            {"$set": {"status": RUN_COMPLETED, "updated_at": old}},
        )
        deleted = await store.cleanup_terminal(retention_days=180)
        assert deleted == 1
        assert await store.get_run(run["run_id"]) is None

    asyncio.run(scenario())


def test_reassign_and_cancel() -> None:
    async def scenario() -> None:
        store = RunStore(_Database())
        run = await store.create_run(document=_document(), tenant_id="t1", user_id="u1")
        await store.suspend(run["run_id"], node_id="approve", todo={"approver": "u-a", "deadline": "2099-01-01T00:00:00+00:00", "resume_token": "t"})
        await store.reassign(run["run_id"], node_id="approve", new_approver="u-b", actor_id="u1")
        loaded = await store.get_run(run["run_id"])
        assert loaded["pending_approvals"]["approve"]["approver"] == "u-b"
        todos = await store.list_todos(tenant_id="t1", approver="u-b")
        assert len(todos) == 1
        await store.cancel(run["run_id"], actor_id="u1", reason="changed my mind")
        assert (await store.get_run(run["run_id"]))["status"] == "cancelled"

    asyncio.run(scenario())