"""Debate orchestration mode (044 FR-005 / FR-006 / FR-007).

A pro agent and a con agent exchange rounds. After every round each side may read
the *other* side's output of the previous round only (044 R-4: strictly
alternating, nobody reads the current round's counterpart). Termination happens on
any of three conditions, whichever comes first (FR-006):

* round budget exhausted (``max_rounds``, default 3, clamped into 1..10, with a
  ``debate.rounds_clamped`` event carrying ``{requested, applied, min, max}``);
* an ``arbiter`` node emits a ``confidence >= convergence_threshold`` (default
  0.8);
* both sides repeat themselves: the Jaccard token similarity between round *n*
  and round *n-1* outputs is ``>= similarity_threshold`` (default 0.9) **for each
  side independently** (R-5).

``arbiter`` is optional. When absent the conclusion is the last pro output and
``confidence`` stays ``None`` (we never fabricate a confidence, R-7) — the
trace marks ``arbiter="absent"``. When declared, the node must exist (checked at
load time by the loader, FR-007 fail-closed).

Failure semantics (R-15): if either side fails the debate stops immediately and
the node fails; rounds already produced are preserved. A failing arbiter fails the
node — we do **not** fall back to the last side's output. ``max_rounds`` is counted
in rounds, never in wall clock, so queueing does not eat budget.

Context keys follow ``debate:{orchestration_id}:{node_id}:round:{n}:{side}`` and
live in a local dictionary, never in the global session context (R-4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.self_evolution.similarity import jaccard

from .graph import Node

DEFAULT_MAX_ROUNDS = 3
MIN_ROUNDS = 1
MAX_ROUNDS = 10
DEFAULT_CONVERGENCE_THRESHOLD = 0.8
DEFAULT_SIMILARITY_THRESHOLD = 0.9

SIDE_PRO = "pro"
SIDE_CON = "con"
VALID_SIDES = (SIDE_PRO, SIDE_CON)

TERMINATION_MAX_ROUNDS = "max_rounds"
TERMINATION_ARBITER_CONFIDENCE = "arbiter_confidence"
TERMINATION_OUTPUT_CONVERGED = "output_converged"
ARBITER_ABSENT = "absent"

#: Termination reasons that count as "converged" for trace purposes.
CONVERGED_REASONS = (TERMINATION_ARBITER_CONFIDENCE, TERMINATION_OUTPUT_CONVERGED)


class DebateError(ValueError):
    """Raised when a debate cannot produce a conclusion (R-15)."""


@dataclass
class DebateRound:
    """One recorded round of the debate."""

    index: int
    pro: str
    con: str
    pro_confidence: float | None = None
    con_confidence: float | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "pro": self.pro,
            "con": self.con,
            "pro_confidence": self.pro_confidence,
            "con_confidence": self.con_confidence,
        }


@dataclass
class DebateResult:
    """The full outcome of a debate, including the explainability payload."""

    rounds: list[DebateRound] = field(default_factory=list)
    conclusion: str = ""
    confidence: float | None = None
    termination: str = ""
    arbiter: str = ARBITER_ABSENT
    requested_rounds: int = DEFAULT_MAX_ROUNDS
    applied_rounds: int = DEFAULT_MAX_ROUNDS
    clamped: bool = False

    @property
    def converged(self) -> bool:
        return self.termination in CONVERGED_REASONS

    def as_payload(self) -> dict[str, Any]:
        return {
            "conclusion": self.conclusion,
            "confidence": self.confidence,
            "termination": self.termination,
            "converged": self.converged,
            "arbiter": self.arbiter,
            "rounds": [round_.as_payload() for round_ in self.rounds],
            "requested_rounds": self.requested_rounds,
            "applied_rounds": self.applied_rounds,
            "rounds_clamped": self.clamped,
        }


def clamp_rounds(requested: int | None) -> tuple[int, bool]:
    """Clamp the requested round budget into ``MIN_ROUNDS..MAX_ROUNDS`` (FR-006)."""
    try:
        value = int(requested) if requested is not None else DEFAULT_MAX_ROUNDS
    except (TypeError, ValueError):
        value = DEFAULT_MAX_ROUNDS
    applied = max(MIN_ROUNDS, min(MAX_ROUNDS, value))
    return applied, applied != value


def _round_key(orchestration_id: str, node_id: str, round_index: int, side: str) -> str:
    return f"debate:{orchestration_id}:{node_id}:round:{round_index}:{side}"


def _tokens(text: str) -> list[str]:
    return str(text or "").split()


def _similar(output_a: str, output_b: str, threshold: float) -> bool:
    return jaccard(_tokens(output_a), _tokens(output_b)) >= float(threshold)


def _extract_text(output: Any) -> str:
    """Normalize a node output into the text used for similarity / conclusion."""
    if isinstance(output, dict):
        for key in ("text", "answer", "content", "output", "conclusion", "message"):
            if isinstance(output.get(key), str) and output[key].strip():
                return output[key]
        return str(output)
    return "" if output is None else str(output)


def _arbiter_reading(result: DebateResult) -> str:
    lines = []
    for round_ in result.rounds:
        lines.append(f"round {round_.index}: 正方 —— {round_.pro}")
        lines.append(f"round {round_.index}: 反方 —— {round_.con}")
    return "\n".join(lines)


async def run_debate(
    node: Node,
    runner: Callable[[Node, dict[str, Any]], Awaitable[Any]],
    *,
    context: dict[str, Any],
    orchestration_id: str = "",
    pro_node: Node | None = None,
    con_node: Node | None = None,
    arbiter_node: Node | None = None,
    max_rounds: int | None = None,
    convergence_threshold: float = DEFAULT_CONVERGENCE_THRESHOLD,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> DebateResult:
    """Run one debate and return the explainable result (never raises on sides)."""
    if pro_node is None or con_node is None:
        raise DebateError("debate requires both pro and con nodes")
    applied, clamped = clamp_rounds(max_rounds)
    result = DebateResult(
        arbiter=arbiter_node.id if arbiter_node else ARBITER_ABSENT,
        requested_rounds=int(max_rounds) if max_rounds is not None else DEFAULT_MAX_ROUNDS,
        applied_rounds=applied,
        clamped=clamped,
    )
    local: dict[str, Any] = {}
    previous_pro = ""
    previous_con = ""

    for index in range(1, applied + 1):
        # Each side reads only the *previous* round of the counterpart (R-4).
        pro_context = dict(context)
        pro_context.update(local)
        pro_context["debate"] = {"round": index, "side": SIDE_PRO, "opponent_previous": previous_con}
        con_context = dict(context)
        con_context.update(local)
        con_context["debate"] = {"round": index, "side": SIDE_CON, "opponent_previous": previous_pro}

        try:
            pro_output = await runner(pro_node, pro_context)
        except Exception as error:  # noqa: BLE001 - R-15
            raise DebateError(f"正方节点 {pro_node.id} 失败：{type(error).__name__}: {error}") from error
        try:
            con_output = await runner(con_node, con_context)
        except Exception as error:  # noqa: BLE001 - R-15
            raise DebateError(f"反方节点 {con_node.id} 失败：{type(error).__name__}: {error}") from error

        round_ = DebateRound(index=index, pro=_extract_text(pro_output), con=_extract_text(con_output))
        result.rounds.append(round_)
        local[_round_key(orchestration_id, node.id, index, SIDE_PRO)] = pro_output
        local[_round_key(orchestration_id, node.id, index, SIDE_CON)] = con_output
        previous_pro, previous_con = round_.pro, round_.con

        # Termination 3: both sides converged for two consecutive rounds.
        if index >= 2:
            prev = result.rounds[index - 2]
            if (
                _similar(prev.pro, round_.pro, similarity_threshold)
                and _similar(prev.con, round_.con, similarity_threshold)
            ):
                result.termination = TERMINATION_OUTPUT_CONVERGED
                break

        if arbiter_node is not None:
            arbiter_output = await runner(
                arbiter_node,
                {
                    **context,
                    **local,
                    "debate": {
                        "round": index,
                        "role": "arbiter",
                        "record": _arbiter_reading(result),
                    },
                },
            )
            if not isinstance(arbiter_output, dict):
                raise DebateError(f"仲裁节点 {arbiter_node.id} 输出不是对象（不能产出结论与置信度）")
            confidence = arbiter_output.get("confidence")
            result.conclusion = _extract_text(arbiter_output.get("conclusion") or arbiter_output)
            result.confidence = float(confidence) if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else None
            if result.confidence is not None and result.confidence >= float(convergence_threshold):
                result.termination = TERMINATION_ARBITER_CONFIDENCE
                break
    else:
        result.termination = TERMINATION_MAX_ROUNDS

    if not result.termination:
        result.termination = TERMINATION_MAX_ROUNDS
    if not result.conclusion:
        result.conclusion = result.rounds[-1].pro if result.rounds else ""
    return result
