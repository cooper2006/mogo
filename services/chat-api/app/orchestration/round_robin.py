"""Round-robin selection mode (044 FR-002 / FR-003 / FR-004).

One task node carries several candidate instances (``instances:`` in YAML, each a
shallow override of ``model`` / ``temperature`` / ``prompt`` / ``label``). Every
candidate runs through the same transport-agnostic runner the 010 engine uses,
bounded by ``max_concurrency`` (excess candidates queue, they are never
rejected). A deterministic selector then picks exactly one result:

* ``first_success``  - the first candidate that completes successfully wins; the
  remaining candidates are still *observed* but their results are discarded
  (``status="discarded"``), never adopted;
* ``highest_score``   - the candidate with the highest ``payload.score`` wins
  (clamped to ``0.0..1.0``); candidates without a score do not take part in the
  comparison but their outputs are preserved; no scores at all falls back to
  ``first_success`` with ``fallback_reason="no_score"``;
* ``majority``        - outputs are normalized (``strip().lower()`` then all
  whitespace removed) and voted on; a tie takes the earliest completed candidate
  and records ``majority_tie``; no majority falls back to ``first_success`` with
  ``fallback_reason="no_majority"``.

Selection is explainable: the caller receives the per-candidate outcomes plus a
``SelectionResult`` carrying the strategy and any fallback reason, so the runner
can put ``payload.candidates`` / ``payload.selection`` on the node item (044
R-9: details live on the parent item, no nested ``item.*`` events).

This module deliberately duplicates the *idea* of
``app.enterprise_capabilities.evidence.foundation.fair_selection.round_robin_take``
(round-robin over groups so one group cannot monopolize capacity, 18 lines)
instead of importing it: that helper lives in the enterprise-capabilities package
which itself imports ``app.orchestration``, so importing it here would invert the
dependency (044 R-12 / tasks T003). The copied helper is :func:`balanced_take`.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Mapping

from .graph import Node

STRATEGY_FIRST_SUCCESS = "first_success"
STRATEGY_HIGHEST_SCORE = "highest_score"
STRATEGY_MAJORITY = "majority"
VALID_STRATEGIES = (STRATEGY_FIRST_SUCCESS, STRATEGY_HIGHEST_SCORE, STRATEGY_MAJORITY)
DEFAULT_STRATEGY = STRATEGY_HIGHEST_SCORE

DEFAULT_MAX_CONCURRENCY = 4

#: Candidate overrides a node may declare. Anything else (notably ``retry`` /
#: ``conditions`` / ``depends_on``) belongs to node-level semantics and would
#: make the execution graph ambiguous, so it fails at load time (044 R-1).
ALLOWED_INSTANCE_KEYS = ("model", "temperature", "prompt", "label")
FORBIDDEN_INSTANCE_KEYS = ("retry", "conditions", "condition", "depends_on", "mode")

STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_DISCARDED = "discarded"

_WHITESPACE = re.compile(r"\s+")


class RoundRobinError(ValueError):
    """Raised for an invalid ``instances:`` declaration."""


@dataclass(frozen=True)
class CandidateSpec:
    """One declared candidate instance."""

    label: str
    overrides: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class CandidateOutcome:
    """The recorded result of one candidate execution."""

    label: str
    status: str = STATUS_COMPLETED
    output: Any = None
    score: float | None = None
    error: str = ""
    order: int = 0


@dataclass
class SelectionResult:
    """Which candidate won, under which strategy, and why."""

    chosen: CandidateOutcome | None
    strategy: str
    fallback_reason: str = ""
    candidates: list[CandidateOutcome] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        """The explainability payload written to the node item (044 R-9)."""
        return {
            "strategy": self.strategy,
            "chosen": self.chosen.label if self.chosen else "",
            "fallback_reason": self.fallback_reason,
            "candidates": [
                {
                    "label": item.label,
                    "status": item.status,
                    "score": item.score,
                    "error": item.error,
                }
                for item in self.candidates
            ],
        }


def parse_instances(raw: Any) -> list[CandidateSpec]:
    """Parse the ``instances:`` declaration into candidate specs.

    An empty/absent declaration means "single candidate" (the node degrades to a
    plain execution, 044 edge case). Forbidden override keys fail closed (R-1).
    """
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise RoundRobinError("'instances' must be a list")
    specs: list[CandidateSpec] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise RoundRobinError(f"instances[{index}] must be a mapping")
        forbidden = sorted(set(item) & set(FORBIDDEN_INSTANCE_KEYS))
        if forbidden:
            raise RoundRobinError(
                f"instances[{index}] may not override {', '.join(forbidden)} "
                "(node-level semantics)"
            )
        unknown = sorted(set(item) - set(ALLOWED_INSTANCE_KEYS))
        if unknown:
            raise RoundRobinError(
                f"instances[{index}] has unsupported keys: {', '.join(unknown)}"
            )
        label = str(item.get("label") or f"candidate_{index + 1}")
        overrides = {key: value for key, value in item.items() if key != "label"}
        specs.append(CandidateSpec(label=label, overrides=overrides))
    return specs


def candidate_node(node: Node, spec: CandidateSpec) -> Node:
    """Materialize a candidate as a ``Node`` with a shallow payload override.

    The candidate keeps the parent node id (downstream reads by node id, 010
    FR-1); only the declared override keys change, and ``label`` is carried on the
    payload so the runner can identify which instance produced the output.
    """
    payload = dict(node.payload or {})
    for key, value in spec.overrides.items():
        if value is not None:
            payload[key] = value
    payload["instance_label"] = spec.label
    return Node(
        id=node.id,
        mode=node.mode,
        condition=node.condition,
        retry=node.retry,
        payload=payload,
    )


def score_of(output: Any) -> float | None:
    """Read ``score`` from a candidate output, clamped to ``0.0..1.0`` (R-2)."""
    if not isinstance(output, Mapping):
        return None
    raw = output.get("score")
    if isinstance(raw, bool):
        return None
    if not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    if value != value:  # NaN
        return None
    return max(0.0, min(1.0, value))


def normalize_output(output: Any) -> str:
    """Normalize an output for ``majority`` comparison (R-3)."""
    if isinstance(output, Mapping):
        for key in ("text", "answer", "content", "output", "message"):
            if key in output:
                output = output[key]
                break
        else:
            output = str(sorted((str(k), str(v)) for k, v in output.items()))
    text = str(output or "").strip().lower()
    return _WHITESPACE.sub("", text)


def select_candidate(outcomes: list[CandidateOutcome], *, strategy: str = DEFAULT_STRATEGY) -> SelectionResult:
    """Pick one candidate deterministically (044 FR-002 / R-2 / R-3 / R-14)."""
    if strategy not in VALID_STRATEGIES:
        strategy = DEFAULT_STRATEGY
    ordered = sorted(outcomes, key=lambda item: item.order)
    completed = [item for item in ordered if item.status == STATUS_COMPLETED]
    if not completed:
        return SelectionResult(chosen=None, strategy=strategy, candidates=ordered)

    if strategy == STRATEGY_FIRST_SUCCESS:
        return SelectionResult(chosen=completed[0], strategy=strategy, candidates=ordered)

    if strategy == STRATEGY_HIGHEST_SCORE:
        scored = [item for item in completed if item.score is not None]
        if not scored:
            # R-2 iii) nobody produced a score -> first success. R-14: when scored
            # candidates *existed* but all of them failed, adopt an unscored
            # candidate and record why.
            any_scored = any(item.score is not None for item in ordered)
            return SelectionResult(
                chosen=completed[0],
                strategy=STRATEGY_FIRST_SUCCESS,
                fallback_reason="scored_all_failed" if any_scored else "no_score",
                candidates=ordered,
            )
        best = max(scored, key=lambda item: (item.score, -item.order))
        return SelectionResult(chosen=best, strategy=strategy, candidates=ordered)

    counts: dict[str, int] = {}
    first_seen: dict[str, CandidateOutcome] = {}
    for item in completed:
        key = normalize_output(item.output)
        counts[key] = counts.get(key, 0) + 1
        first_seen.setdefault(key, item)
    top = max(counts.values())
    if top < 2:
        # No output repeated => no majority at all -> first success (R-3).
        return SelectionResult(
            chosen=completed[0],
            strategy=STRATEGY_FIRST_SUCCESS,
            fallback_reason="no_majority",
            candidates=ordered,
        )
    winners = [key for key, value in counts.items() if value == top]
    if len(winners) > 1:
        # Tie -> the earliest completed candidate, recorded as such (R-3).
        return SelectionResult(
            chosen=completed[0],
            strategy=strategy,
            fallback_reason="majority_tie",
            candidates=ordered,
        )
    return SelectionResult(chosen=first_seen[winners[0]], strategy=strategy, candidates=ordered)


def balanced_take(groups: Iterable[Iterable[Any]], *, limit: int) -> list[Any]:
    """Round-robin across groups so one group cannot monopolize capacity.

    Copied from the idea of
    ``app/enterprise_capabilities/evidence/foundation/fair_selection.py::round_robin_take``
    (044 R-12): the helper lives in a package that imports ``app.orchestration``,
    so importing it here would invert the dependency. Kept as a plain pure
    function for the same reason it is pure there.
    """
    buckets = [list(group) for group in groups]
    picked: list[Any] = []
    while buckets and len(picked) < max(0, int(limit)):
        for bucket in list(buckets):
            if not bucket:
                buckets.remove(bucket)
                continue
            picked.append(bucket.pop(0))
            if len(picked) >= max(0, int(limit)):
                break
    return picked


CandidateRunner = Callable[[Node, dict[str, Any]], Awaitable[Any]]


async def run_round_robin(
    node: Node,
    runner: CandidateRunner,
    *,
    context: dict[str, Any],
    instances: list[CandidateSpec] | None = None,
    strategy: str = DEFAULT_STRATEGY,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
) -> tuple[SelectionResult, dict[str, Any]]:
    """Execute every candidate and select one winner.

    Candidates run concurrently under ``max_concurrency`` (FR-003). A failing
    candidate never aborts the others: its error is recorded and the selector
    decides (all-failed -> the caller turns the node into ``failed``, R-14).
    ``first_success`` does **not** cancel in-flight work (044 R-6): results are
    observed and then discarded, which avoids side-effect and billing ambiguity.
    """
    if not instances:
        # A node may declare its candidates declaratively (``instances:`` in
        # YAML); callers that already parsed them pass them explicitly.
        instances = parse_instances((node.payload or {}).get("instances"))
    specs = list(instances or [])
    if not specs:
        specs = [CandidateSpec(label="default")]

    semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))
    outcomes: list[CandidateOutcome] = [CandidateOutcome(label=spec.label, order=index) for index, spec in enumerate(specs)]

    async def execute(index: int, spec: CandidateSpec) -> None:
        outcome = outcomes[index]
        async with semaphore:
            try:
                output = await runner(candidate_node(node, spec), dict(context))
            except Exception as error:  # noqa: BLE001 - recorded, never swallowed silently
                outcome.status = STATUS_FAILED
                outcome.error = f"{type(error).__name__}: {error}"
                return
        outcome.output = output
        outcome.score = score_of(output)

    await asyncio.gather(*(execute(index, spec) for index, spec in enumerate(specs)))

    selection = select_candidate(outcomes, strategy=strategy)
    if selection.chosen is not None:
        for outcome in outcomes:
            if outcome is not selection.chosen and outcome.status == STATUS_COMPLETED:
                outcome.status = STATUS_DISCARDED
    payload = selection.as_payload()
    payload["errors"] = [item.error for item in outcomes if item.error]
    return selection, payload
