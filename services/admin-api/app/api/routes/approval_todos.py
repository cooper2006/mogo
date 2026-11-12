"""056 US1 — 统一审批待办端点（跨 tool/portal/sop 三来源）。

迁移期只读聚合视图：读取 ``ApprovalKernel.list_todos()`` 的 ``approval_tickets``
影子票据（由 R-7 旁路双写产生，开关 ``APPROVAL_KERNEL_ENABLED`` 控制）。

**边界说明**：本端点只做「统一视图 + 对账」，**不改变任何决策语义**。
三套旧状态机仍是唯一仲裁源；影子票据带 ``shadow=True`` 且不可被
``Kernel.decide`` 消费。开关关闭时（默认）集合为空，返回空列表而非报错——
这是灰度期的预期状态。
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Query

from app.security import gatekeeper as gk
from app.security.service_token import ServiceTokenHeader

from .gatekeeper_internal import _require_service

router = APIRouter()

from app.api.deps import get_current_admin_user
from fastapi import Depends


@router.get("/todos")
async def list_unified_approval_todos(
    tenantId: str = Query(default="", description="租户过滤"),
    approver: str = Query(default="", description="审批人过滤"),
    status: str = Query(default="pending", pattern="^(pending|all)$"),
    service_token: ServiceTokenHeader = "",
) -> dict[str, Any]:
    """返回三类来源的统一待办；每条带 ``source_type`` / ``source_id`` 等统一字段。"""
    _require_service(
        service_token,
        tenant_id=str(tenantId or ""),
        scope=gk.SCOPE_GATEKEEPER_LIST_APPROVALS,
    )

    from app.common.approval_kernel import ApprovalKernel
    from app.core.db import get_db

    kernel = ApprovalKernel(db=get_db(), audit_db=get_db())
    todos = await kernel.list_todos(
        tenant_id=str(tenantId or ""),
        approver_id=str(approver or ""),
        status=status,  # type: ignore[arg-type]
    )
    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": [
                {
                    "ticketId": t.ticket_id,
                    "sourceType": t.source_type,
                    "sourceId": t.source_id,
                    "approverId": t.approver_id,
                    "deadline": t.deadline.isoformat() if hasattr(t.deadline, "isoformat") else str(t.deadline or ""),
                    "state": t.state,
                    "runId": t.run_id,
                    "nodeId": t.node_id,
                }
                for t in todos
            ],
            "total": len(todos),
            # 诚实标注数据源状态，避免前端把空列表误读为「无待办」。
            "shadowOnly": True,
            "kernelEnabled": os.environ.get("APPROVAL_KERNEL_ENABLED", "").strip().lower()
            in {"1", "true", "yes", "on"},
        },
    }


@router.get("/todos/admin")
async def list_admin_approval_todos(
    current_user: dict = Depends(get_current_admin_user),
    tenantId: str = Query(default="", description="租户过滤"),
    approver: str = Query(default="", description="审批人过滤"),
    status: str = Query(default="pending", pattern="^(pending|all)$"),
) -> dict[str, Any]:
    """面向管理端浏览器的统一审批待办列表（使用管理员 JWT，而非内部 service token）。

    复用 ``ApprovalKernel.list_todos`` 的统一视图；返回结构与前缀 ``/todos`` 的内部端点一致，
    便于前端统一渲染。开关 ``APPROVAL_KERNEL_ENABLED`` 关闭（默认）时仍返回空列表（灰度期预期）。
    """
    from app.common.approval_kernel import ApprovalKernel
    from app.core.db import get_db

    kernel = ApprovalKernel(db=get_db(), audit_db=get_db())
    todos = await kernel.list_todos(
        tenant_id=str(tenantId or ""),
        approver_id=str(approver or ""),
        status=status,  # type: ignore[arg-type]
    )
    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": [
                {
                    "ticketId": t.ticket_id,
                    "sourceType": t.source_type,
                    "sourceId": t.source_id,
                    "approverId": t.approver_id,
                    "deadline": t.deadline.isoformat()
                    if hasattr(t.deadline, "isoformat")
                    else str(t.deadline or ""),
                    "state": t.state,
                    "runId": t.run_id,
                    "nodeId": t.node_id,
                }
                for t in todos
            ],
            "total": len(todos),
            "shadowOnly": True,
            "kernelEnabled": os.environ.get("APPROVAL_KERNEL_ENABLED", "").strip().lower()
            in {"1", "true", "yes", "on"},
        },
    }
