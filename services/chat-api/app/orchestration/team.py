"""Team orchestration mode (052 FR-001 / FR-002 / FR-003 / FR-004 / FR-005 / FR-006).

A ``team`` run organizes work as "leader + members": the leader node decomposes a
task into a ``TeamPlan`` (member x subtask assignment), members execute their
subtasks (bounded by ``max_concurrency``, transport-agnostic runner), outputs and
intermediate material land on a run-level **blackboard** (keyed with an author
prefix for namespace isolation, old versions preserved), and the leader then
reviews each member's output with ``accept`` / ``rework`` verdicts. ``rework``
sends the work back to the member with the review opinion; the loop is bounded by
a review-round cap (default 3, clamped 1..5). Reaching the cap still failing
fails the team run (fail-closed, never silently accepted).

Artificial takeover (FR-006) reuses 050's ``human_approval`` semantics: a declared
takeover point suspends the run through ``RunSuspended`` and the human decision
overrides the leader verdict. Member ``employee_id`` is a soft dependency on 051:
if the employee injection hook is available it is applied; otherwise the key is
ignored and an event is recorded (FR-010) — it never blocks delivery of this
feature.

The module is transport-agnostic: all model calls go through the injected runner,
which already applies 001 gatekeeping + 007 resilience. This deliberately
parallels ``supervisor.py`` (decompose/aggregate) but keeps its own failure
threshold configuration (plan.md: no reuse of supervisor's hardcoded 1.0).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .graph import Node

#: Default review-round cap (decision #4, OQ-1 default 3); clamped to 1..5.
DEFAULT_MAX_REVIEW_ROUNDS = 3
MIN_MAX_REVIEW_ROUNDS = 1
MAX_MAX_REVIEW_ROUNDS = 5

#: Default reassign cap (OQ-2 default: matches supervisor's 1.0 failure threshold).
DEFAULT_MAX_REASSIGN = 3
#: Reassign cap upper bound (bounds the failure loop; clamp to 1..10).
MAX_MAX_REASSIGN = 10

#: Default max concurrency for member execution (graph same口径).
DEFAULT_MAX_CONCURRENCY = 4

VERDICT_ACCEPT = "accept"
VERDICT_REWORK = "rework"

#: Event names carried on the run audit (050 run_store.append_event).
EVENT_DECOMPOSE = "team.decomposed"
EVENT_MEMBER_STARTED = "team.member.started"
EVENT_MEMBER_COMPLETED = "team.member.completed"
EVENT_BLACKBOARD_WRITE = "team.blackboard.write"
EVENT_REVIEW = "team.review"
EVENT_TAKEOVER = "team.takeover"

#: Takeover trigger conditions (FR-006, OQ-3): 首期人工主动触发；验收分歧自动触发二期。
TAKEOVER_TRIGGER_ON_REWORK = "on_rework"
TAKEOVER_TRIGGER_ON_ROUND_CAP = "on_round_cap"
TAKEOVER_TRIGGER_MANUAL = "manual"
TAKEOVER_TRIGGERS = (TAKEOVER_TRIGGER_ON_REWORK, TAKEOVER_TRIGGER_ON_ROUND_CAP, TAKEOVER_TRIGGER_MANUAL)

#: Node-level ``mode`` value for a team child inside a graph execution.
NODE_MODE_TEAM = "team"

TeamRunner = Callable[[Node, dict[str, Any]], Awaitable[Any]]


class TeamError(ValueError):
    """Raised for an invalid team declaration or execution."""


def clamp_review_rounds(value: Any) -> int:
    """Clamp the review-round cap to ``1..5`` (decision #4; out-of-range records an event)."""
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_REVIEW_ROUNDS
    return max(MIN_MAX_REVIEW_ROUNDS, min(MAX_MAX_REVIEW_ROUNDS, raw))


def clamp_reassign(value: Any) -> int:
    """Clamp the reassign cap to ``1..10`` (positive; bounds the failure loop)."""
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_REASSIGN
    return max(1, min(10, raw))


@dataclass
class TeamPlan:
    """Leader-produced assignment table: member x subtask (FR-002)."""

    assignments: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_output(cls, output: Any, *, member_ids: list[str]) -> "TeamPlan":
        """Parse a leader output into a plan; fail-closed on a reference to an
        unknown member (Edge Cases: 分派表引用不存在成员 fail-closed)."""
        if not isinstance(output, dict):
            raise TeamError("领导未产出分派表（期望 dict）")
        raw = output.get("assignments") or output.get("plan") or output
        if not isinstance(raw, dict):
            raise TeamError("分派表必须是 {member_id: subtask} 映射")
        member_set = set(member_ids)
        assignments: dict[str, dict[str, Any]] = {}
        for member_id, subtask in raw.items():
            member = str(member_id)
            if member not in member_set:
                raise TeamError(f"分派表引用不存在的成员节点：{member!r}（fail-closed）")
            if isinstance(subtask, dict):
                assignments[member] = dict(subtask)
            else:
                assignments[member] = {"task": str(subtask)}
        if not assignments:
            raise TeamError("分派表为空")
        return cls(assignments=assignments)

    def as_payload(self) -> dict[str, Any]:
        return {"assignments": self.assignments}


@dataclass
class BlackboardEntry:
    """One blackboard material entry (author / version / content; FR-003)."""

    key: str
    author: str
    version: int
    content: Any = None
    review_opinion: str = ""

    def as_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "author": self.author,
            "version": self.version,
            "content": self.content,
            "review_opinion": self.review_opinion,
        }


@dataclass
class ReviewVerdict:
    """Leader acceptance verdict (accept / rework + opinion + target member)."""

    verdict: str
    opinion: str = ""
    target_member: str = ""

    @classmethod
    def from_output(cls, output: Any, *, member_ids: list[str]) -> "ReviewVerdict":
        """Parse a leader review output; verdict must be accept/rework (fail-closed)."""
        if isinstance(output, dict):
            raw_verdict = str(output.get("verdict") or output.get("decision") or "").lower()
            opinion = str(output.get("opinion") or output.get("reason") or output.get("comment") or "")
            target = str(output.get("target_member") or output.get("member") or "")
        else:
            text = str(output or "").strip().lower()
            if text in ("accept", "pass", "approve", "ok"):
                raw_verdict = VERDICT_ACCEPT
            elif text in ("rework", "reject", "retry"):
                raw_verdict = VERDICT_REWORK
            else:
                raw_verdict = ""
            opinion = str(output or "")
            target = ""
        if raw_verdict not in (VERDICT_ACCEPT, VERDICT_REWORK):
            # OQ-1: 解析失败不得静默回退 accept（治理旁路）。
            raise TeamError(f"领导判定无效：{raw_verdict!r}（须 accept 或 rework）")
        if raw_verdict == VERDICT_REWORK and target and target not in member_ids:
            raise TeamError(f"rework 目标成员不存在：{target!r}（fail-closed）")
        return cls(verdict=raw_verdict, opinion=opinion, target_member=target)

    def as_payload(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "opinion": self.opinion, "target_member": self.target_member}


@dataclass
class TeamRunState:
    """Run-level team state (round / reassign / takeover), kept on the 050 snapshot."""

    round: int = 0
    reassign_count: int = 0
    takeover: bool = False
    verdicts: list[dict[str, Any]] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "round": self.round,
            "reassign_count": self.reassign_count,
            "takeover": self.takeover,
            "verdicts": list(self.verdicts),
        }


@dataclass
class TeamResult:
    """Aggregated team run result (FR-007 / R-9: details on the parent item)."""

    team_id: str
    ok: bool
    reason: str = ""
    blackboard: list[dict[str, Any]] = field(default_factory=list)
    rounds: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "ok": self.ok,
            "reason": self.reason,
            "blackboard": list(self.blackboard),
            "rounds": list(self.rounds),
            "state": dict(self.state),
            "output": dict(self.output),
        }


def _member_node(node: Node, member_id: str, subtask: dict[str, Any]) -> Node:
    """Materialize a member execution as a ``Node`` carrying its subtask.

    The member keeps the member node's id (downstream reads by node id); the
    subtask payload is shallow-merged so the runner can see what to do.
    """
    payload = dict(node.payload or {})
    for key, value in subtask.items():
        if value is not None:
            payload[key] = value
    return Node(id=member_id, mode=node.mode, payload=payload)


async def run_team(
    node: Node,
    runner: TeamRunner,
    *,
    context: dict[str, Any],
    member_nodes: list[Node],
    leader_node: Node | None = None,
    max_review_rounds: int = DEFAULT_MAX_REVIEW_ROUNDS,
    max_reassign: int = DEFAULT_MAX_REASSIGN,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    employee_hook: Callable[[Node, dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    takeover: dict[str, Any] | None = None,
    approval_hook: Callable[[Node, dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
) -> TeamResult:
    """Execute the team protocol (US1 + US2).

    Decompose -> members run their subtasks -> blackboard writes -> review loop.
    Any leader failure fails the team (Edge Cases: 领导节点失败 fail-closed).
    """
    if not member_nodes:
        raise TeamError("team 需要至少一个成员节点")
    rounds = clamp_review_rounds(max_review_rounds)
    reassign_cap = clamp_reassign(max_reassign)
    concurrency = max(1, int(max_concurrency))
    state = TeamRunState()
    blackboard: dict[str, list[BlackboardEntry]] = {}
    round_log: list[dict[str, Any]] = []

    async def emit(payload: dict[str, Any]) -> None:
        if event is not None:
            await event(payload)

    # US1 step 1: leader decomposes into a plan.
    leader = leader_node or Node(id=str(node.id), mode=NODE_MODE_TEAM, payload={})
    try:
        plan_output = await runner(leader, dict(context))
    except Exception as exc:  # noqa: BLE001 - leader failure fails the team
        return TeamResult(team_id=node.id, ok=False, reason=f"领导节点失败：{exc}")
    plan = TeamPlan.from_output(plan_output, member_ids=[m.id for m in member_nodes])
    await emit({"event": EVENT_DECOMPOSE, "node": node.id, "plan": plan.as_payload()})

    # US1 step 2: run members per their assigned subtasks (bounded concurrency).
    async def execute_member(member: Node) -> tuple[str, Any]:
        subtask = plan.assignments.get(member.id, {"task": str(plan_output)})
        exec_node = _member_node(member, member.id, subtask)
        if employee_hook is not None:
            try:
                exec_node = employee_hook(exec_node, dict(context)) or exec_node
            except Exception:  # noqa: BLE001 - soft dependency, never blocks (FR-010)
                pass
        await emit({"event": EVENT_MEMBER_STARTED, "node": member.id})
        try:
            output = await runner(exec_node, dict(context))
        except Exception as exc:  # noqa: BLE001 - member failure is isolated
            await emit({"event": EVENT_MEMBER_COMPLETED, "node": member.id, "ok": False, "error": str(exc)})
            raise
        # Blackboard write: key is namespace-isolated by author (Edge Cases).
        author_key = f"{member.id}:{subtask.get('task', 'output')}"
        existing = blackboard.setdefault(author_key, [])
        version = len(existing) + 1
        entry = BlackboardEntry(key=author_key, author=member.id, version=version, content=output)
        existing.append(entry)
        await emit({"event": EVENT_BLACKBOARD_WRITE, "node": member.id, "key": author_key, "version": version})
        return member.id, output

    semaphore = asyncio.Semaphore(concurrency)
    member_outputs: dict[str, Any] = {}
    member_failures: list[str] = []

    async def guarded(member: Node) -> None:
        async with semaphore:
            try:
                member_id, output = await execute_member(member)
                member_outputs[member_id] = output
                context[member.id] = output
            except Exception as exc:  # noqa: BLE001
                member_failures.append(member.id)
                context[member.id] = {"error": str(exc)}

    await asyncio.gather(*(guarded(member) for member in member_nodes))

    # Failure propagation: a failed member does not drag the others down, but a
    # reassign is possible only within the cap (FR-005 / OQ-2).
    state.reassign_count = len(member_failures)
    if member_failures and state.reassign_count > reassign_cap:
        return TeamResult(
            team_id=node.id,
            ok=False,
            reason=f"成员失败数 {len(member_failures)} 超过重指派上限 {reassign_cap}",
            blackboard=_blackboard_payload(blackboard),
            rounds=round_log,
            state=state.as_payload(),
        )

    # US2: review loop. leader judges accept/rework until accept or cap reached.
    accepted: dict[str, Any] = {}
    for round_index in range(1, rounds + 1):
        state.round = round_index
        review_payload = {"round": round_index, "outputs": dict(member_outputs)}
        review_output = await runner(leader, {**dict(context), "review": review_payload})
        verdict = ReviewVerdict.from_output(review_output, member_ids=[m.id for m in member_nodes])
        state.verdicts.append(verdict.as_payload())
        await emit({
            "event": EVENT_REVIEW,
            "node": node.id,
            "round": round_index,
            **verdict.as_payload(),
        })
        round_log.append({"round": round_index, **verdict.as_payload()})
        # FR-006 / OQ-3: 接管点命中（人工主动触发，自动触发二期）→ approval_hook
        # 获取人工决策覆盖领导判定；决策全审计（SC-005）。hook 未注入时忽略接管，
        # 走领导判定（soft dependency on 050，不阻塞团队交付）。
        if _should_take_over(takeover, verdict, round_index, rounds) and approval_hook is not None:
            state.takeover = True
            human = await approval_hook(leader, dict(context), {
                "takeover": dict(takeover or {}),
                "round": round_index,
                "verdict": verdict.as_payload(),
                "outputs": dict(member_outputs),
            })
            human_verdict = str(human.get("verdict") or "")
            await emit({
                "event": EVENT_TAKEOVER,
                "node": node.id,
                "round": round_index,
                "approver": str(human.get("approver") or ""),
                "reason": str(human.get("reason") or ""),
                "decision": human_verdict,
                "overrides": verdict.as_payload(),
            })
            round_log.append({
                "round": round_index,
                "takeover": True,
                "approver": str(human.get("approver") or ""),
                "reason": str(human.get("reason") or ""),
                "decision": human_verdict,
                "overrides": verdict.as_payload(),
            })
            if human_verdict == VERDICT_ACCEPT:
                accepted = dict(member_outputs)
                break
            if human_verdict == "terminate":
                return TeamResult(
                    team_id=node.id,
                    ok=False,
                    reason=f"人工接管终止（{human.get('approver') or '?'}）：{human.get('reason') or ''}",
                    blackboard=_blackboard_payload(blackboard),
                    rounds=round_log,
                    state=state.as_payload(),
                )
            # rework 或未知决策：落到下方 rework 分支，opinion 用人工意见。
            verdict = ReviewVerdict(verdict=VERDICT_REWORK, opinion=str(human.get("opinion") or verdict.opinion), target_member=verdict.target_member)
        if verdict.verdict == VERDICT_ACCEPT:
            accepted = dict(member_outputs)
            break
        # rework: resend the subtask with the opinion to the target member.
        target = verdict.target_member or (member_failures[0] if member_failures else member_nodes[0].id)
        target_node = next((m for m in member_nodes if m.id == target), None)
        if target_node is None:
            raise TeamError(f"rework 目标成员不存在：{target!r}")
        subtask = plan.assignments.get(target, {"task": str(plan_output)})
        subtask = {**subtask, "review_opinion": verdict.opinion}
        try:
            rework_output = await runner(_member_node(target_node, target, subtask), dict(context))
        except Exception as exc:  # noqa: BLE001
            raise TeamError(f"成员重做失败：{target}：{exc}") from exc
        member_outputs[target] = rework_output
        context[target] = rework_output
        author_key = f"{target}:{subtask.get('task', 'output')}"
        existing = blackboard.setdefault(author_key, [])
        version = len(existing) + 1
        existing.append(BlackboardEntry(key=author_key, author=target, version=version, content=rework_output, review_opinion=verdict.opinion))
        await emit({"event": EVENT_BLACKBOARD_WRITE, "node": target, "key": author_key, "version": version})
    else:
        # Reached the cap still failing: fail-closed, never silently accept.
        return TeamResult(
            team_id=node.id,
            ok=False,
            reason=f"验收轮次达上限 {rounds} 仍不合格（fail-closed，不静默接受）",
            blackboard=_blackboard_payload(blackboard),
            rounds=round_log,
            state=state.as_payload(),
        )

    return TeamResult(
        team_id=node.id,
        ok=True,
        blackboard=_blackboard_payload(blackboard),
        rounds=round_log,
        state=state.as_payload(),
        output=accepted,
    )


def _should_take_over(
    takeover: dict[str, Any] | None,
    verdict: ReviewVerdict,
    round_index: int,
    rounds: int,
) -> bool:
    """FR-006 trigger predicate: a declared takeover point fires on its condition.

    ``on_rework`` fires when the leader asks for rework (验收分歧); ``manual`` is
    a declared point that always offers the human a decision; ``on_round_cap``
    fires only at the last allowed round (达上限前的人工兜底). No declaration or
    unknown trigger never fires — the team runs on leader verdicts alone.
    """
    if not takeover:
        return False
    trigger = str(takeover.get("trigger") or TAKEOVER_TRIGGER_MANUAL)
    if trigger == TAKEOVER_TRIGGER_MANUAL:
        return True
    if trigger == TAKEOVER_TRIGGER_ON_REWORK:
        return verdict.verdict == VERDICT_REWORK
    if trigger == TAKEOVER_TRIGGER_ON_ROUND_CAP:
        return round_index >= rounds and verdict.verdict == VERDICT_REWORK
    return False


def _blackboard_payload(blackboard: dict[str, list[BlackboardEntry]]) -> list[dict[str, Any]]:
    """Flatten the blackboard for the parent item payload (old versions kept)."""
    flat: list[dict[str, Any]] = []
    for entries in blackboard.values():
        flat.extend(entry.as_payload() for entry in entries)
    return flat


__all__ = [
    "NODE_MODE_TEAM",
    "DEFAULT_MAX_REVIEW_ROUNDS",
    "MIN_MAX_REVIEW_ROUNDS",
    "MAX_MAX_REVIEW_ROUNDS",
    "DEFAULT_MAX_REASSIGN",
    "MAX_MAX_REASSIGN",
    "DEFAULT_MAX_CONCURRENCY",
    "VERDICT_ACCEPT",
    "VERDICT_REWORK",
    "EVENT_DECOMPOSE",
    "EVENT_MEMBER_STARTED",
    "EVENT_MEMBER_COMPLETED",
    "EVENT_BLACKBOARD_WRITE",
    "EVENT_REVIEW",
    "EVENT_TAKEOVER",
    "TAKEOVER_TRIGGER_ON_REWORK",
    "TAKEOVER_TRIGGER_ON_ROUND_CAP",
    "TAKEOVER_TRIGGER_MANUAL",
    "TAKEOVER_TRIGGERS",
    "TeamError",
    "TeamPlan",
    "BlackboardEntry",
    "ReviewVerdict",
    "TeamRunState",
    "TeamResult",
    "clamp_review_rounds",
    "clamp_reassign",
    "run_team",
]
