"""Hook rules management API (009 T015 / US4 — declarative rule CRUD).

Exposes the ``hook_rules`` store over HTTP so operators can add / update /
disable / list PreToolUse rules without code changes (FR-4). Rule edits take
effect on the very next tool call because the admission gate re-reads the
store at call time.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.db import get_db
from app.core.tenant import resolve_main_id
from app.dsh_runtime.hooks.rules import RuleParseError
from app.dsh_runtime.hooks.store import HookRuleStore
from app.api.endpoints.auth import _resolve_session_user

router = APIRouter()


class HookRuleIn(BaseModel):
    scope: str = Field("tenant", description="Rule scope level: tool / session / tenant")
    rule_type: str = Field(..., description="deny_tool / require_field / observe")
    rule_config: dict[str, Any] = Field(default_factory=dict, description="Rule parameters")
    enabled: bool = Field(True, description="Rule is active when True")


class HookRuleOut(BaseModel):
    rule_id: str
    scope: str
    rule_type: str
    rule_config: dict[str, Any]
    enabled: bool
    tenant_id: str


class HookRuleUpdateIn(BaseModel):
    enabled: Optional[bool] = None
    rule_config: Optional[dict[str, Any]] = None
    scope: Optional[str] = None
    rule_type: Optional[str] = None


def _to_out(document: Any) -> HookRuleOut:
    return HookRuleOut(
        rule_id=document.rule_id,
        scope=document.scope,
        rule_type=document.rule_type,
        rule_config=dict(document.rule_config or {}),
        enabled=bool(document.enabled),
        tenant_id=document.tenant_id,
    )


@router.post("/hooks/rules", response_model=HookRuleOut)
async def create_hook_rule(
    payload: HookRuleIn,
    authorization: str | None = Header(default=None),
):
    resolved = await _resolve_session_user(authorization if isinstance(authorization, str) else None)
    main_id = resolve_main_id(resolved["main_id"])
    store = HookRuleStore(get_db())
    try:
        document = await store.create(
            scope=payload.scope,
            rule_type=payload.rule_type,
            rule_config=payload.rule_config,
            enabled=payload.enabled,
            tenant_id=main_id,
        )
    except RuleParseError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _to_out(document)


@router.get("/hooks/rules", response_model=list[HookRuleOut])
async def list_hook_rules(
    tenant_id: str | None = None,
    authorization: str | None = Header(default=None),
):
    resolved = await _resolve_session_user(authorization if isinstance(authorization, str) else None)
    main_id = resolve_main_id(resolved["main_id"])
    store = HookRuleStore(get_db())
    documents = await store.list(tenant_id=tenant_id or main_id)
    return [_to_out(document) for document in documents]


@router.put("/hooks/rules/{rule_id}", response_model=HookRuleOut)
async def update_hook_rule(
    rule_id: str,
    payload: HookRuleUpdateIn,
    authorization: str | None = Header(default=None),
):
    resolved = await _resolve_session_user(authorization if isinstance(authorization, str) else None)
    main_id = resolve_main_id(resolved["main_id"])
    store = HookRuleStore(get_db())
    document = await store.update(
        rule_id,
        enabled=payload.enabled,
        rule_config=payload.rule_config,
        scope=payload.scope,
        rule_type=payload.rule_type,
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Hook rule not found")
    return _to_out(document)


@router.delete("/hooks/rules/{rule_id}")
async def delete_hook_rule(
    rule_id: str,
    authorization: str | None = Header(default=None),
):
    resolved = await _resolve_session_user(authorization if isinstance(authorization, str) else None)
    resolve_main_id(resolved["main_id"])
    store = HookRuleStore(get_db())
    if not await store.delete(rule_id):
        raise HTTPException(status_code=404, detail="Hook rule not found")
    return {"deleted": rule_id}
