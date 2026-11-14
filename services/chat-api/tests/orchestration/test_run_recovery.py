"""运行恢复契约测试（050 T022）：重启续跑 / 已完成节点零重跑 / 并发租约 / 崩溃标记。

关键语义：挂起运行不占协程，快照在 DB；恢复 = 重新驱动，已完成节点不重复执行
（runner 调用计数断言）。
"""

from __future__ import annotations

import asyncio

import pytest

from app.governance.approval_runtime import ApprovalRuntime
from app.orchestration.human_approval import RunDriver
from app.orchestration.run_store import RunStore
from tests.orchestration.fixtures.memory_db import FakeDatabase


def _doc() -> dict:
    return {
        "orchestration": {"id": "recovery-demo", "version": "1", "mode": "graph"},
        "nodes": [
            {"id": "start", "payload": {"skill": "s"}},
            {"id": "approve", "type": "human_approval", "approver": "u-approver", "payload": {}},
            {"id": "finish", "depends_on": ["approve"], "payload": {"skill": "f"}},
        ],
        "edges": [
            {"source": "start", "target": "approve"},
            {"source": "approve", "target": "finish"},
        ],
    }


class CountingRunner:
    """计数 runner：断言已完成节点不重复执行。"""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    async def __call__(self, node, context):
        self.calls[node.id] = self.calls.get(node.id, 0) + 1
        return {"node_id": node.id, "calls": self.calls[node.id]}


async def _always_valid(_user_id: str) -> bool:
    return True


def _past():
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) - timedelta(minutes=5)


def test_restart_resume_does_not_repeat_completed_nodes() -> None:
    """模拟重启：丢弃进程态（新 RunDriver + 新 runtime），从快照恢复。"""
    async def scenario() -> None:
        db = FakeDatabase("orchestration_runs", "end_users")
        runner = CountingRunner()
        driver1 = RunDriver(RunStore(db), approval_runtime=ApprovalRuntime(), approver_validator=_always_valid)
        run = await driver1.start(document=_doc(), tenant_id="t1", user_id="u-initiator", runner=runner)
        assert run["status"] == "awaiting_approval"
        assert runner.calls["start"] == 1  # start 已执行一次

        # 重启：新驱动器、新票据运行时（进程态清空），同一 DB。
        driver2 = RunDriver(RunStore(db), approval_runtime=ApprovalRuntime(), approver_validator=_always_valid)
        outcome = await driver2.decide(
            run["run_id"], node_id="approve", actor_id="u-approver",
            decision="approve", runner=runner, tenant_id="t1",
        )
        assert outcome.run_status == "completed"
        assert runner.calls["start"] == 1  # 已完成节点零重跑
        assert runner.calls["finish"] == 1
        final = await db.orchestration_runs.find_one({"run_id": run["run_id"]})
        assert final["status"] == "completed"

    asyncio.run(scenario())


def test_concurrent_resume_lease() -> None:
    async def scenario() -> None:
        db = FakeDatabase("orchestration_runs", "end_users")
        store = RunStore(db)
        driver1 = RunDriver(store, approval_runtime=ApprovalRuntime(), approver_validator=_always_valid)
        run = await driver1.start(document=_doc(), tenant_id="t1", user_id="u-initiator", runner=CountingRunner())
        assert run["status"] == "awaiting_approval"
        # store 层租约：worker1 拿租约后，worker2 抢租约必须失败（单活租约）。
        held = await store.resume(run["run_id"], worker_id="worker-1")
        assert held["lease_owner"] == "worker-1"
        from app.orchestration.run_store import RunStoreError

        with pytest.raises(RunStoreError):
            await store.resume(run["run_id"], worker_id="worker-2")
        # 释放后 worker2 可拿。
        await store.release_lease(run["run_id"], worker_id="worker-1", status="awaiting_approval")
        again = await store.resume(run["run_id"], worker_id="worker-2")
        assert again["lease_owner"] == "worker-2"

    asyncio.run(scenario())


def test_interrupted_running_run_flags_needs_review() -> None:
    """运行中（非挂起）worker 崩溃 → 恢复扫描标记 needs_review，不静默重跑。"""
    async def scenario() -> None:
        db = FakeDatabase("orchestration_runs", "end_users")
        store = RunStore(db)
        run = await store.create_run(document=_doc(), tenant_id="t1", user_id="u-initiator")
        await db.orchestration_runs.update_one(
            {"run_id": run["run_id"]},
            {"$set": {"status": "running", "lease_owner": "w-dead", "lease_until": _past()}},
        )
        driver = RunDriver(store, approval_runtime=ApprovalRuntime())
        summary = await driver.recovery_sweep()
        assert run["run_id"] in summary["needs_review"]
        final = await db.orchestration_runs.find_one({"run_id": run["run_id"]})
        assert final["status"] == "needs_review"

    asyncio.run(scenario())


def test_resolve_review_skip_resumes() -> None:
    async def scenario() -> None:
        db = FakeDatabase("orchestration_runs", "end_users")
        store = RunStore(db)
        run = await store.create_run(document=_doc(), tenant_id="t1", user_id="u-initiator")
        await db.orchestration_runs.update_one(
            {"run_id": run["run_id"]},
            {"$set": {"status": "needs_review", "lease_owner": None, "lease_until": None}},
        )
        await store.resolve_review(run["run_id"], node_id="start", action="skip", actor_id="u-admin")
        driver = RunDriver(store, approval_runtime=ApprovalRuntime(), approver_validator=_always_valid)
        final = await driver.resume(run["run_id"], runner=CountingRunner(), tenant_id="t1")
        assert final["status"] == "awaiting_approval"

    asyncio.run(scenario())