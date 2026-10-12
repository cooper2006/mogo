"""Internal gatekeeper endpoint (001 US1 — employee-side enforcement).

001's six-layer chain lives in admin-api, but the tool/Skill calls that need it are
executed by chat-api on behalf of *employees*. This endpoint lets chat-api run the
real chain (implemented once here, not duplicated) over HTTP with the shared
service token.

The response carries the (possibly **redacted**) request back to the caller: the
redaction layer rewrites ``ctx.request`` in place, and chat-api must forward the
redacted body to the tool backend — otherwise PII would still reach the backend
(FR-7).
"""

from __future__ import annotations

import hmac
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.security import gatekeeper as gk
from app.governance import GateContext, gatekeeper

router = APIRouter()


#: 022 FR-12（T020）：期望的调用方服务身份。chat-api 是唯一的服务间调用方。
EXPECTED_SERVICE_ID = "chat-api"

#: 历史命名兼容：新式凭据未配置时回退到该静态共享密钥。
LEGACY_TOKEN_ENV_NAMES = ("ADMIN_BACKEND_SERVICE_TOKEN",)


def _service_token_issuer() -> Any:
    """惰性构建签发器（未配置新式凭据时返回 None → 回退静态比对）。"""
    if not hasattr(_service_token_issuer, "_cached"):
        from app.security import gatekeeper as gk

        _service_token_issuer._cached = gk.build_issuer_from_env(
            EXPECTED_SERVICE_ID,
            extra_primary_names=LEGACY_TOKEN_ENV_NAMES,
        )
    return _service_token_issuer._cached


def _require_service(
    token: str,
    *,
    tenant_id: str = "",
    user_id: str = "",
    scope: str = "",
) -> Any:
    """校验服务令牌（022 FR-12 / T020 双因子 + T028 最小权限）。

    优先使用新式签名令牌；未配置时回退到既有静态共享密钥（灰度可回滚）。
    任何失败都 fail-closed 抛 401。

    ``scope`` 非空时，令牌必须显式携带该权限码 —— 认得出调用方身份不等于
    允许它做这件事。
    """
    from app.security import gatekeeper as gk

    try:
        claim = gk.verify_service_call(
            str(token or ""),
            expected_service_id=EXPECTED_SERVICE_ID,
            tenant_id=str(tenant_id or ""),
            user_id=str(user_id or ""),
            issuer=_service_token_issuer(),
            required_scope=scope,
        )
    except gk.GatekeeperDenied as exc:
        raise HTTPException(status_code=401, detail=str(exc.reason)) from exc
    if claim is not None:
        return claim

    # 回退：既有静态共享密钥（ADMIN_BACKEND_SERVICE_TOKEN）。
    expected = str(settings.backend_service_token or "")
    if str(token or "") and expected and hmac.compare_digest(str(token), expected):
        return None
    raise HTTPException(status_code=401, detail="invalid_service_token")


class GateEvaluatePayload(BaseModel):
    tool: str = Field(..., description="Tool / Skill identifier being invoked")
    tenantId: str = Field(default="", description="Tenant (tenant_id) the caller belongs to")
    userId: str = Field(default="", description="Employee user id")
    roles: list[str] = Field(default_factory=list, description="Bound position-role ids")
    request: dict[str, Any] = Field(default_factory=dict, description="Tool request body (may be redacted)")
    sessionId: str = Field(default="", description="Kernel session id")
    scope: str = Field(default="tool")
    # 019 harness mode: "thick" (all six layers) or "thin" (identity/rbac/redaction/
    # audit only). The server enforces the floor — audit is always required — so
    # the client cannot coerce the chain into a weaker state (T999, 2026-10-03).
    harnessMode: str = Field(default="thick", description="thick | thin")
    # Resume path (FR-2): a requester re-enters with the approval ticket it was
    # handed when the call was suspended. Only an already-approved ticket passes.
    approvalToken: str = Field(default="", description="One-time approval ticket")
    approvalActionId: str = Field(default="", description="Action id the ticket belongs to")


async def _resolve_roles(tenant_id: str, user_id: str, provided: list[str]) -> list[str]:
    """Resolve the employee's real position-role ids (006) when the caller omits them.

    006 binds roles to *employees* in ``end_user_position_roles`` (``user_id`` keyed).
    Without this the RBAC layer would see an empty role set and fail closed on every
    call — the original breakage (001 audit, 2026-10-03).
    """
    if provided:
        return [str(r) for r in provided]
    if not tenant_id or not user_id:
        return []
    try:
        from app.core.db import get_db

        db = get_db()
        if db is None:
            return []
        rows = await db["end_user_position_roles"].find(
            {"tenant_id": tenant_id, "user_id": user_id}, {"role_id": 1}
        ).to_list(length=100)
        return [str(row.get("role_id") or "") for row in rows if row.get("role_id")]
    except Exception:
        return []


@router.post("/evaluate")
async def evaluate_gate(
    payload: GateEvaluatePayload,
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Run the six-layer chain and return the verdict (+ redacted request)."""
    _require_service(
        service_token,
        tenant_id=str(payload.tenantId or ""),
        user_id=str(payload.userId or ""),
        scope=gk.SCOPE_GATEKEEPER_EVALUATE,
    )

    roles = await _resolve_roles(
        str(payload.tenantId or ""), str(payload.userId or ""), list(payload.roles or [])
    )
    annotations: dict[str, Any] = {}
    if payload.approvalToken:
        annotations["approval_token"] = str(payload.approvalToken)
        annotations["approval_action_id"] = str(
            payload.approvalActionId or payload.sessionId or payload.tool or ""
        )
    ctx = GateContext(
        tool=str(payload.tool or ""),
        tenant_id=str(payload.tenantId or ""),
        user_id=str(payload.userId or ""),
        roles=roles,
        request=dict(payload.request or {}),
        session_id=str(payload.sessionId or ""),
        scope=str(payload.scope or "tool"),
        annotations=annotations,
        harness_mode=str(payload.harnessMode or "thick"),
    )
    verdict = await gatekeeper.evaluate(ctx.tool, ctx)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "decision": verdict.decision.value,
            "layer": verdict.layer,
            "reason": verdict.reason,
            "statusCode": verdict.status_code,
            "detail": verdict.detail,
            "roles": roles,
            # The redaction layer rewrites ctx.request in place; hand the (possibly)
            # redacted body back so the caller never forwards plaintext PII.
            "request": ctx.request,
        },
    }


__all__ = ["router"]


class GateApprovalDecision(BaseModel):
    actionId: str = Field(..., description="Action id the suspended call was issued for")
    token: str = Field(..., description="One-time approval ticket to decide")
    approved: bool = Field(..., description="True approves, False denies")
    actor: str = Field(default="", description="Approver identity (audited)")


@router.post("/decide")
async def decide_gate_approval(
    payload: GateApprovalDecision,
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Human-approver decision on a suspended call (FR-2 / FR-11).

    Moves the ticket ``pending -> approved|denied``. The requester then re-enters
    ``/evaluate`` with the token; only an ``approved`` ticket is consumable.
    """
    _require_service(service_token, scope=gk.SCOPE_GATEKEEPER_DECIDE)

    from app.governance.layers.approval import ApprovalRegistry

    ok = await ApprovalRegistry().decide(
        action_id=str(payload.actionId or ""),
        token=str(payload.token or ""),
        approved=bool(payload.approved),
        actor=str(payload.actor or ""),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="approval_ticket_not_pending_or_expired")
    return {
        "code": 0,
        "message": "success",
        "data": {"actionId": str(payload.actionId), "status": "approved" if payload.approved else "denied"},
    }


@router.get("/approvals")
async def list_gate_approvals(
    tenantId: str = "",
    status: str = "pending",
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Approver inbox: list tickets awaiting a decision (FR-2).

    Without this the suspended calls were invisible to any approver — the ticket
    existed in ``gate_approvals`` with nobody able to see it (001 audit, 2026-10-03).
    """
    _require_service(
        service_token,
        tenant_id=str(tenantId or ""),
        scope=gk.SCOPE_GATEKEEPER_LIST_APPROVALS,
    )

    from app.core.db import get_db
    from app.governance.layers.approval import GATE_APPROVALS_COLLECTION

    db = get_db()
    query: dict[str, Any] = {}
    if tenantId:
        query["tenant_id"] = tenantId
    if status:
        query["status"] = status
    rows = (
        await db[GATE_APPROVALS_COLLECTION]
        .find(query, {"token_hash": 0})
        .sort("created_at", -1)
        .limit(200)
        .to_list(length=200)
    )
    for row in rows:
        row["_id"] = str(row.get("_id") or "")
    return {"code": 0, "message": "success", "data": {"items": rows, "count": len(rows)}}


@router.get("/events")
async def list_gate_events(
    tenantId: str = "",
    decision: str = "",
    tool: str = "",
    limit: int = 100,
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> dict[str, Any]:
    """Read the 001 audit trail (``gate_events``).

    The audit layer has always *written* every pass/reject here, but nothing could
    read it — so "audit coverage 100%" was unverifiable (001 audit, 2026-10-03).
    This is the missing consumer.
    """
    _require_service(
        service_token,
        tenant_id=str(tenantId or ""),
        scope=gk.SCOPE_GATEKEEPER_LIST_EVENTS,
    )

    from app.core.db import get_db
    from app.governance.layers.audit import GATE_EVENTS_COLLECTION

    db = get_db()
    query: dict[str, Any] = {}
    if tenantId:
        query["tenant_id"] = tenantId
    if decision:
        query["decision"] = decision
    if tool:
        query["tool"] = tool
    size = max(1, min(int(limit or 100), 500))
    rows = (
        await db[GATE_EVENTS_COLLECTION]
        .find(query, {"_id": 0})
        .sort("occurred_at", -1)
        .limit(size)
        .to_list(length=size)
    )
    for row in rows:
        occurred = row.get("occurred_at")
        if hasattr(occurred, "isoformat"):
            row["occurred_at"] = occurred.isoformat()
    return {"code": 0, "message": "success", "data": {"items": rows, "count": len(rows)}}
