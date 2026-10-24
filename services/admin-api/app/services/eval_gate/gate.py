"""032-eval-gate: publish gate orchestration + audit events.

Inserted into ``skill_lifecycle.publish()`` between the version-uniqueness check
and the release insert.  Any failure (no test set, too few cases, gateway
unavailable, thresholds below policy) raises ``EvalGateBlocked`` — publish never
silently proceeds (fail-closed).

Audit events land in 001's ``gate_events`` collection with
``event_type=eval_gate.passed|blocked`` — publish is not a tool call, so we do
not hang this on the six-layer gate chain; we only reuse the same audit sink
(spec 已定决策 #8).
"""

from __future__ import annotations

import datetime
import time
import uuid
from typing import Any

from app.core.db import get_db

from .executor import GatewayError, run_evaluation
from .models import (
    CASES_COLLECTION,
    DEFAULT_MIN_CASES,
    GATE_EVENTS_COLLECTION,
    Metrics,
    RUNS_COLLECTION,
)
from .policies import get_policy
from .test_sets import count_cases


def now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class EvalGateBlocked(RuntimeError):
    """Carries the full metric + threshold detail so the API layer can surface it."""

    def __init__(self, reason: str, *, metrics: dict[str, float] | None = None,
                 thresholds: dict[str, Any] | None = None,
                 status_code: int = 409) -> None:
        super().__init__(reason)
        self.reason = reason
        self.metrics = metrics or {}
        self.thresholds = thresholds or {}
        self.status_code = status_code

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "metrics": self.metrics,
            "thresholds": self.thresholds,
        }


async def _write_audit(*, event_type: str, tenant_id: str, skill_id: str,
                       version: str, metrics: dict[str, float], thresholds: dict[str, Any],
                       verdict: str, detail: dict[str, Any]) -> str:
    event_id = uuid.uuid4().hex
    doc = {
        "event_id": event_id,
        "occurred_at": now(),
        "tenant_id": tenant_id,
        "skill_id": skill_id,
        "skill_version": version,
        "event_type": event_type,
        "decision": verdict,
        "layer": "eval_gate",
        "reason": verdict,
        "metrics": metrics,
        "thresholds": thresholds,
        "detail": detail,
    }
    # FR-008 fail-closed: a decision that cannot be audited must not silently
    # release a version — mirror 001 AuditLayer, whose write failure is a DENY.
    try:
        await get_db()[GATE_EVENTS_COLLECTION].insert_one(doc)
    except Exception as exc:  # pragma: no cover - defensive
        raise EvalGateBlocked(
            f"评测审计写入失败（fail-closed 阻断发布）：{exc}",
            metrics=metrics, thresholds=thresholds, status_code=503,
        ) from exc
    return event_id


async def _store_run(*, tenant_id: str, skill_id: str, version: str, dry_run: bool,
                     metrics: Metrics, case_results: list[Any], passed: bool,
                     blocked_reason: str, duration_ms: int,
                     thresholds: dict[str, Any]) -> dict[str, Any]:
    run = {
        "_id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "skill_id": skill_id,
        "version": version,
        "dry_run": bool(dry_run),
        "metrics": metrics.as_dict(),
        "passed": bool(passed),
        "blocked_reason": blocked_reason,
        "thresholds": thresholds,
        "case_results": [result.as_dict() if hasattr(result, "as_dict") else result for result in case_results],
        "duration_ms": duration_ms,
        "created_at": now(),
    }
    await get_db()[RUNS_COLLECTION].insert_one(run)
    return run


async def run_gate(
    *,
    tenant_id: str,
    skill_id: str,
    version: str,
    skill_draft: dict[str, Any],
    dry_run: bool = False,
    model: str | None = None,
    llm_call=None,
) -> dict[str, Any]:
    """Run the eval gate.  Raises ``EvalGateBlocked`` on any blocking condition.

    Returns the evaluation report dict on success (metrics + run id + thresholds).
    Dry runs never raise and never write a blocking audit event (决策 #10) —
    callers use them purely to preview the verdict.
    """
    db = get_db()

    async def _block(reason: str, *, metrics: dict[str, float | None],
                     status_code: int = 409) -> None:
        """Record then raise — FR-008 requires even structural blocks to audit."""
        if not dry_run:
            await _write_audit(
                event_type="eval_gate.blocked", tenant_id=tenant_id, skill_id=skill_id,
                version=version, metrics=metrics, thresholds=policy,
                verdict="blocked", detail={"reason": reason},
            )
        raise EvalGateBlocked(reason, metrics=metrics, thresholds=policy, status_code=status_code)

    policy = await get_policy(tenant_id=tenant_id, skill_id=skill_id)
    min_cases = int(policy.get("min_cases") or DEFAULT_MIN_CASES)
    timeout_seconds = float(policy.get("timeout_seconds") or 300)
    max_cases = int(policy.get("max_cases") or 50)

    total_cases = await count_cases(tenant_id=tenant_id, skill_id=skill_id)
    # FR-007: no test set or too few cases → fail-closed.
    if total_cases == 0:
        await _block("该 Skill 尚未配置评测测试集，请先创建黄金测试集再发布", metrics={})
    if total_cases < min_cases:
        await _block(f"评测样本不足：当前 {total_cases} 条用例，少于最低要求 {min_cases} 条", metrics={})
    if total_cases > max_cases:
        await _block(f"评测用例数 {total_cases} 超过上限 {max_cases}，请精简后重试", metrics={})

    cases = await db[CASES_COLLECTION].find(
        {"tenant_id": tenant_id, "skill_id": skill_id}
    ).sort("created_at", 1).to_list(length=max_cases)

    started = time.monotonic()
    try:
        case_results, metrics = await run_evaluation(
            tenant_id=tenant_id,
            cases=cases,
            skill_draft=skill_draft,
            model=model,
            timeout_seconds=timeout_seconds,
            llm_call=llm_call,
        )
    except Exception as exc:  # noqa: BLE001 - any infra failure → fail-closed
        # Persist a run record marking the failure so the dialog can explain it.
        failed_run = await _store_run(
            tenant_id=tenant_id, skill_id=skill_id, version=version, dry_run=dry_run,
            metrics=Metrics(), case_results=[], passed=False,
            blocked_reason=f"评测执行失败：{exc}", duration_ms=int((time.monotonic() - started) * 1000),
            thresholds=policy,
        )
        if not dry_run:
            await _write_audit(
                event_type="eval_gate.blocked", tenant_id=tenant_id, skill_id=skill_id,
                version=version, metrics={}, thresholds=policy, verdict="blocked",
                detail={"reason": f"评测执行失败：{exc}", "run_id": failed_run["_id"]},
            )
        raise EvalGateBlocked(
            f"评测执行失败（fail-closed 阻断发布）：{exc}",
            metrics={}, thresholds=policy, status_code=502,
        ) from exc

    duration_ms = int((time.monotonic() - started) * 1000)
    # Threshold comparison — equality passes (spec 已定决策 #11).
    failed = metrics.below(Metrics(
        citation_support=float(policy.get("min_citation_support") or 0),
        refusal_accuracy=float(policy.get("min_refusal_accuracy") or 0),
        task_success=float(policy.get("min_task_success") or 0),
    ))

    passed = not failed
    reason = "" if passed else "评测未达阈值：%s" % ", ".join(failed)

    run_doc = await _store_run(
        tenant_id=tenant_id, skill_id=skill_id, version=version, dry_run=dry_run,
        metrics=metrics, case_results=case_results, passed=passed,
        blocked_reason=reason, duration_ms=duration_ms, thresholds=policy,
    )

    if not dry_run:
        await _write_audit(
            event_type="eval_gate.passed" if passed else "eval_gate.blocked",
            tenant_id=tenant_id, skill_id=skill_id, version=version,
            metrics=metrics.as_dict(), thresholds=policy,
            verdict="passed" if passed else "blocked",
            detail={"reason": reason or "全部指标达标", "run_id": run_doc["_id"], "failed_metrics": failed},
        )

    report = {
        "runId": run_doc["_id"],
        "dryRun": bool(dry_run),
        "passed": passed,
        "metrics": metrics.as_dict(),
        "thresholds": policy,
        "failedMetrics": failed,
        "blockedReason": reason,
        "durationMs": duration_ms,
        "caseResults": [result.as_dict() for result in case_results],
        "createdAt": run_doc["created_at"].isoformat(),
    }

    if not passed and not dry_run:
        raise EvalGateBlocked(reason, metrics=metrics.as_dict(), thresholds=policy, status_code=409)
    return report