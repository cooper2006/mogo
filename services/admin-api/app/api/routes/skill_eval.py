"""032-eval-gate: admin-api routes for test sets, dry-run, reports and policy."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.core.db import get_db

from app.services import eval_gate as gate_service
from app.services.eval_gate import (
    EvalCaseLimitError,
    EvalCaseNotFoundError,
    EvalCaseValidationError,
    SkillNotFoundError,
    create_case,
    delete_case,
    get_policy,
    list_cases,
    run_gate,
    save_policy,
    update_case,
)
from app.services.eval_gate.models import RUNS_COLLECTION
from app.services.eval_gate.policies import view as policy_view


router = APIRouter()


class EvalCasePayload(BaseModel):
    input: str = Field(min_length=1, max_length=8000)
    expectations: list[str] = Field(default_factory=list, max_length=32)
    expected_refs: list[str] = Field(default_factory=list, max_length=16)
    expect_refusal: bool = False
    agent_tag: str = Field(default="", max_length=64)


class EvalPolicyPayload(BaseModel):
    min_citation_support: float | None = Field(default=None, ge=0.0, le=1.0)
    min_refusal_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    min_task_success: float | None = Field(default=None, ge=0.0, le=1.0)
    min_cases: int | None = Field(default=None, ge=1, le=1000)
    max_cases: int | None = Field(default=None, ge=1, le=1000)
    timeout_seconds: int | None = Field(default=None, ge=1, le=3600)


class DryRunPayload(BaseModel):
    model: str | None = None


# ---------------------------------------------------------------------------
# test-set CRUD
# ---------------------------------------------------------------------------


@router.get("/{skill_id}/eval/cases")
async def list_skill_cases(skill_id: str, agent_tag: str | None = None,
                           current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    return {"items": await list_cases(tenant_id=tenant_id, skill_id=str(skill_id), agent_tag=agent_tag)}


@router.post("/{skill_id}/eval/cases", status_code=201)
async def create_skill_case(skill_id: str, payload: EvalCasePayload,
                            current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    policy = await get_policy(tenant_id=tenant_id, skill_id=str(skill_id))
    try:
        row = await create_case(
            tenant_id=tenant_id, skill_id=str(skill_id),
            payload=payload.model_dump(),
            max_cases=int(policy.get("max_cases") or 50),
        )
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvalCaseValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EvalCaseLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return row


@router.put("/{skill_id}/eval/cases/{case_id}")
async def update_skill_case(skill_id: str, case_id: str, payload: EvalCasePayload,
                            current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    try:
        return await update_case(
            tenant_id=tenant_id, skill_id=str(skill_id), case_id=str(case_id),
            payload=payload.model_dump(),
        )
    except EvalCaseValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EvalCaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{skill_id}/eval/cases/{case_id}")
async def delete_skill_case(skill_id: str, case_id: str,
                            current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    try:
        return await delete_case(tenant_id=tenant_id, skill_id=str(skill_id), case_id=str(case_id))
    except EvalCaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# dry-run + recent report
# ---------------------------------------------------------------------------


@router.post("/{skill_id}/eval/dry-run")
async def dry_run_eval(skill_id: str, payload: DryRunPayload,
                       current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    skill = await get_db().skills.find_one({"_id": str(skill_id), "tenant_id": tenant_id})
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    draft = dict(skill.get("draft") or skill)
    try:
        return await run_gate(
            tenant_id=tenant_id, skill_id=str(skill_id), version="dry-run",
            skill_draft=draft, dry_run=True, model=payload.model,
        )
    except gate_service.EvalGateBlocked as exc:
        # dry-run also returns the blocked report (no blocking audit written).
        return {
            "runId": None,
            "dryRun": True,
            "passed": False,
            "metrics": exc.metrics,
            "thresholds": exc.thresholds,
            "failedMetrics": [],
            "blockedReason": exc.reason,
            "durationMs": 0,
            "caseResults": [],
            "createdAt": "",
        }


@router.get("/{skill_id}/eval/reports")
async def list_reports(skill_id: str, limit: int = 5,
                       current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    size = min(max(limit, 1), 20)
    rows = await get_db()[RUNS_COLLECTION].find(
        {"tenant_id": tenant_id, "skill_id": str(skill_id)}
    ).sort("created_at", -1).limit(size).to_list(length=size)
    return {"items": [_report_view(row) for row in rows]}


@router.get("/{skill_id}/eval/reports/latest")
async def latest_report(skill_id: str,
                        current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    row = await get_db()[RUNS_COLLECTION].find_one(
        {"tenant_id": tenant_id, "skill_id": str(skill_id)},
        sort=[("created_at", -1)],
    )
    if row is None:
        raise HTTPException(status_code=404, detail="暂无评测报告")
    return _report_view(row)


# ---------------------------------------------------------------------------
# policy
# ---------------------------------------------------------------------------


@router.get("/{skill_id}/eval/policy")
async def read_policy(skill_id: str, current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    policy = await get_policy(tenant_id=tenant_id, skill_id=str(skill_id))
    return policy_view(policy)


@router.put("/{skill_id}/eval/policy")
async def write_policy(skill_id: str, payload: EvalPolicyPayload,
                       current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    try:
        policy = await save_policy(
            tenant_id=tenant_id, skill_id=str(skill_id),
            payload=payload.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return policy_view(policy)


def _report_view(row: dict[str, Any]) -> dict[str, Any]:
    created = row.get("created_at")
    return {
        "id": str(row.get("_id") or ""),
        "dryRun": bool(row.get("dry_run")),
        "passed": bool(row.get("passed")),
        "metrics": row.get("metrics") or {},
        "thresholds": row.get("thresholds") or {},
        "failedMetrics": row.get("failed_metrics") or [],
        "blockedReason": str(row.get("blocked_reason") or ""),
        "durationMs": int(row.get("duration_ms") or 0),
        "caseResults": list(row.get("case_results") or []),
        "createdAt": created.isoformat() if hasattr(created, "isoformat") else str(created or ""),
    }