"""human_approval 执行与决策契约测试（050 T020）。

覆盖：挂起生成待办 / 批准续跑 / 驳回分支与默认终止 / 超时判定 / 自审拒绝 /
重复票据拒绝 / 无效审批人 fail-closed。使用内存假 db（fixtures.memory_db）。
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.governance.approval_runtime import ApprovalRuntime
from app.orchestration.human_approval import (
    ApprovalError,
    RunDriver,
    RunSuspended,
    make_approval_runner,
)
from app.orchestration.loader import OrchestrationLoadError, load_orchestration_document
from app.orchestration.run_store import RunStore, utcnow
from tests.orchestration.fixtures.memory_db import FakeDatabase


def _doc(reject: bool = False) -> dict:
    nodes = [
        {"id": "start", "payload": {"skill": "s"}},
        {"id": "approve", "type": "human_approval", "approver": "u-approver", "timeout": 3600, "payload": {"prompt": "请审批"}},
    ]
    edges = [{"source": "start", "target": "approve"}]
    if reject:
        nodes.append({"id": "branch", "depends_on": ["approve"], "payload": {"skill": "b"}})
        nodes.append({"id": "next", "depends_on": ["approve"], "payload": {"skill": "n"}})
        edges.extend([{"source": "approve", "target": "branch"}, {"source": "approve", "target": "next"}])
    else:
        nodes.append({"id": "finish", "depends_on": ["approve"], "payload": {"skill": "f"}})
        edges.append({"source": "approve", "target": "finish"})
    return {
        "orchestration": {"id": "approval-demo", "version": "1", "mode": "graph"},
        "nodes": nodes,
        "edges": edges,
    }


def _doc_on_reject() -> dict:
    # on_reject 必须是审批节点的直接依赖。
    return {
        "orchestration": {"id": "approval-reject", "version": "1", "mode": "graph"},
        "nodes": [
            {"id": "start", "payload": {"skill": "s"}},
            {"id": "approve", "type": "human_approval", "approver": "u-approver", "on_reject": "rework", "payload": {}},
            {"id": "rework", "depends_on": ["approve"], "payload": {"skill": "r"}},
            {"id": "next", "depends_on": ["approve"], "payload": {"skill": "n"}},
        ],
        "edges": [{"source": "start", "target": "approve"}, {"source": "approve", "target": "rework"}, {"source": "approve", "target": "next"}],
    }


async def _always_valid(_user_id: str) -> bool:
    return True


async def _runner(node, context):
    return {"node_id": node.id, "echo": True}


def _driver(db=None):
    return RunDriver(
        RunStore(db or FakeDatabase("orchestration_runs", "end_users")),
        approval_runtime=ApprovalRuntime(),
        approver_validator=_always_valid,
    )


def test_loader_rejects_missing_approver() -> None:
    doc = _doc()
    doc["nodes"][1] = {"id": "approve", "type": "human_approval", "payload": {}}
    with pytest.raises(OrchestrationLoadError):
        load_orchestration_document(doc)


def test_loader_rejects_bad_on_reject_target() -> None:
    doc = _doc_on_reject()
    doc["nodes"][1]["on_reject"] = "ghost"
    with pytest.raises(OrchestrationLoadError):
        load_orchestration_document(doc)


def test_loader_clamps_timeout() -> None:
    doc = _doc()
    doc["nodes"][1]["timeout"] = 10  # 低于 60s 下限 → 钳到 60
    loaded = load_orchestration_document(doc)
    entry = loaded.definition.nodes[1]
    assert entry["payload"]["timeout"] == 60


def test_run_suspends_then_approves_and_completes() -> None:
    async def scenario() -> None:
        db = FakeDatabase("orchestration_runs", "end_users")
        driver = _driver(db)
        run = await driver.start(document=_doc(), tenant_id="t1", user_id="u-initiator", runner=_runner)
        assert run["status"] == "awaiting_approval"
        assert "approve" in run["pending_approvals"]
        todo = run["pending_approvals"]["approve"]
        assert todo["approver"] == "u-approver"
        assert "resume_token" in todo

        outcome = await driver.decide(
            run["run_id"], node_id="approve", actor_id="u-approver",
            decision="approve", runner=_runner, tenant_id="t1",
        )
        assert outcome.decision == "approve"
        assert outcome.run_status == "completed"
        final = await db.orchestration_runs.find_one({"run_id": run["run_id"]})
        assert final["status"] == "completed"
        assert final["outcomes"]["finish"]["state"] == "completed"

    asyncio.run(scenario())


def test_self_approval_rejected() -> None:
    async def scenario() -> None:
        db = FakeDatabase("orchestration_runs", "end_users")
        driver = _driver(db)
        run = await driver.start(document=_doc(), tenant_id="t1", user_id="u-initiator", runner=_runner)
        with pytest.raises(ApprovalError) as exc:
            await driver.decide(
                run["run_id"], node_id="approve", actor_id="u-initiator",
                decision="approve", runner=_runner, tenant_id="t1",
            )
        assert "发起人" in str(exc.value)

    asyncio.run(scenario())


def test_wrong_approver_rejected() -> None:
    async def scenario() -> None:
        db = FakeDatabase("orchestration_runs", "end_users")
        driver = _driver(db)
        run = await driver.start(document=_doc(), tenant_id="t1", user_id="u-initiator", runner=_runner)
        with pytest.raises(ApprovalError):
            await driver.decide(
                run["run_id"], node_id="approve", actor_id="u-other",
                decision="approve", runner=_runner, tenant_id="t1",
            )

    asyncio.run(scenario())


def test_reject_requires_reason() -> None:
    async def scenario() -> None:
        db = FakeDatabase("orchestration_runs", "end_users")
        driver = _driver(db)
        run = await driver.start(document=_doc(), tenant_id="t1", user_id="u-initiator", runner=_runner)
        with pytest.raises(ApprovalError) as exc:
            await driver.decide(
                run["run_id"], node_id="approve", actor_id="u-approver",
                decision="reject", runner=_runner, tenant_id="t1",
            )
        assert "理由" in str(exc.value)

    asyncio.run(scenario())


def test_reject_without_on_reject_terminates() -> None:
    async def scenario() -> None:
        db = FakeDatabase("orchestration_runs", "end_users")
        driver = _driver(db)
        run = await driver.start(document=_doc(), tenant_id="t1", user_id="u-initiator", runner=_runner)
        outcome = await driver.decide(
            run["run_id"], node_id="approve", actor_id="u-approver",
            decision="reject", reason="不同意", runner=_runner, tenant_id="t1",
        )
        assert outcome.run_status == "rejected"
        final = await db.orchestration_runs.find_one({"run_id": run["run_id"]})
        assert final["status"] == "rejected"
        assert final["decision_history"][0]["reason"] == "不同意"

    asyncio.run(scenario())


def test_reject_routes_to_on_reject_branch() -> None:
    async def scenario() -> None:
        db = FakeDatabase("orchestration_runs", "end_users")
        driver = _driver(db)
        run = await driver.start(document=_doc_on_reject(), tenant_id="t1", user_id="u-initiator", runner=_runner)
        outcome = await driver.decide(
            run["run_id"], node_id="approve", actor_id="u-approver",
            decision="reject", reason="返工", runner=_runner, tenant_id="t1",
        )
        assert outcome.run_status == "completed"
        final = await db.orchestration_runs.find_one({"run_id": run["run_id"]})
        # 分支节点执行；正常路径节点被决策守卫跳过。
        assert final["outcomes"]["rework"]["state"] == "completed"
        assert final["outcomes"]["next"]["state"] in ("skipped", "blocked")

    asyncio.run(scenario())


def test_timeout_fail_closed_via_sweep() -> None:
    async def scenario() -> None:
        db = FakeDatabase("orchestration_runs", "end_users")
        driver = _driver(db)
        run = await driver.start(document=_doc(), tenant_id="t1", user_id="u-initiator", runner=_runner)
        await db.orchestration_runs.update_one(
            {"run_id": run["run_id"]},
            {"$set": {f"pending_approvals.approve.deadline": (utcnow() - timedelta(seconds=1)).isoformat()}},
        )
        summary = await driver.recovery_sweep()
        assert run["run_id"] in summary["timed_out"]
        final = await db.orchestration_runs.find_one({"run_id": run["run_id"]})
        assert final["status"] == "timeout"
        assert final["outcomes"]["approve"]["state"] == "failed"
        # 下游按 FR-6 阻塞。
        assert final["outcomes"]["finish"]["state"] == "blocked"

    asyncio.run(scenario())


async def _never_valid(_user_id: str) -> bool:
    return False


def test_invalid_approver_fails_closed_at_decision() -> None:
    async def scenario() -> None:
        db = FakeDatabase("orchestration_runs", "end_users")
        # start 时审批人有效；决策时审批人已停用 → needs_review（不静默放行）。
        driver = RunDriver(RunStore(db), approval_runtime=ApprovalRuntime(), approver_validator=_always_valid)
        run = await driver.start(document=_doc(), tenant_id="t1", user_id="u-initiator", runner=_runner)
        driver2 = RunDriver(RunStore(db), approval_runtime=ApprovalRuntime(), approver_validator=_never_valid)
        with pytest.raises(ApprovalError) as exc:
            await driver2.decide(
                run["run_id"], node_id="approve", actor_id="u-approver",
                decision="approve", runner=_runner, tenant_id="t1",
            )
        assert "needs_review" in str(exc.value)
        final = await db.orchestration_runs.find_one({"run_id": run["run_id"]})
        assert final["status"] == "needs_review"

    asyncio.run(scenario())


def test_approval_runner_suspends_via_exception() -> None:
    async def scenario() -> None:
        db = FakeDatabase("orchestration_runs", "end_users")
        store = RunStore(db)
        run = await store.create_run(document=_doc(), tenant_id="t1", user_id="u1")
        wrapped = make_approval_runner(_runner, store=store, run_id=run["run_id"])
        node = load_orchestration_document(_doc()).definition.to_graph().nodes["approve"]
        with pytest.raises(RunSuspended):
            await wrapped(node, {})
        assert (await store.get_run(run["run_id"]))["status"] == "awaiting_approval"

    asyncio.run(scenario())


def test_second_decision_on_consumed_todo_rejected() -> None:
    async def scenario() -> None:
        db = FakeDatabase("orchestration_runs", "end_users")
        driver = _driver(db)
        run = await driver.start(document=_doc(), tenant_id="t1", user_id="u-initiator", runner=_runner)
        await driver.decide(run["run_id"], node_id="approve", actor_id="u-approver", decision="approve", runner=_runner, tenant_id="t1")
        with pytest.raises(ApprovalError) as exc:
            await driver.decide(run["run_id"], node_id="approve", actor_id="u-approver", decision="approve", runner=_runner, tenant_id="t1")
        assert ("已被消费" in str(exc.value)) or ("不处于待审批" in str(exc.value))


def _doc_two_approvals() -> dict:
    return {
        "orchestration": {"id": "two-approvals", "version": "1", "mode": "graph"},
        "nodes": [
            {"id": "start", "payload": {"skill": "s"}},
            {"id": "a1", "type": "human_approval", "approver": "u-approver", "payload": {}},
            {"id": "a2", "type": "human_approval", "approver": "u-approver", "payload": {}},
            {"id": "finish", "depends_on": ["a2"], "payload": {"skill": "f"}},
        ],
        "edges": [
            {"source": "start", "target": "a1"},
            {"source": "a1", "target": "a2"},
            {"source": "a2", "target": "finish"},
        ],
    }


def test_two_approvals_in_sequence_suspend_approve_suspend_approve_complete() -> None:
    """SC-001：双审批节点串联（挂起→批准→再挂起→批准→完成）。"""
    async def scenario() -> None:
        db = FakeDatabase("orchestration_runs", "end_users")
        driver = _driver(db)
        run = await driver.start(document=_doc_two_approvals(), tenant_id="t1", user_id="u-initiator", runner=_runner)
        assert run["status"] == "awaiting_approval"
        assert "a1" in run["pending_approvals"]

        # 第一节点批准 → 执行到第二节点再次挂起。
        outcome1 = await driver.decide(run["run_id"], node_id="a1", actor_id="u-approver", decision="approve", runner=_runner, tenant_id="t1")
        assert outcome1.run_status == "awaiting_approval"
        after1 = await db.orchestration_runs.find_one({"run_id": run["run_id"]})
        assert "a2" in after1["pending_approvals"]

        # 第二节点批准 → 完成。
        outcome2 = await driver.decide(run["run_id"], node_id="a2", actor_id="u-approver", decision="approve", runner=_runner, tenant_id="t1")
        assert outcome2.run_status == "completed"
        final = await db.orchestration_runs.find_one({"run_id": run["run_id"]})
        assert final["status"] == "completed"
        assert final["outcomes"]["finish"]["state"] == "completed"

    asyncio.run(scenario())

    asyncio.run(scenario())