"""032-eval-gate: shared data model, collection names and defaults.

Three new MongoDB collections:

- ``skill_eval_cases``   — golden test cases per ``(tenant_id, skill_id)``
- ``skill_eval_policies``— tenant / skill threshold policy
- ``skill_eval_runs``    — one record per publish-time (or dry-run) evaluation

032 deliberately does **not** write 016's ``skill_quality_metrics`` daily bucket
(the runtime rolling aggregate). See spec 已定决策 #9.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Collection names
# ---------------------------------------------------------------------------

CASES_COLLECTION = "skill_eval_cases"
POLICIES_COLLECTION = "skill_eval_policies"
RUNS_COLLECTION = "skill_eval_runs"

# Reuse 001's single audit sink (see governance/layers/audit.py).
GATE_EVENTS_COLLECTION = "gate_events"

# ---------------------------------------------------------------------------
# Defaults (spec 已定决策 #6 / FR-006 / FR-011)
# ---------------------------------------------------------------------------

#: Aligned with 011 ``DEFAULT_MIN_SAMPLES`` (chat-api/self_evolution/similarity.py).
DEFAULT_MIN_CASES = 5

#: Hard cap on golden cases per skill (spec edge case: 超大测试集).
DEFAULT_MAX_CASES = 50

#: Overall evaluation timeout in seconds (spec 已定决策 #7).
DEFAULT_TIMEOUT_SECONDS = 300

#: Per-LLM-call timeout inside the evaluation run (must be << overall timeout).
DEFAULT_LLM_TIMEOUT_SECONDS = 60

#: Default thresholds (fraction 0..1).  Fail-closed default values chosen so a
#: freshly provisioned tenant gets a meaningful baseline gate rather than a
#: trivially-passing one.
DEFAULT_MIN_CITATION_SUPPORT = 0.6
DEFAULT_MIN_REFUSAL_ACCURACY = 0.6
DEFAULT_MIN_TASK_SUCCESS = 0.6

#: Per-case LLM retry budget (admin-api does not implement resilience itself —
#: 007 resilience lives on the chat-api side; here we only bound our own wait).
DEFAULT_EXECUTION_RETRIES = 2


# ---------------------------------------------------------------------------
# Result objects (deterministic, JSON-serialisable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Metrics:
    """Three computed proxies for the unmeasurable "hallucination rate".

    A metric is ``None`` when its denominator is empty (no case carried
    ``expected_refs`` / ``expect_refusal`` / task expectations) — spec Edge
    Case: 空期望不参与分母.  ``None`` means "不适用" and is therefore skipped by
    the threshold comparison instead of being coerced to 0.0 (which would block
    a skill for a metric nobody can measure).
    """

    citation_support: float | None = None
    refusal_accuracy: float | None = None
    task_success: float | None = None

    def as_dict(self) -> dict[str, float | None]:
        return {
            "citation_support": None if self.citation_support is None else round(self.citation_support, 4),
            "refusal_accuracy": None if self.refusal_accuracy is None else round(self.refusal_accuracy, 4),
            "task_success": None if self.task_success is None else round(self.task_success, 4),
        }

    def below(self, other: "Metrics", *, tolerance: float = 1e-9) -> list[str]:
        """Return the names of metrics strictly below ``other`` (threshold).

        ``==`` is passing, so a tolerance is used to avoid float noise; a
        metric this run could not measure (``None``) is not compared.
        """
        failed: list[str] = []
        for key in ("citation_support", "refusal_accuracy", "task_success"):
            value = getattr(self, key)
            if value is None:
                continue
            if value + tolerance < float(getattr(other, key) or 0.0):
                failed.append(key)
        return failed


@dataclass
class EvalCaseResult:
    """Per-case judgement summary — never the full LLM output (FR-009).

    Stored in ``skill_eval_runs.case_results``.
    """

    case_id: str
    kind: str = "task"  # 'task' | 'refusal'
    citation_support: bool | None = None
    refusal_accuracy: bool | None = None
    task_success: bool | None = None
    reasons: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "kind": self.kind,
            "citation_support": self.citation_support,
            "refusal_accuracy": self.refusal_accuracy,
            "task_success": self.task_success,
            "reasons": self.reasons,
            "duration_ms": self.duration_ms,
        }


def policy_defaults() -> dict[str, Any]:
    """A fresh ``skill_eval_policies`` document for a tenant (no skill override)."""
    return {
        "min_citation_support": DEFAULT_MIN_CITATION_SUPPORT,
        "min_refusal_accuracy": DEFAULT_MIN_REFUSAL_ACCURACY,
        "min_task_success": DEFAULT_MIN_TASK_SUCCESS,
        "min_cases": DEFAULT_MIN_CASES,
        "max_cases": DEFAULT_MAX_CASES,
        "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
    }