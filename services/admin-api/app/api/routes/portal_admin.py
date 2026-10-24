"""统一门户 —— 管理侧接口（037 FR-002 / FR-008 / FR-009 / FR-013 / FR-014）。

契约（admin-api，管理员会话）：

* ``GET    /api/portal/listings``                            已上架清单（管理端列表）
* ``POST   /api/portal/listings``                            上架（owner 或 ``portal:manage``）
* ``DELETE /api/portal/listings/{asset_type}/{asset_key}``   下架（owner 或 ``portal:manage``）
* ``GET    /api/portal/approvals``                           审批队列（默认 applied）
* ``POST   /api/portal/approvals/{request_id}/decide``       批准 / 拒绝
* ``POST   /api/portal/requests/{request_id}/revoke``        回收已开通授权

与 chat-api 侧的分工：终端用户的浏览 / 申领在 chat-api ``/api/portal/*``
（``services/chat-api/app/api/endpoints/portal.py``），本模块只做上架与审批。

**跨服务字段契约**（两个服务共享同一 MongoDB，chat-api 侧
``services/chat-api/app/services/portal/requests.py`` 是同一状态机的另一实现）：

* ``portal_requests``：``{tenant_id, request_id, requester_id, asset_type, asset_key,
  reason, status, approver_id, applied_at, decided_at, decided_reason, granted_at,
  expires_at?, revoked_at, revoked_by, revoke_reason}``，
  ``status ∈ {applied, approved, rejected, granted, revoked, expired}``；
* ``portal_listings``：``{tenant_id, asset_type, asset_key, category, published_by,
  published_at, unpublished_at?}``（``unpublished_at`` 为空 = 已上架）；
* 开通 = ``permission_grants`` 用户级记录 ``{tenant_id, level: "user", org_id: "",
  user_id, code: "asset:use:<asset_key>", granted_by, granted_at}``（001 契约）。

``tests/test_portal_admin.py`` 把这些字段锁成契约测试，防止两个服务漂移。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.core.db import get_db
from app.governance.rbac_model import has_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portal", tags=["portal"])

PORTAL_LISTINGS_COLLECTION = "portal_listings"
PORTAL_REQUESTS_COLLECTION = "portal_requests"
PERMISSION_GRANTS_COLLECTION = "permission_grants"
GATE_EVENTS_COLLECTION = "gate_events"
PORTAL_SETTINGS_COLLECTION = "portal_settings"

STATUS_APPLIED = "applied"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_GRANTED = "granted"
STATUS_REVOKED = "revoked"
STATUS_EXPIRED = "expired"
PORTAL_STATUSES = (STATUS_APPLIED, STATUS_APPROVED, STATUS_REJECTED, STATUS_GRANTED, STATUS_REVOKED, STATUS_EXPIRED)
#: 审批队列里可见的状态（待办）。
QUEUE_STATUSES = (STATUS_APPLIED, STATUS_APPROVED)

CATALOG_ASSET_TYPES = ("skill", "capability_asset")

PORTAL_READ = "portal:read"
PORTAL_MANAGE = "portal:manage"
PORTAL_APPROVE = "portal:approve"

#: 平台级角色 → 全量权限码（与 001 ``full_access_admin`` 同口径）。
_ALL_CODES_ROLES = frozenset({"平台管理员", "超级管理员", "full_access_admin"})

#: 所有已认证管理员都有的只读基线。
_BASELINE_CODES = frozenset({PORTAL_READ})

DEFAULT_GRANT_TTL_DAYS = 0


# --- RBAC（fail-closed） -----------------------------------------------------


def _admin_codes(user: dict[str, Any]) -> set[str]:
    role = str(user.get("role_name") or "")
    if role in _ALL_CODES_ROLES:
        return {"*"}
    codes = set(_BASELINE_CODES)
    for code in user.get("permission_codes") or ():
        code = str(code or "")
        if code:
            codes.add(code)
    return codes


def _require(user: dict[str, Any], code: str) -> None:
    if not has_permission(_admin_codes(user), code):
        raise HTTPException(status_code=403, detail=f"missing permission: {code}")


def _tenant_id(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or "default")


def _actor(user: dict[str, Any]) -> str:
    return str(user.get("username") or user.get("display_name") or "")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _db() -> Any:
    return get_db()


# --- 资产 / 上架辅助 ---------------------------------------------------------


async def _asset_row(db: Any, tenant_id: str, asset_type: str, asset_key: str) -> dict[str, Any] | None:
    """读取资产文档（跨租户一律不可见）。"""
    if asset_type == "capability_asset":
        row = await db["capability_assets"].find_one({"asset_id": asset_key})
    elif asset_type == "skill":
        row = await db.skills.find_one({"_id": asset_key, "tenant_id": tenant_id})
    else:
        return None
    if not row:
        return None
    row_tenant = str(row.get("tenant_id") or "")
    if row_tenant and row_tenant != tenant_id:
        return None
    return row


def _is_active_asset(row: dict[str, Any], asset_type: str) -> bool:
    """与 chat-api ``services/portal/listings.py:is_active_asset`` 同口径。"""
    if not row:
        return False
    if asset_type == "capability_asset":
        return str(row.get("state") or "") == "active"
    if asset_type == "skill":
        if str(row.get("authoring_mode") or "") == "platform":
            return str(row.get("publication_status") or "") == "published"
        return True
    return False


def _asset_owner(row: dict[str, Any]) -> str:
    for field in ("created_by", "owner_id", "owner"):
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return ""


def _can_manage_asset(user: dict[str, Any], row: dict[str, Any]) -> bool:
    """资产 owner 或持 ``portal:manage`` 的管理员可上 / 下架。"""
    if has_permission(_admin_codes(user), PORTAL_MANAGE):
        return True
    actor = _actor(user)
    return bool(actor) and _asset_owner(row) == actor


async def _audit(
    db: Any,
    *,
    tenant_id: str,
    actor: str,
    action: str,
    decision: str = "allow",
    detail: dict[str, Any] | None = None,
) -> None:
    """写 gate_events 审计（与 001 单一审计汇同 schema；失败不阻断）。"""
    try:
        await db[GATE_EVENTS_COLLECTION].insert_one(
            {
                "event_id": uuid.uuid4().hex,
                "occurred_at": _now(),
                "tenant_id": tenant_id,
                "user_id": actor,
                "roles": [],
                "tool": f"portal.{action}",
                "risk_level": "",
                "autonomy_level": "",
                "decision": decision,
                "layer": "portal",
                "reason": f"portal {action}",
                "detail": detail or {},
            }
        )
    except Exception as exc:  # pragma: no cover - 审计不可用时不阻断主流程
        # 审计是治理证据链，静默丢弃等于证据链断口；至少留一条 warning 让缺口可发现。
        logger.warning("portal audit write failed (%s %s): %s", action, decision, exc)


# --- 授权开通 / 回收（共用契约）---------------------------------------------


def build_asset_use_code(asset_key: str) -> str:
    return f"asset:use:{asset_key}"


async def _grant_asset_use(
    db: Any, *, tenant_id: str, user_id: str, asset_key: str, granted_by: str
) -> dict[str, Any]:
    code = build_asset_use_code(asset_key)
    document = {
        "tenant_id": tenant_id,
        "level": "user",
        "org_id": "",
        "user_id": user_id,
        "code": code,
        "granted_by": granted_by,
        "granted_at": _now(),
    }
    await db[PERMISSION_GRANTS_COLLECTION].update_one(
        {"tenant_id": tenant_id, "level": "user", "org_id": "", "user_id": user_id, "code": code},
        {"$set": document},
        upsert=True,
    )
    return document


async def _revoke_asset_use(db: Any, *, tenant_id: str, user_id: str, asset_key: str) -> bool:
    result = await db[PERMISSION_GRANTS_COLLECTION].delete_one(
        {
            "tenant_id": tenant_id,
            "level": "user",
            "org_id": "",
            "user_id": user_id,
            "code": build_asset_use_code(asset_key),
        }
    )
    return bool(getattr(result, "deleted_count", 0))


async def _grant_ttl_days(db: Any, tenant_id: str) -> int:
    try:
        row = await db[PORTAL_SETTINGS_COLLECTION].find_one({"tenant_id": tenant_id})
    except Exception:
        return DEFAULT_GRANT_TTL_DAYS
    try:
        return max(int((row or {}).get("grant_ttl_days") or 0), 0)
    except (TypeError, ValueError):
        return DEFAULT_GRANT_TTL_DAYS


async def _transition(
    db: Any,
    *,
    tenant_id: str,
    request_id: str,
    from_status: str,
    to_status: str,
    updates: dict[str, Any] | None = None,
) -> int:
    payload: dict[str, Any] = {"status": to_status}
    payload.update(updates or {})
    result = await db[PORTAL_REQUESTS_COLLECTION].update_one(
        {"tenant_id": tenant_id, "request_id": request_id, "status": from_status},
        {"$set": payload},
    )
    return int(getattr(result, "modified_count", 0) or 0)


# --- request models ---------------------------------------------------------


class PublishPayload(BaseModel):
    asset_type: str = Field(..., max_length=64)
    asset_key: str = Field(..., min_length=1, max_length=256)
    category: str = Field(default="", max_length=64)


class DecidePayload(BaseModel):
    approved: bool
    reason: str = Field(default="", max_length=500)


class RevokePayload(BaseModel):
    reason: str = Field(default="", max_length=500)


def _serialize_listing(row: dict[str, Any]) -> dict[str, Any]:
    unpublished_at = row.get("unpublished_at")
    return {
        "asset_type": row.get("asset_type"),
        "asset_key": row.get("asset_key"),
        "category": row.get("category") or "uncategorized",
        "published_by": row.get("published_by") or "",
        "published_at": row.get("published_at"),
        "unpublished_at": unpublished_at,
        "published": not bool(unpublished_at),
    }


def _serialize_request(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": row.get("request_id"),
        "requester_id": row.get("requester_id") or "",
        "asset_type": row.get("asset_type"),
        "asset_key": row.get("asset_key"),
        "reason": row.get("reason") or "",
        "status": row.get("status"),
        "approver_id": row.get("approver_id") or "",
        "applied_at": row.get("applied_at"),
        "decided_at": row.get("decided_at"),
        "decided_reason": row.get("decided_reason") or "",
        "granted_at": row.get("granted_at"),
        "expires_at": row.get("expires_at"),
        "revoked_at": row.get("revoked_at"),
    }


# --- 上架 / 下架 -------------------------------------------------------------


@router.get("/listings")
async def list_listings(
    published_only: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
    user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """已上架清单（``published_only=false`` 时含已下架记录，便于管理端审计）。"""
    _require(user, PORTAL_READ)
    db = _db()
    tenant_id = _tenant_id(user)
    query: dict[str, Any] = {"tenant_id": tenant_id}
    if published_only:
        query["$or"] = [{"unpublished_at": None}, {"unpublished_at": {"$exists": False}}]
    rows = await db[PORTAL_LISTINGS_COLLECTION].find(query).to_list(length=limit)
    rows.sort(key=lambda r: str(r.get("published_at") or ""), reverse=True)
    items: list[dict[str, Any]] = []
    for row in rows:
        item = _serialize_listing(row)
        asset = await _asset_row(db, tenant_id, str(row.get("asset_type") or ""), str(row.get("asset_key") or ""))
        item["name"] = str((asset or {}).get("name") or row.get("asset_key") or "")
        item["is_active_asset"] = _is_active_asset(asset or {}, str(row.get("asset_type") or ""))
        items.append(item)
    return {"items": items, "total": len(items)}


@router.post("/listings", status_code=201)
async def publish_listing(
    payload: PublishPayload,
    user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """上架（即时生效；重复上架幂等覆盖分类，但保留首次 ``published_at``）。"""
    _require(user, PORTAL_READ)
    if payload.asset_type not in CATALOG_ASSET_TYPES:
        raise HTTPException(status_code=400, detail="unsupported_asset_type")
    db = _db()
    tenant_id = _tenant_id(user)
    asset_key = str(payload.asset_key or "").strip()
    row = await _asset_row(db, tenant_id, payload.asset_type, asset_key)
    if not row:
        raise HTTPException(status_code=404, detail="asset_not_found")
    if not _is_active_asset(row, payload.asset_type):
        raise HTTPException(status_code=409, detail="asset_not_active")
    if not _can_manage_asset(user, row):
        raise HTTPException(status_code=403, detail="forbidden")

    existing = await db[PORTAL_LISTINGS_COLLECTION].find_one(
        {"tenant_id": tenant_id, "asset_type": payload.asset_type, "asset_key": asset_key}
    )
    document = {
        "tenant_id": tenant_id,
        "asset_type": payload.asset_type,
        "asset_key": asset_key,
        "category": str(payload.category or "").strip() or "uncategorized",
        "published_by": _actor(user),
        "published_at": (existing or {}).get("published_at") or _now(),
    }
    await db[PORTAL_LISTINGS_COLLECTION].update_one(
        {"tenant_id": tenant_id, "asset_type": payload.asset_type, "asset_key": asset_key},
        {"$set": document, "$unset": {"unpublished_at": ""}},
        upsert=True,
    )
    await _audit(
        db,
        tenant_id=tenant_id,
        actor=_actor(user),
        action="listing.publish",
        detail={"asset_type": payload.asset_type, "asset_key": asset_key, "category": document["category"]},
    )
    return {"listing": _serialize_listing({**document, "unpublished_at": None}), "published": True}


@router.delete("/listings/{asset_type}/{asset_key}")
async def unpublish_listing(
    asset_type: str,
    asset_key: str,
    user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """下架（即时生效；**不撤销**存量授权，spec 边界）。"""
    _require(user, PORTAL_READ)
    db = _db()
    tenant_id = _tenant_id(user)
    row = await _asset_row(db, tenant_id, asset_type, asset_key)
    if row and not _can_manage_asset(user, row):
        raise HTTPException(status_code=403, detail="forbidden")
    if not row and not has_permission(_admin_codes(user), PORTAL_MANAGE):
        raise HTTPException(status_code=403, detail="forbidden")

    result = await db[PORTAL_LISTINGS_COLLECTION].update_one(
        {
            "tenant_id": tenant_id,
            "asset_type": asset_type,
            "asset_key": asset_key,
            "$or": [{"unpublished_at": None}, {"unpublished_at": {"$exists": False}}],
        },
        {"$set": {"unpublished_at": _now(), "unpublished_by": _actor(user)}},
    )
    if not int(getattr(result, "modified_count", 0) or 0):
        raise HTTPException(status_code=404, detail="listing_not_found")
    await _audit(
        db,
        tenant_id=tenant_id,
        actor=_actor(user),
        action="listing.unpublish",
        decision="deny",
        detail={"asset_type": asset_type, "asset_key": asset_key},
    )
    return {"unpublished": True, "asset_type": asset_type, "asset_key": asset_key}


# --- 审批队列 ----------------------------------------------------------------


@router.get("/approvals")
async def list_approvals(
    status: str = Query(default=STATUS_APPLIED),
    limit: int = Query(default=100, ge=1, le=500),
    user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """审批队列（默认只看待审 ``applied``；``status=all`` 看全部在途）。"""
    _require(user, PORTAL_READ)
    db = _db()
    tenant_id = _tenant_id(user)
    query: dict[str, Any] = {"tenant_id": tenant_id}
    if status and status != "all":
        if status not in PORTAL_STATUSES:
            raise HTTPException(status_code=400, detail="invalid_status")
        query["status"] = status
    rows = await db[PORTAL_REQUESTS_COLLECTION].find(query).to_list(length=limit)
    rows.sort(key=lambda r: str(r.get("applied_at") or ""), reverse=True)
    items: list[dict[str, Any]] = []
    for row in rows:
        item = _serialize_request(row)
        asset = await _asset_row(db, tenant_id, str(row.get("asset_type") or ""), str(row.get("asset_key") or ""))
        item["asset_name"] = str((asset or {}).get("name") or row.get("asset_key") or "")
        item["can_decide"] = (
            str(row.get("status") or "") == STATUS_APPLIED
            and str(row.get("requester_id") or "") != _actor(user)
            and has_permission(_admin_codes(user), PORTAL_APPROVE)
        )
        items.append(item)
    return {"items": items, "total": len(items)}


@router.post("/approvals/{request_id}/decide")
async def decide_approval(
    request_id: str,
    payload: DecidePayload,
    user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """批准（→ 开通，写用户级 ``asset:use:<key>``）/ 拒绝。"""
    _require(user, PORTAL_APPROVE)
    db = _db()
    tenant_id = _tenant_id(user)
    actor = _actor(user)
    row = await db[PORTAL_REQUESTS_COLLECTION].find_one(
        {"tenant_id": tenant_id, "request_id": str(request_id or "").strip()}
    )
    if not row:
        raise HTTPException(status_code=404, detail="request_not_found")
    if actor and actor == str(row.get("requester_id") or ""):
        # 防自审（001 审计教训）：申请人不得审批自己的单。
        raise HTTPException(status_code=403, detail="self_approval_forbidden")

    current = str(row.get("status") or "")
    if current != STATUS_APPLIED:
        # 并发双审批 / 已处理：不重复开通，返回当前状态。
        return {"status": current, "changed": False, "request": _serialize_request(row)}

    decided_at = _now()
    if not payload.approved:
        modified = await _transition(
            db,
            tenant_id=tenant_id,
            request_id=row["request_id"],
            from_status=STATUS_APPLIED,
            to_status=STATUS_REJECTED,
            updates={"approver_id": actor, "decided_at": decided_at, "decided_reason": payload.reason},
        )
        if not modified:
            latest = await db[PORTAL_REQUESTS_COLLECTION].find_one(
                {"tenant_id": tenant_id, "request_id": row["request_id"]}
            )
            return {"status": str((latest or {}).get("status") or ""), "changed": False, "request": _serialize_request(latest or row)}
        await _audit(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="request.rejected",
            decision="deny",
            detail={"request_id": row["request_id"], "reason": payload.reason},
        )
        return {
            "status": STATUS_REJECTED,
            "changed": True,
            "request": _serialize_request({**row, "status": STATUS_REJECTED, "approver_id": actor}),
        }

    # 资产在审批窗口内下线 → 自动拒绝（spec 边界：asset offline）。
    asset = await _asset_row(db, tenant_id, str(row.get("asset_type") or ""), str(row.get("asset_key") or ""))
    if not asset or not _is_active_asset(asset, str(row.get("asset_type") or "")):
        await _transition(
            db,
            tenant_id=tenant_id,
            request_id=row["request_id"],
            from_status=STATUS_APPLIED,
            to_status=STATUS_REJECTED,
            updates={"approver_id": actor, "decided_at": decided_at, "decided_reason": "asset_offline"},
        )
        await _audit(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="request.rejected",
            decision="deny",
            detail={"request_id": row["request_id"], "reason": "asset_offline"},
        )
        return {
            "status": STATUS_REJECTED,
            "changed": True,
            "reason": "asset_offline",
            "request": _serialize_request({**row, "status": STATUS_REJECTED, "decided_reason": "asset_offline"}),
        }

    modified = await _transition(
        db,
        tenant_id=tenant_id,
        request_id=row["request_id"],
        from_status=STATUS_APPLIED,
        to_status=STATUS_APPROVED,
        updates={"approver_id": actor, "decided_at": decided_at, "decided_reason": payload.reason},
    )
    if not modified:
        latest = await db[PORTAL_REQUESTS_COLLECTION].find_one(
            {"tenant_id": tenant_id, "request_id": row["request_id"]}
        )
        return {"status": str((latest or {}).get("status") or ""), "changed": False, "request": _serialize_request(latest or row)}

    grant = await _grant_asset_use(
        db,
        tenant_id=tenant_id,
        user_id=str(row.get("requester_id") or ""),
        asset_key=str(row.get("asset_key") or ""),
        granted_by=actor,
    )
    granted_at = _now()
    ttl_days = await _grant_ttl_days(db, tenant_id)
    expires_at = granted_at + timedelta(days=ttl_days) if ttl_days > 0 else None
    grant_updates: dict[str, Any] = {"granted_at": granted_at}
    if expires_at is not None:
        grant_updates["expires_at"] = expires_at
    await _transition(
        db,
        tenant_id=tenant_id,
        request_id=row["request_id"],
        from_status=STATUS_APPROVED,
        to_status=STATUS_GRANTED,
        updates=grant_updates,
    )
    await _audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="grant.granted",
        detail={
            "request_id": row["request_id"],
            "requester_id": row.get("requester_id"),
            "code": grant["code"],
        },
    )
    granted_doc = {
        **row,
        "status": STATUS_GRANTED,
        "approver_id": actor,
        "decided_at": decided_at,
        "granted_at": granted_at,
    }
    if expires_at is not None:
        granted_doc["expires_at"] = expires_at
    return {"status": STATUS_GRANTED, "changed": True, "grant": grant["code"], "request": _serialize_request(granted_doc)}


@router.post("/requests/{request_id}/revoke")
async def revoke_request(
    request_id: str,
    payload: Optional[RevokePayload] = None,
    user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """回收已开通授权（资产 owner 或 ``portal:manage``）；删记录 = 立即失效。"""
    _require(user, PORTAL_READ)
    db = _db()
    tenant_id = _tenant_id(user)
    actor = _actor(user)
    row = await db[PORTAL_REQUESTS_COLLECTION].find_one(
        {"tenant_id": tenant_id, "request_id": str(request_id or "").strip()}
    )
    if not row:
        raise HTTPException(status_code=404, detail="request_not_found")
    asset = await _asset_row(db, tenant_id, str(row.get("asset_type") or ""), str(row.get("asset_key") or ""))
    if not _can_manage_asset(user, asset or {}):
        raise HTTPException(status_code=403, detail="forbidden")

    removed = await _revoke_asset_use(
        db,
        tenant_id=tenant_id,
        user_id=str(row.get("requester_id") or ""),
        asset_key=str(row.get("asset_key") or ""),
    )
    reason = (payload.reason if payload else "") or ""
    modified = await _transition(
        db,
        tenant_id=tenant_id,
        request_id=row["request_id"],
        from_status=STATUS_GRANTED,
        to_status=STATUS_REVOKED,
        updates={"revoked_at": _now(), "revoked_by": actor, "revoke_reason": reason},
    )
    await _audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="grant.revoked",
        decision="deny",
        detail={
            "request_id": row["request_id"],
            "user_id": row.get("requester_id"),
            "asset_type": row.get("asset_type"),
            "asset_key": row.get("asset_key"),
            "removed": removed,
            "reason": reason,
        },
    )
    return {"revoked": bool(removed or modified), "grant_removed": removed, "status": STATUS_REVOKED if modified else str(row.get("status") or "")}


# --- 索引（启动时由 app/main.py 调用）---------------------------------------


async def ensure_indexes(db: Any = None) -> None:
    """建门户索引：上架唯一键 + 申领单唯一键 + 队列 / 我的单查询索引。"""
    db = db if db is not None else get_db()
    await db[PORTAL_LISTINGS_COLLECTION].create_index(
        [("tenant_id", 1), ("asset_type", 1), ("asset_key", 1)],
        name="portal_listing_key",
        unique=True,
    )
    await db[PORTAL_REQUESTS_COLLECTION].create_index(
        [("tenant_id", 1), ("request_id", 1)], name="portal_request_key", unique=True
    )
    await db[PORTAL_REQUESTS_COLLECTION].create_index(
        [("tenant_id", 1), ("status", 1), ("applied_at", -1)], name="portal_request_queue"
    )
    await db[PORTAL_REQUESTS_COLLECTION].create_index(
        [("tenant_id", 1), ("requester_id", 1), ("applied_at", -1)], name="portal_request_mine"
    )
