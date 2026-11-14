"""Human approval node + pausable run driver (050 FR-001..FR-008).

``human_approval`` is a **node type**, not a document mode: ``VALID_MODES`` is
untouched and any ``graph``-mode orchestration may embed approval nodes. A node
declares ``type: human_approval`` with payload ``approver`` (required),
``timeout`` (seconds, default 24h, clamped 60..30d), ``on_reject`` (optional
direct-dependent branch node) and ``prompt``.

Ticket design (T003): ``ApprovalRuntime`` keeps tickets in an in-process dict,
which cannot back a suspension that outlives the process. Two stages instead:
the **durable todo** lives in ``orchestration_runs.pending_approvals`` (one-time
consumption via an atomic ``$unset`` claim) and a **fresh short-TTL ticket** is
issued + consumed through ``ApprovalRuntime`` at decision time, preserving the
001 one-time / approve-consume-split semantics without changing that module.

Rejection routing: the approval node is recorded ``skipped`` (so dependents
become ready), the ``on_reject`` branch runs, and every other direct dependent
gets an injected ``decision != "rejected"`` guard — the normal path stops while
the branch continues. The loader guarantees the branch is a direct dependent.

The engine subclass below duplicates the ``run_graph`` scheduling loop on
purpose: 050 FR-009 requires the existing six modes' code path to stay
bit-for-bit identical, so pausing/checkpointing lives in ``PausableDagEngine``
and ``engine.py`` only gains the ``AWAITING`` enum member.
"""

from __future__ import annotations

import asyncio
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from .conditions import ConditionError, evaluate_condition
from .engine import DEFAULT_MAX_CONCURRENCY, DagEngine, ExecutionResult, NodeOutcome, NodeRunner, NodeState
from .graph import Graph, Node
from .loader import OrchestrationLoadError, load_orchestration_document
from .run_store import (
    RUN_AWAITING,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_REJECTED,
    RunStore,
    RunStoreError,
    utcnow,
)
from .topo import topological_order

NODE_TYPE_HUMAN_APPROVAL = "human_approval"
DEFAULT_TIMEOUT_SECONDS = 24 * 3600  # OQ-1：默认 24h
MIN_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 30 * 24 * 3600
TICKET_TTL_SECONDS = 300  # 决策时即时发票据，沿用 001 的 5min 口径


class ApprovalError(RuntimeError):
    """Fail-closed approval failure (self-approval, bad actor, consumed todo)."""


class RunSuspended(Exception):
    """Raised by the approval runner to pause its node (not a failure)."""

    def __init__(self, node_id: str) -> None:
        super().__init__(f"node {node_id} awaiting approval")
        self.node_id = node_id


def is_approval_node(node: Node) -> bool:
    return str((node.payload or {}).get("type") or "") == NODE_TYPE_HUMAN_APPROVAL


def approval_node_ids(graph: Graph) -> list[str]:
    return [node_id for node_id, node in graph.nodes.items() if is_approval_node(node)]


def clamp_timeout(value: Any) -> int:
    if value is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        seconds = int(value)
    except (TypeError, ValueError) as error:
        raise OrchestrationLoadError(f"human_approval timeout 必须是秒数：{value!r}") from error
    return max(MIN_TIMEOUT_SECONDS, min(MAX_TIMEOUT_SECONDS, seconds))


@dataclass
class ApprovalNodeConfig:
    node_id: str
    approver: str
    timeout_seconds: int
    on_reject: str | None
    prompt: str

    @classmethod
    def from_node(cls, node: Node) -> "ApprovalNodeConfig":
        payload = node.payload or {}
        approver = str(payload.get("approver") or "").strip()
        if not approver:
            raise OrchestrationLoadError(f"node {node.id}: human_approval requires an approver")
        return cls(
            node_id=node.id,
            approver=approver,
            timeout_seconds=clamp_timeout(payload.get("timeout")),
            on_reject=str(payload.get("on_reject") or "").strip() or None,
            prompt=str(payload.get("prompt") or ""),
        )


def make_approval_runner(
    base_runner: NodeRunner,
    *,
    store: RunStore,
    run_id: str,
    approver_validator: Callable[[str], Awaitable[bool]] | None = None,
) -> NodeRunner:
    """Wrap a runner: approval nodes persist a todo and suspend; others pass through."""

    async def wrapped(node: Node, ctx: dict[str, Any]) -> Any:
        if not is_approval_node(node):
            return await base_runner(node, ctx)
        config = ApprovalNodeConfig.from_node(node)
        if approver_validator is not None and not await approver_validator(config.approver):
            # 无效审批人不静默超时放行：节点失败 → 运行 needs_review 由管理员改派。
            raise ApprovalError(f"审批人不存在或已停用：{config.approver}")
        now = utcnow()
        todo = {
            "approver": config.approver,
            "prompt": config.prompt,
            "on_reject": config.on_reject,
            "created_at": now.isoformat(),
            "deadline": (now + timedelta(seconds=config.timeout_seconds)).isoformat(),
            "resume_token": uuid.uuid4().hex,
        }
        # Persist first: a failed snapshot write fails the node (never an
        # unpersisted in-memory suspension the restart would drop).
        await store.suspend(run_id, node_id=node.id, todo=todo)
        await store.append_event(
            run_id,
            {"event": "approval.suspended", "node": node.id, "approver": config.approver, "at": now.isoformat()},
        )

        # 056 R-7：签发侧旁路镜像（deadline 直接用已计算的 aware datetime）。
        # wrapped 作用域里没有 run 文档，身份/租户只从 ctx 尽力解析；
        # 影子票据不参与判权，缺失不影响旧状态机。
        from app.common.approval_mirror import mirror_issue

        await mirror_issue(
            source="sop", source_id=f"{run_id}:{node.id}",
            tenant_id=str(ctx.get("tenant_id") or ""),
            actor_id=str(ctx.get("initiator_id") or ctx.get("user_id") or ""),
            approver_id=config.approver,
            deadline=now + timedelta(seconds=config.timeout_seconds),
            run_id=run_id, node_id=node.id,
        )
        raise RunSuspended(node.id)

    return wrapped


class PausableDagEngine(DagEngine):
    """``run_graph`` plus seed outcomes, per-node checkpoints and suspension.

    Only used by the 050 run driver; the base engine and the six existing modes
    are untouched (FR-009). Suspended nodes release their coroutine immediately
    — the durable todo in ``orchestration_runs`` is the wait state.
    """

    async def run_pausable(
        self,
        graph: Graph,
        runner: NodeRunner,
        *,
        context: dict[str, Any] | None = None,
        seed_outcomes: dict[str, dict[str, Any]] | None = None,
        checkpoint_cb: Callable[[str, NodeOutcome, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> ExecutionResult:
        order = topological_order(graph)
        result = ExecutionResult(context=dict(context or {}))
        seeded = seed_outcomes or {}
        for node_id, raw in seeded.items():
            if raw.get("state") in (NodeState.COMPLETED.value, NodeState.SKIPPED.value):
                result.outcomes[node_id] = NodeOutcome(
                    node_id=node_id,
                    state=str(raw.get("state")),
                    output=raw.get("output"),
                    error=str(raw.get("error") or ""),
                    attempts=int(raw.get("attempts") or 0),
                    reason=str(raw.get("reason") or ""),
                )
        pending = {node_id for node_id in order if node_id not in result.outcomes}
        blocked: set[str] = {
            node_id for node_id, raw in seeded.items()
            if raw.get("state") in (NodeState.FAILED.value, NodeState.BLOCKED.value)
        }
        running: dict[str, asyncio.Task] = {}
        semaphore = asyncio.Semaphore(self.max_concurrency)

        def ready(node_id: str) -> bool:
            return all(
                dep in result.outcomes
                and result.outcomes[dep].state in (NodeState.COMPLETED.value, NodeState.SKIPPED.value)
                for dep in graph.dependencies(node_id)
            )

        async def execute(node: Node) -> NodeOutcome:
            async with semaphore:
                if node.condition is not None:
                    try:
                        should_run = evaluate_condition(node.condition, result.context)
                    except ConditionError as error:
                        result.events.append({"node": node.id, "event": "skipped", "reason": f"条件求值失败：{error}"})
                        return NodeOutcome(node_id=node.id, state=NodeState.SKIPPED.value, reason=f"条件求值失败：{error}")
                    if not should_run:
                        result.events.append({"node": node.id, "event": "skipped", "reason": "条件为假"})
                        return NodeOutcome(node_id=node.id, state=NodeState.SKIPPED.value, reason="条件为假")
                result.events.append({"node": node.id, "event": "started"})
                try:
                    output = await runner(node, result.context)
                except RunSuspended:
                    result.events.append({"node": node.id, "event": "awaiting_approval"})
                    return NodeOutcome(node_id=node.id, state=NodeState.AWAITING.value)
                except Exception as error:  # noqa: BLE001 - surfaced as a failed node
                    result.events.append({"node": node.id, "event": "failed", "reason": str(error)})
                    return NodeOutcome(node_id=node.id, state=NodeState.FAILED.value, error=str(error), attempts=1)
                result.events.append({"node": node.id, "event": "completed"})
                result.context[node.id] = output
                return NodeOutcome(node_id=node.id, state=NodeState.COMPLETED.value, output=output, attempts=1)

        async def record(node_id: str, outcome: NodeOutcome) -> None:
            result.outcomes[node_id] = outcome
            if checkpoint_cb is not None and outcome.state != NodeState.AWAITING.value:
                # 快照写失败 → 异常上抛 → 运行 failed（fail-closed，不静默续跑）。
                await checkpoint_cb(node_id, outcome, result.context)

        while pending or running:
            newly_blocked = {
                node_id for node_id in pending
                if any(dep in blocked for dep in graph.dependencies(node_id))
            }
            for node_id in newly_blocked:
                pending.discard(node_id)
                blocked.add(node_id)
                blocked.update(graph.downstream_closure(node_id))
                await record(node_id, NodeOutcome(node_id=node_id, state=NodeState.BLOCKED.value, reason="上游失败阻塞"))
                result.events.append({"node": node_id, "event": "blocked"})

            launchable = [
                node_id for node_id in order
                if node_id in pending and ready(node_id) and node_id not in running
            ]
            for node_id in launchable:
                if len(running) >= self.max_concurrency:
                    break
                pending.discard(node_id)
                running[node_id] = asyncio.create_task(execute(graph.nodes[node_id]))

            if not running:
                # 存在挂起节点：其下游未就绪，保持 pending 而非误标 blocked，运行将
                # 以 awaiting_approval 收束，由决策后恢复。
                if any(item.state == NodeState.AWAITING.value for item in result.outcomes.values()):
                    break
                for node_id in list(pending):
                    pending.discard(node_id)
                    blocked.add(node_id)
                    await record(node_id, NodeOutcome(node_id=node_id, state=NodeState.BLOCKED.value, reason="上游不可达"))
                    result.events.append({"node": node_id, "event": "blocked"})
                break

            done, _ = await asyncio.wait(running.values(), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                node_id = next(nid for nid, t in running.items() if t is task)
                running.pop(node_id)
                await record(node_id, task.result())

        return result


@dataclass
class DecisionOutcome:
    run_id: str
    node_id: str
    decision: str
    run_status: str


class RunDriver:
    """Drives persisted runs: start, decide, resume, recover (050 US1/US2/US3)."""

    def __init__(
        self,
        store: RunStore,
        *,
        approval_runtime: Any,
        worker_id: str | None = None,
        approver_validator: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self.store = store
        self.approval_runtime = approval_runtime
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.approver_validator = approver_validator

    # ------------------------------------------------------------------- start

    async def start(
        self,
        *,
        document: dict[str, Any],
        tenant_id: str,
        user_id: str,
        runner: NodeRunner,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        loaded = load_orchestration_document(document)
        if loaded.mode != "graph":
            raise OrchestrationLoadError(
                f"050 首期仅 graph 模式支持 human_approval 节点（当前 {loaded.mode!r}，fail-closed）"
            )
        graph = loaded.definition.to_graph()
        for node_id in approval_node_ids(graph):
            config = ApprovalNodeConfig.from_node(graph.nodes[node_id])
            if self.approver_validator is not None and not await self.approver_validator(config.approver):
                raise OrchestrationLoadError(f"审批人不存在：{config.approver}（fail-closed）")
        run = await self.store.create_run(
            document=document, tenant_id=tenant_id, user_id=user_id, context=context
        )
        return await self._execute(run, runner)

    # ------------------------------------------------------------------ decide

    async def decide(
        self,
        run_id: str,
        *,
        node_id: str,
        actor_id: str,
        decision: str,
        reason: str = "",
        runner: NodeRunner | None = None,
        tenant_id: str | None = None,
    ) -> DecisionOutcome:
        if decision not in ("approve", "reject"):
            raise ApprovalError(f"未知决策：{decision!r}（允许 approve/reject）")
        if decision == "reject" and not str(reason or "").strip():
            raise ApprovalError("驳回必须附理由（进审计与运行记录）")
        run = await self.store.get_run(run_id, tenant_id=tenant_id)
        if run is None:
            raise ApprovalError(f"运行不存在：{run_id}")
        if run.get("status") != RUN_AWAITING:
            raise ApprovalError(f"运行不处于待审批状态：{run.get('status')}")
        todo = (run.get("pending_approvals") or {}).get(node_id)
        if todo is None:
            raise ApprovalError(f"待办不存在或已被消费：{run_id}/{node_id}")
        if actor_id == run.get("initiator_id"):
            raise ApprovalError("发起人不可审批自己发起的运行（审批与消费分离，001 语义）")
        if actor_id != str(todo.get("approver")):
            raise ApprovalError(f"决策人不是该待办的审批人：{actor_id}")
        if self.approver_validator is not None and not await self.approver_validator(actor_id):
            await self.store.set_status(run_id, "needs_review", reason=f"审批人无效：{actor_id}", actor_id=actor_id)
            raise ApprovalError(f"审批人不存在或已停用，运行转 needs_review 待改派：{actor_id}")
        deadline = todo.get("deadline")
        if isinstance(deadline, str):
            try:
                if datetime.fromisoformat(deadline) < utcnow():
                    raise ApprovalError("审批已超时（fail-closed，等待恢复扫描判定）")
            except ValueError:
                pass

        # 两段式：先原子消费持久化待办（重启后依然一次性），再经 ApprovalRuntime
        # 即时签发并消费短 TTL 票据（001 的一次性/分离语义不变）。
        await self.store.claim_pending(run_id, node_id)
        action_id = f"{run_id}:{node_id}:{uuid.uuid4().hex[:8]}"
        await self.approval_runtime.issue(
            action_id=action_id,
            resume_token=str(todo.get("resume_token") or ""),
            actor_id=actor_id,
            reason_code="orchestration.human_approval",
            human_prompt=str(todo.get("prompt") or ""),
            expires_at=utcnow() + timedelta(seconds=TICKET_TTL_SECONDS),
        )
        if decision == "approve":
            consumed = await self.approval_runtime.validate_and_consume(
                action_id=action_id, resume_token=str(todo.get("resume_token") or ""), actor_id=actor_id
            )
            if not consumed:
                raise ApprovalError("票据消费失败（fail-closed）")
        else:
            await self.approval_runtime.deny(action_id=action_id, actor_id=actor_id)

        at = utcnow().isoformat()
        record = {
            "node_id": node_id, "decision": decision, "actor_id": actor_id,
            "reason": reason, "at": at,
        }
        await self.store.record_decision(run_id, record)
        await self.store.append_event(
            run_id, {"event": f"approval.{decision}d" if decision == "approve" else "approval.rejected",
                     "node": node_id, "actor_id": actor_id, "reason": reason, "at": at}
        )
        payload = {"decision": "approved" if decision == "approve" else "rejected", "actor_id": actor_id, "reason": reason, "at": at}

        if decision == "reject" and not todo.get("on_reject"):
            await self.store.checkpoint(
                run_id, node_id=node_id,
                outcome={"node_id": node_id, "state": "failed", "error": f"rejected: {reason}", "output": payload},
                context={**(run.get("context") or {}), node_id: payload},
            )
            await self.store.set_status(run_id, RUN_REJECTED, reason=reason, actor_id=actor_id)
            return DecisionOutcome(run_id, node_id, decision, RUN_REJECTED)

        state = "completed" if decision == "approve" else "skipped"
        outcome = {"node_id": node_id, "state": state, "output": payload}
        if decision == "reject":
            outcome["reason"] = f"rejected → {todo.get('on_reject')}"
        ctx = {**(run.get("context") or {}), node_id: payload}
        await self.store.checkpoint(run_id, node_id=node_id, outcome=outcome, context=ctx)

        refreshed = await self.store.get_run(run_id)
        if refreshed is None:
            raise ApprovalError(f"运行不存在：{run_id}")
        remaining = refreshed.get("pending_approvals") or {}
        if remaining:
            await self.store.set_status(run_id, RUN_AWAITING, reason="其余分支仍在等待审批", actor_id=actor_id)
            return DecisionOutcome(run_id, node_id, decision, RUN_AWAITING)
        if runner is None:
            # 无 runner 注入时只记录决策，续跑由恢复扫描/调用方驱动。
            await self.store.set_status(run_id, RUN_AWAITING, reason="决策已记录，等待续跑", actor_id=actor_id)
            return DecisionOutcome(run_id, node_id, decision, RUN_AWAITING)
        reject_branch = str(todo.get("on_reject") or "") if decision == "reject" else ""
        final = await self.resume(run_id, runner=runner, tenant_id=tenant_id, reject_route=(node_id, reject_branch) if reject_branch else None)
        return DecisionOutcome(run_id, node_id, decision, str(final.get("status")))

    # ------------------------------------------------------------------ resume

    async def resume(
        self,
        run_id: str,
        *,
        runner: NodeRunner,
        tenant_id: str | None = None,
        reject_route: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        run = await self.store.resume(run_id, worker_id=self.worker_id)
        if tenant_id is not None and run.get("tenant_id") != tenant_id:
            await self.store.release_lease(run_id, worker_id=self.worker_id, status=RUN_AWAITING)
            raise ApprovalError(f"运行不属于该租户：{run_id}")
        return await self._execute(run, runner, reject_route=reject_route)

    async def _execute(
        self,
        run: dict[str, Any],
        runner: NodeRunner,
        *,
        reject_route: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        run_id = run["run_id"]
        try:
            loaded = load_orchestration_document(run["definition_document"])
            graph = loaded.definition.to_graph()
            if reject_route is not None:
                graph = _route_rejection(graph, source=reject_route[0], branch=reject_route[1])
            engine = PausableDagEngine(max_concurrency=loaded.max_concurrency or DEFAULT_MAX_CONCURRENCY)
            wrapped = make_approval_runner(
                runner, store=self.store, run_id=run_id, approver_validator=self.approver_validator
            )
            revision = [int(run.get("revision") or 0)]

            async def checkpoint(node_id: str, outcome: NodeOutcome, context: dict[str, Any]) -> None:
                revision[0] = await self.store.checkpoint(
                    run_id,
                    node_id=node_id,
                    outcome={"node_id": outcome.node_id, "state": outcome.state, "output": outcome.output,
                             "error": outcome.error, "attempts": outcome.attempts, "reason": outcome.reason},
                    context=context,
                    expected_revision=revision[0],
                )

            result = await engine.run_pausable(
                graph,
                wrapped,
                context=run.get("context") or {},
                seed_outcomes=run.get("outcomes") or {},
                checkpoint_cb=checkpoint,
            )
        except Exception as error:  # noqa: BLE001 - 快照写失败/定义损坏均 fail-closed
            await self.store.set_status(run_id, RUN_FAILED, reason=str(error), actor_id=self.worker_id)
            final = await self.store.get_run(run_id)
            return final or {**run, "status": RUN_FAILED}

        awaiting = [nid for nid, item in result.outcomes.items() if item.state == NodeState.AWAITING.value]
        if awaiting:
            status = RUN_AWAITING
        elif result.failed_nodes or result.blocked_nodes:
            status = RUN_FAILED
        else:
            status = RUN_COMPLETED
        await self.store.release_lease(run_id, worker_id=self.worker_id, status=status)
        final = await self.store.get_run(run_id)
        return final or {**run, "status": status}

    # ---------------------------------------------------------------- recovery

    async def recovery_sweep(self) -> dict[str, list[str]]:
        """Restart-safe sweep: expire timeouts, block downstream, flag crashed runs."""
        expired = await self.store.scan_timeouts()
        timed_out: list[str] = []
        for item in expired:
            run = await self.store.get_run(item["run_id"])
            if run is None:
                continue
            timed_out.append(item["run_id"])
            try:
                loaded = load_orchestration_document(run["definition_document"])
                graph = loaded.definition.to_graph()
            except Exception:  # noqa: BLE001 - 定义损坏时仍保留 timeout 终态与事件
                continue
            for downstream in sorted(graph.downstream_closure(item["node_id"])):
                existing = (run.get("outcomes") or {}).get(downstream)
                if existing and existing.get("state") in ("completed", "skipped"):
                    continue
                await self.store.checkpoint(
                    item["run_id"], node_id=downstream,
                    outcome={"node_id": downstream, "state": "blocked", "reason": "审批超时阻塞"},
                    context=run.get("context") or {},
                )
        interrupted = await self.store.scan_interrupted()
        return {
            "timed_out": timed_out,
            "needs_review": [doc["run_id"] for doc in interrupted],
        }


def _route_rejection(graph: Graph, *, source: str, branch: str) -> Graph:
    """Copy the graph with ``decision != rejected`` guards on the normal path.

    The approval node itself is seeded ``skipped`` so every direct dependent is
    ready; the ``on_reject`` branch runs while the other direct dependents'
    injected guards evaluate false (context holds the rejection payload).
    """
    guard = {"op": "!=", "left": {"var": f"{source}.decision"}, "right": "rejected"}
    nodes: list[Node] = []
    direct = set(graph.dependents(source))
    for node_id, node in graph.nodes.items():
        condition = node.condition
        if node_id in direct and node_id != branch:
            condition = {"op": "and", "operands": [guard, condition]} if condition is not None else guard
        nodes.append(Node(id=node.id, mode=node.mode, condition=deepcopy(condition),
                          retry=deepcopy(node.retry), payload=deepcopy(node.payload)))
    from .graph import Edge

    return Graph(nodes=nodes, edges=[Edge(source=e.source, target=e.target) for e in graph.edges])