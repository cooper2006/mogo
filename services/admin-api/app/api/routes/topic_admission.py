from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_admin_user
from app.topic_admission.models import TopicChangesPayload, TopicDraftTestPayload, TopicPolicyPayload, TopicTestPayload
from app.topic_admission.rules import get_summary, preview_changes, save_changes, search_rules
from app.topic_admission.service import get_policy, preview, save_policy


router = APIRouter()


def _tenant_id(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or "default")


@router.get("")
async def read_policy(current_user: dict[str, Any] = Depends(get_current_admin_user)) -> dict[str, Any]:
    return await get_policy(_tenant_id(current_user))


@router.get("/summary")
async def read_summary(current_user: dict[str, Any] = Depends(get_current_admin_user)) -> dict[str, Any]:
    return await get_summary(_tenant_id(current_user))


@router.get("/rules")
async def read_rules(
    q: str = Query(default="", max_length=80),
    status: str = Query(default="all", pattern="^(all|enabled|disabled)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50, alias="pageSize"),
    offset: int | None = Query(default=None, ge=0),
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    return await search_rules(_tenant_id(current_user), q, status, page, page_size, offset)


@router.put("/changes")
async def write_changes(
    payload: TopicChangesPayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    return await save_changes(_tenant_id(current_user), str(current_user.get("username") or "admin"), payload)


@router.post("/preview")
async def preview_draft(
    payload: TopicDraftTestPayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    return await preview_changes(_tenant_id(current_user), payload.text, payload)


@router.put("")
async def write_policy(
    payload: TopicPolicyPayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    return await save_policy(_tenant_id(current_user), str(current_user.get("username") or "admin"), payload)


@router.post("/test")
async def test_policy(
    payload: TopicTestPayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    return preview(payload.text, payload.policy)
