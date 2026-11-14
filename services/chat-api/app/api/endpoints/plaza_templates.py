"""053-plaza-template-distribution：模板广场查询（end_user 侧，FR-008 / FR-010）.

契约（走 chat-api 既有 ``/askai-api`` 前缀 + ``end_user`` 会话鉴权）：

* ``GET  /api/v1/plaza/templates``        广场目录（租户内已上架模板，只读）
* ``GET  /api/v1/plaza/templates/{id}``   模板详情（含版本序列）

租户隔离：``tenant_id`` 一律取自 ``end_user`` 会话（``ApiPrincipal.tenant_id``）；
跨租户 fail-closed（FR-008）。广场查询经既有鉴权（``require_end_user_principal``），
不另建通道。管理侧（上架 / 克隆 / 升级）在 admin-api ``/api/v1/templates``。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.principal import ApiPrincipal, require_end_user_principal
from app.core.db import get_db

router = APIRouter(prefix="/api/v1/plaza", dependencies=[Depends(require_end_user_principal)])

TEMPLATES_COLLECTION = "asset_templates"

TEMPLATE_TYPES: tuple[str, ...] = ("employee_template", "sop_template")
VISIBLE_STATES: tuple[str, ...] = ("published",)


def _db() -> Any:
    return get_db()


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    """模板广场投影（不含内容，含版本序列摘要）。"""
    return {
        "template_id": row.get("template_id"),
        "name": row.get("name"),
        "asset_type": row.get("asset_type"),
        "version": row.get("version"),
        "state": row.get("state"),
        "category": row.get("category") or "",
        "description": row.get("description") or "",
        "owner_id": row.get("owner_id") or "",
        "updated_at": row.get("updated_at").isoformat() if row.get("updated_at") else None,
    }


def _serialize_detail(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_serialize(row),
        "content": row.get("content") or {},
        "gate_report": row.get("gate_report") or {},
        "versions": list(row.get("versions") or []),
    }


@router.get("/templates")
async def list_plaza_templates(
    asset_type: Optional[str] = None,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, Any]:
    """广场目录：租户内已上架模板（跨租户 fail-closed，只读）。"""
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="data backend not initialized")
    query: dict[str, Any] = {"tenant_id": principal.tenant_id, "state": {"$in": list(VISIBLE_STATES)}}
    if asset_type:
        if asset_type not in TEMPLATE_TYPES:
            raise HTTPException(status_code=400, detail="unsupported_asset_type")
        query["asset_type"] = asset_type
    rows = await db[TEMPLATES_COLLECTION].find(query).sort("updated_at", -1).to_list(length=500)
    items = [_serialize(r) for r in rows]
    return {"code": 0, "message": "ok", "data": {"items": items, "total": len(items)}}


@router.get("/templates/{template_id}")
async def get_plaza_template(
    template_id: str,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, Any]:
    """模板详情（租户内已上架，含版本序列）。"""
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="data backend not initialized")
    row = await db[TEMPLATES_COLLECTION].find_one(
        {"tenant_id": principal.tenant_id, "template_id": template_id, "state": {"$in": list(VISIBLE_STATES)}}
    )
    if row is None:
        raise HTTPException(status_code=404, detail="template_not_found")
    return {"code": 0, "message": "ok", "data": _serialize_detail(row)}


__all__ = ["router"]
