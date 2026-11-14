"""Sandbox 执行记录只读查询（③）。

数据来源：chat-api 在 ``finalize_task_audit`` 归档时，将每次 call 的 audit.json
落为扁平文档写入 ``sandbox_execution_records`` 集合（区别于 ``sandbox_task_audits``
的 message 级嵌套 calls[]）。本路由是管理面查询入口：按 agent / status / 时间倒序的
只读列表 + 单条详情，并保留 DB 未就绪时的降级空视图（与 egress.py 一致）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.api.deps import get_authenticated_admin
from app.core.db import get_db

SANDBOX_EXEC_COLLECTION = "sandbox_execution_records"

router = APIRouter(prefix="/sandbox-executions", tags=["sandbox-executions"])


async def get_sandbox_admin(authorization: str | None = Header(default=None)) -> dict:
    """Any authenticated admin — tenant only（拒绝 platform 的 ``default`` 上下文）。"""
    user = await get_authenticated_admin(authorization)
    if str(user.get("tenant_id") or "") == "default":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant context is required")
    return user


@router.get("")
async def list_sandbox_executions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    agent_id: str = Query(default=""),
    status: str = Query(default=""),
    current_user: dict[str, Any] = Depends(get_sandbox_admin),
) -> dict[str, Any]:
    """Read-only list of this tenant's sandbox execution records, newest first."""
    tenant_id = str(current_user.get("tenant_id") or "default")
    # 025 FR-15 (T028)：DB 未就绪是**降级**而非「没有记录」。保留 `items: []`
    # 以兼容既有前端表格渲染，同时显式标记 `degraded: true` + `reason`。
    try:
        db = get_db()
    except Exception:  # noqa: BLE001 — DB 未就绪时返回降级空视图，不影响调用方
        return {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "degraded": True,
            "reason": "db_unavailable",
        }
    if db is None:
        return {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "degraded": True,
            "reason": "db_unavailable",
        }
    collection = db[SANDBOX_EXEC_COLLECTION]
    query: dict[str, Any] = {"tenant_id": tenant_id}
    if agent_id:
        query["agent_id"] = agent_id
    if status:
        query["status"] = status
    total = await collection.count_documents(query)
    cursor = collection.find(query).sort("finished_at", -1).skip((page - 1) * page_size).limit(page_size)
    rows = await cursor.to_list(length=page_size)
    items = [_to_item(r) for r in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{record_id}")
async def get_sandbox_execution(
    record_id: str,
    current_user: dict[str, Any] = Depends(get_sandbox_admin),
) -> dict[str, Any]:
    """Single execution record by composite id ``tenant:message:call``."""
    tenant_id = str(current_user.get("tenant_id") or "default")
    try:
        db = get_db()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="db_unavailable")
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="db_unavailable")
    collection = db[SANDBOX_EXEC_COLLECTION]
    doc = await collection.find_one({"_id": record_id, "tenant_id": tenant_id})
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sandbox execution record not found")
    return _to_item(doc)


def _to_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": row.get("_id"),
        "tenant_id": row.get("tenant_id"),
        "user_id": row.get("user_id"),
        "agent_id": row.get("agent_id"),
        "message_id": row.get("message_id"),
        "conversation_id": row.get("conversation_id"),
        "call_id": row.get("call_id"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "duration_ms": row.get("duration_ms"),
        "exit_code": row.get("exit_code"),
        "status": row.get("status"),
        "rejected": bool(row.get("rejected", False)),
        "skill_digest": row.get("skill_digest") or "",
        "image_ref": row.get("image_ref") or "",
    }


__all__ = ["router"]
