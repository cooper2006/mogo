"""032-eval-gate: golden test-set CRUD (tenant-isolated).

``(tenant_id, skill_id)`` is the isolation key (US1 / FR-001).  Cases carry an
optional ``agent_tag`` for grouping only — the tag does not change the gate
decision semantics (spec US1 acceptance 4).

No test set UI in phase 1 (Non-Goal); the publish dialog only displays reports
and offers a dry-run trigger.  Test sets are maintained over this API.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from app.core.db import get_db

from .models import CASES_COLLECTION, DEFAULT_MAX_CASES, DEFAULT_MIN_CASES


def now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class EvalCaseLimitError(ValueError):
    def __init__(self, message: str, *, limit: int) -> None:
        super().__init__(message)
        self.limit = limit


class EvalCaseNotFoundError(LookupError):
    pass


class EvalCaseValidationError(ValueError):
    pass


class SkillNotFoundError(LookupError):
    pass


async def _require_skill(tenant_id: str, skill_id: str) -> None:
    skill = await get_db().skills.find_one({"_id": skill_id, "tenant_id": tenant_id}, {"_id": 1})
    if skill is None:
        raise SkillNotFoundError("技能不存在")


async def count_cases(*, tenant_id: str, skill_id: str) -> int:
    return int(await get_db()[CASES_COLLECTION].count_documents({"tenant_id": tenant_id, "skill_id": skill_id}))


async def list_cases(*, tenant_id: str, skill_id: str, agent_tag: str | None = None) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"tenant_id": tenant_id, "skill_id": skill_id}
    if agent_tag:
        query["agent_tag"] = agent_tag
    rows = await get_db()[CASES_COLLECTION].find(query).sort("created_at", 1).to_list(length=10000)
    return [view(row) for row in rows]


async def get_case(*, tenant_id: str, skill_id: str, case_id: str) -> dict[str, Any]:
    row = await get_db()[CASES_COLLECTION].find_one({"_id": case_id, "tenant_id": tenant_id, "skill_id": skill_id})
    if row is None:
        raise EvalCaseNotFoundError("用例不存在")
    return view(row)


async def create_case(*, tenant_id: str, skill_id: str, payload: dict[str, Any], max_cases: int = DEFAULT_MAX_CASES) -> dict[str, Any]:
    await _require_skill(tenant_id, skill_id)
    data = _validate(payload)
    if await count_cases(tenant_id=tenant_id, skill_id=skill_id) >= int(max_cases or DEFAULT_MAX_CASES):
        raise EvalCaseLimitError(f"测试集用例数已达上限 {int(max_cases or DEFAULT_MAX_CASES)}，请先删除或调整", limit=int(max_cases or DEFAULT_MAX_CASES))
    row = {"_id": uuid.uuid4().hex, "tenant_id": tenant_id, "skill_id": skill_id, **data, "created_at": now(), "updated_at": now()}
    await get_db()[CASES_COLLECTION].insert_one(row)
    return view(row)


async def update_case(*, tenant_id: str, skill_id: str, case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = _validate(payload)
    result = await get_db()[CASES_COLLECTION].update_one(
        {"_id": case_id, "tenant_id": tenant_id, "skill_id": skill_id},
        {"$set": {**data, "updated_at": now()}},
    )
    if result.matched_count == 0:
        raise EvalCaseNotFoundError("用例不存在")
    return await get_case(tenant_id=tenant_id, skill_id=skill_id, case_id=case_id)


async def delete_case(*, tenant_id: str, skill_id: str, case_id: str) -> dict[str, bool]:
    result = await get_db()[CASES_COLLECTION].delete_one({"_id": case_id, "tenant_id": tenant_id, "skill_id": skill_id})
    if result.deleted_count == 0:
        raise EvalCaseNotFoundError("用例不存在")
    return {"deleted": True}


def _validate(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("input") or "")
    if not text.strip():
        raise EvalCaseValidationError("input 不能为空")
    expectations = [str(item).strip() for item in (payload.get("expectations") or []) if str(item).strip()]
    expected_refs = [str(item).strip() for item in (payload.get("expected_refs") or []) if str(item).strip()]
    expect_refusal = bool(payload.get("expect_refusal"))
    if not expect_refusal and not expectations:
        # Refusal cases need no expectations; ordinary cases do.
        raise EvalCaseValidationError("expectations 不能为空（应拒答用例除外）")
    return {
        "agent_tag": str(payload.get("agent_tag") or "").strip(),
        "input": text,
        "expectations": expectations,
        "expected_refs": expected_refs,
        "expect_refusal": expect_refusal,
    }


def view(row: dict[str, Any]) -> dict[str, Any]:
    created = row.get("created_at")
    updated = row.get("updated_at")
    return {
        "id": str(row.get("_id") or ""),
        "agentTag": str(row.get("agent_tag") or ""),
        "input": str(row.get("input") or ""),
        "expectations": list(row.get("expectations") or []),
        "expectedRefs": list(row.get("expected_refs") or []),
        "expectRefusal": bool(row.get("expect_refusal")),
        "createdAt": created.isoformat() if isinstance(created, datetime.datetime) else "",
        "updatedAt": updated.isoformat() if isinstance(updated, datetime.datetime) else "",
    }