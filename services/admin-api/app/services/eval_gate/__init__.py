"""032-eval-gate: publish-time evaluation gate.

Exports the gate runner and index bootstrapping.  Modules::

    models.py     data model / collection names / defaults
    test_sets.py  golden test-set CRUD (tenant-isolated)
    policies.py   threshold policy (fail-closed default)
    judges.py     deterministic rule judges
    executor.py   chat-api gateway evaluation executor
    gate.py       gate orchestration + audit events
"""

from __future__ import annotations

from typing import Any

from .gate import EvalGateBlocked, run_gate
from .models import (
    CASES_COLLECTION,
    POLICIES_COLLECTION,
    RUNS_COLLECTION,
)
from .executor import (
    EvaluationExecutionError,
    EvaluationTimeoutError,
    GatewayError,
    run_evaluation,
)
from .judges import aggregate, citation_supported, is_refusal, judge_case, task_successful
from .policies import get_policy, save_policy
from .test_sets import (
    EvalCaseLimitError,
    EvalCaseNotFoundError,
    EvalCaseValidationError,
    SkillNotFoundError,
    create_case,
    delete_case,
    list_cases,
    update_case,
)

__all__ = [
    "EvalGateBlocked",
    "run_gate",
    "run_evaluation",
    "GatewayError",
    "EvaluationExecutionError",
    "EvaluationTimeoutError",
    "aggregate",
    "citation_supported",
    "is_refusal",
    "judge_case",
    "task_successful",
    "get_policy",
    "save_policy",
    "create_case",
    "delete_case",
    "list_cases",
    "update_case",
    "EvalCaseLimitError",
    "EvalCaseNotFoundError",
    "EvalCaseValidationError",
    "SkillNotFoundError",
    "ensure_indexes",
]


async def ensure_indexes() -> None:
    """Create the indexes the eval gate relies on.  Idempotent."""
    from app.core.db import get_db

    db = get_db()
    await db[CASES_COLLECTION].create_index(
        [("tenant_id", 1), ("skill_id", 1), ("created_at", 1)],
        name="skill_eval_cases_tenant_skill_time",
    )
    await db[POLICIES_COLLECTION].create_index(
        [("tenant_id", 1), ("skill_id", 1)],
        unique=True,
        name="skill_eval_policies_tenant_skill",
    )
    await db[RUNS_COLLECTION].create_index(
        [("tenant_id", 1), ("skill_id", 1), ("created_at", -1)],
        name="skill_eval_runs_tenant_skill_time",
    )