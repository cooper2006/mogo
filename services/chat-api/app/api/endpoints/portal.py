"""统一门户 —— 终端用户侧接口（037 FR-001 / FR-003 / FR-011 / FR-012）。

契约（全部走 chat-api 既有 ``/askai-api`` 前缀 + ``end_user`` 会话鉴权）：

* ``GET  /api/portal/catalog``                              目录列表（分类 / 关键词 / 分页）
* ``GET  /api/portal/catalog/categories``                   目录分类
* ``GET  /api/portal/catalog/{asset_type}/{asset_key}``     资产详情 + 我的申领状态
* ``GET  /api/portal/requests/mine``                        我的申领单
* ``POST /api/portal/requests``                             提交申领
* ``POST /api/portal/requests/{request_id}/revoke``         回收（申请人本人或资产 owner）

租户隔离：``tenant_id`` 一律取自 ``end_user`` 会话（``ApiPrincipal.tenant_id``），
请求体/查询串里的 ``tenantId`` 由 ``_assert_end_user_scope`` 交叉校验，不接受外部指定。
管理侧（上架 / 审批队列 / 批准拒绝）在 admin-api ``/api/portal/*``，见
``services/admin-api/app/api/routes/portal_admin.py``。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.principal import ApiPrincipal, require_end_user_principal
from app.core.db import get_db
from app.services.portal import CATALOG_ASSET_TYPES
from app.services.portal import listings as portal_listings
from app.services.portal import requests as portal_requests

router = APIRouter(prefix="/api/v1/portal", dependencies=[Depends(require_end_user_principal)])

#: 领域错误 → HTTP 状态码（fail-closed：未知错误一律 400）。
_ERROR_STATUS: dict[str, int] = {
    "asset_not_published": 404,
    "asset_not_available": 404,
    "asset_not_found": 404,
    "request_not_found": 404,
    "approver_unresolved": 409,
    "self_approval_forbidden": 403,
    "forbidden": 403,
    "unsupported_asset_type": 400,
    "invalid_status": 400,
    "asset_key_required": 400,
    "requester_required": 400,
    "approver_required": 400,
}


def _raise(exc: portal_requests.PortalRequestError) -> None:
    raise HTTPException(status_code=_ERROR_STATUS.get(exc.reason, 400), detail=exc.reason) from exc


def _db() -> Any:
    return get_db()


def _serialize(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """申领单投影（详情 / 申领返回用；字段与列表口径一致）。"""
    if not row:
        return None
    return {
        "request_id": row.get("request_id"),
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
        "is_terminal": str(row.get("status") or "") in portal_requests.STATUS_TERMINAL,
    }


@router.get("/catalog")
async def get_catalog(
    principal: ApiPrincipal = Depends(require_end_user_principal),
    category: str = Query(default=""),
    keyword: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=portal_listings.MAX_PAGE_SIZE),
) -> dict[str, Any]:
    """目录列表：本租户已上架且 active 的资产。"""
    db = _db()
    return await portal_listings.list_catalog(
        principal.tenant_id,
        category=category,
        keyword=keyword,
        page=page,
        page_size=page_size,
        db=db,
    )


@router.get("/catalog/categories")
async def get_catalog_categories(
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, Any]:
    """目录分类（来自已上架标记）。"""
    db = _db()
    return {"items": await portal_listings.list_categories(principal.tenant_id, db=db)}


@router.get("/catalog/{asset_type}/{asset_key}")
async def get_catalog_detail(
    asset_type: str,
    asset_key: str,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, Any]:
    """资产详情 + 我的申领状态（未上架 / 不 active 一律 404，不泄露存在性）。"""
    if asset_type not in CATALOG_ASSET_TYPES:
        raise HTTPException(status_code=400, detail="unsupported_asset_type")
    db = _db()
    key = portal_listings.normalize_asset_key(asset_key)
    listing = await portal_listings.find_listing(principal.tenant_id, asset_type, key, db=db)
    basic = await portal_listings.get_asset_basics(principal.tenant_id, asset_type, key, db=db)
    if not listing or not basic:
        raise HTTPException(status_code=404, detail="asset_not_found")
    state = await portal_requests.get_my_request_state(
        db,
        tenant_id=principal.tenant_id,
        requester_id=principal.user_id,
        asset_type=asset_type,
        asset_key=key,
    )
    return {
        "item": {
            **basic,
            "category": str(listing.get("category") or basic.get("category") or "uncategorized"),
            "published_at": listing.get("published_at"),
        },
        "my_request": _serialize(state.get("request")),
        "granted": bool(state.get("granted")),
    }


@router.get("/requests/mine")
async def get_my_requests(
    principal: ApiPrincipal = Depends(require_end_user_principal),
    status: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=portal_requests.MAX_PAGE_SIZE),
) -> dict[str, Any]:
    """我的申领单（读取时惰性过期，返回带终态标注）。"""
    db = _db()
    try:
        return await portal_requests.list_my_requests(
            db,
            tenant_id=principal.tenant_id,
            requester_id=principal.user_id,
            status=status,
            page=page,
            page_size=page_size,
        )
    except portal_requests.PortalRequestError as exc:
        _raise(exc)


@router.post("/requests", status_code=201)
async def create_request(
    principal: ApiPrincipal = Depends(require_end_user_principal),
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """提交申领（幂等：已开通返回 ``already_granted``，待审返回 ``pending``）。"""
    db = _db()
    asset_type = str(payload.get("asset_type") or payload.get("assetType") or "").strip()
    asset_key = str(payload.get("asset_key") or payload.get("assetKey") or "").strip()
    reason = str(payload.get("reason") or "")
    try:
        result = await portal_requests.issue_request(
            db,
            tenant_id=principal.tenant_id,
            requester_id=principal.user_id,
            asset_type=asset_type,
            asset_key=asset_key,
            reason=reason,
        )
    except portal_requests.PortalRequestError as exc:
        _raise(exc)
    return {
        "status": result.get("status"),
        "created": bool(result.get("created")),
        "request": _serialize(result.get("request")),
    }


@router.post("/requests/{request_id}/revoke")
async def revoke_my_request(
    request_id: str,
    principal: ApiPrincipal = Depends(require_end_user_principal),
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """回收：申请人可放弃自己的开通，资产 owner 可回收他人的开通（FR-014）。"""
    db = _db()
    row = await db[portal_requests.PORTAL_REQUESTS_COLLECTION].find_one(
        {"tenant_id": principal.tenant_id, "request_id": str(request_id or "").strip()}
    )
    if not row:
        raise HTTPException(status_code=404, detail="request_not_found")
    basic = await portal_listings.get_asset_basics(
        principal.tenant_id, str(row.get("asset_type") or ""), str(row.get("asset_key") or ""), db=db
    )
    owner = str((basic or {}).get("owner") or "")
    if principal.user_id not in {str(row.get("requester_id") or ""), owner}:
        raise HTTPException(status_code=403, detail="forbidden")
    result = await portal_requests.revoke_grant(
        db,
        tenant_id=principal.tenant_id,
        user_id=str(row.get("requester_id") or ""),
        asset_type=str(row.get("asset_type") or ""),
        asset_key=str(row.get("asset_key") or ""),
        revoked_by=principal.user_id,
        reason=str(payload.get("reason") or ""),
    )
    return {"revoked": bool(result.get("revoked")), "request_ids": result.get("request_ids") or []}
