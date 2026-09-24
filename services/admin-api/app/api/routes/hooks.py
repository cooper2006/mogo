"""Admin hook_rules CRUD + scope query (009 T015-T016).

Declarative hook rules are managed here: create / read / update / delete,
instant effect (the PreToolUse engine reads the latest at call time), and a
three-level scope query (tool > session > tenant).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_admin_user
from app.core.db import get_db
from app.services.hooks_store import HOOK_RULES_COLLECTION, HookRuleStore, RuleValidationError

router = APIRouter(prefix="/api/hooks", tags=["hooks"])


def _store(current_user: dict[str, Any] = Depends(get_current_admin_user)) -> HookRuleStore:
    tenant_id = str(current_user.get("main_id") or "default")
    db = get_db()
    return HookRuleStore(db=db if db is not None else None)


@router.get("/rules")
async def list_rules(
    scope: str = Query(default=""),
    enabled: Optional[bool] = Query(default=None),
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    tenant_id = str(current_user.get("main_id") or "default")
    store = _store(current_user)
    rows = store.list(tenant_id=tenant_id)
    documents = [r.as_document() for r in rows]
    if scope:
        documents = [d for d in documents if d["scope"] == scope]
    if enabled is not None:
        documents = [d for d in documents if d["enabled"] is enabled]
    return {"items": documents, "total": len(documents)}


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: str, current_user: dict[str, Any] = Depends(get_current_admin_user)) -> dict[str, Any]:
    store = _store(current_user)
    document = store.get(rule_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="hook rule not found")
    return document.as_document()


@router.post("/rules", status_code=status.HTTP_201_CREATED)
async def create_rule(payload: dict[str, Any], current_user: dict[str, Any] = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = str(current_user.get("main_id") or "default")
    store = _store(current_user)
    try:
        document = store.create(
            scope=str(payload.get("scope") or ""),
            rule_type=str(payload.get("rule_type") or ""),
            rule_config=payload.get("rule_config") or {},
            enabled=bool(payload.get("enabled", True)),
            tenant_id=tenant_id,
        )
    except RuleValidationError as error:
        # Fail-closed on an invalid rule (FR-11): reject, don't persist.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid hook rule: {error}")
    except Exception as error:  # noqa: BLE001 — any other shape error also 400
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid hook rule: {error}")
    return document.as_document()


@router.patch("/rules/{rule_id}")
async def update_rule(
    rule_id: str, payload: dict[str, Any], current_user: dict[str, Any] = Depends(get_current_admin_user)
) -> dict[str, Any]:
    store = _store(current_user)
    document = store.update(
        rule_id,
        enabled=payload.get("enabled"),
        rule_config=payload.get("rule_config"),
        scope=payload.get("scope"),
        rule_type=payload.get("rule_type"),
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="hook rule not found")
    return document.as_document()


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: str, current_user: dict[str, Any] = Depends(get_current_admin_user)) -> None:
    store = _store(current_user)
    if not store.delete(rule_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="hook rule not found")


@router.get("/scope")
async def query_scope(
    tool: str = Query(default=""),
    session_id: str = Query(default=""),
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """T016 — rules matching the three-level context (tool > session > tenant)."""
    tenant_id = str(current_user.get("main_id") or "default")
    store = _store(current_user)
    in_scope = store.ordered_rules_for(tool=tool, session_id=session_id, tenant_id=tenant_id)
    return {
        "tool": tool,
        "session_id": session_id,
        "tenant_id": tenant_id,
        "rules": [
            {"scope": r.scope, "rule_type": r.rule_type, "rule_config": dict(r.rule_config), "enabled": r.enabled}
            for r in in_scope
        ],
    }


__all__ = ["router"]
