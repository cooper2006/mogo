"""数字员工用户侧接口（051 FR-003 / FR-005 / FR-010）。

契约（chat-api ``/api/v1`` 前缀 + ``end_user`` 会话鉴权，租户隔离）：

* ``GET /api/employees``         可用员工列表（可见性 = 我的 ∪ 我参与的；认领开通过滤）
* ``GET /api/employees/{id}``    员工详情（同可见性）

未声明员工的会话行为零改动（FR-003）；跨租户 fail-closed（020 口径）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException

from app.api.endpoints.auth import _resolve_session_user
from app.core.tenant import resolve_tenant_id
from app.employees.repository import EmployeeRepository
from app.employees.profile import materialize_employee_profile
from app.employees.api_key_auth import EmployeeApiKeyPrincipal, require_scope

router = APIRouter()


async def _principal(authorization: str | None) -> tuple[str, str]:
    resolved = await _resolve_session_user(authorization if isinstance(authorization, str) else None)
    user_id = str(resolved["user"].get("_id") or "")
    tenant_id = resolve_tenant_id(resolved.get("tenant_id"))
    return user_id, tenant_id


@router.get("/employees/me/by-key")
async def get_employee_by_api_key(
    principal: EmployeeApiKeyPrincipal = Depends(require_scope("read")),
) -> dict[str, Any]:
    """员工级 API Key 持有者访问自己的员工档案（T021 / FR-009，read scope）。

    Key 解析出员工身份；仅返回该员工（不暴露租户其他员工）。路由定义在
    ``/employees/{employee_id}`` 之前，避免 ``me`` 被当作 employee_id。
    """
    repo = EmployeeRepository()
    row = await repo.get(principal.tenant_id, principal.employee_id)
    if not row:
        raise HTTPException(status_code=404, detail="employee_not_found")
    profile = await materialize_employee_profile(principal.tenant_id, principal.employee_id)
    return {
        **EmployeeRepository.serialize(row),
        "available": str(row.get("status") or "") == "active",
        "profile_ready": profile is not None,
        "access_scope": principal.scope,
    }


@router.get("/employees")
async def list_employees(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """可用员工列表：可见性（049 口径）+ 只返回 active 且未删除的员工。"""
    user_id, tenant_id = await _principal(authorization)
    repo = EmployeeRepository()
    rows = await repo.list_visible(tenant_id, user_id)
    items = [
        {**EmployeeRepository.serialize(row), "available": str(row.get("status") or "") == "active"}
        for row in rows
    ]
    return {"items": items, "total": len(items)}


@router.get("/employees/{employee_id}")
async def get_employee(employee_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """员工详情：同可见性过滤，跨租户 / 不可见一律 404（不泄露存在性）。"""
    user_id, tenant_id = await _principal(authorization)
    repo = EmployeeRepository()
    row = await repo.get(tenant_id, employee_id)
    if not row or not repo._visible(row, user_id):
        raise HTTPException(status_code=404, detail="employee_not_found")
    profile = await materialize_employee_profile(tenant_id, employee_id)
    return {
        **EmployeeRepository.serialize(row),
        "available": str(row.get("status") or "") == "active",
        "profile_ready": profile is not None,
    }
