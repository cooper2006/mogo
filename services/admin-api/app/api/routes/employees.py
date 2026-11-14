"""数字员工管理端接口（051 FR-001 / FR-011）。

契约（admin-api，管理员会话）：

* ``GET    /api/v1/employees``                    列表（租户隔离，含软删除过滤）
* ``POST   /api/v1/employees``                    创建（CRUD 全审计 → 001 审计流）
* ``GET    /api/v1/employees/{id}``               详情
* ``PUT    /api/v1/employees/{id}``               更新档案
* ``PATCH  /api/v1/employees/{id}/status``        启停 / 归档
* ``DELETE /api/v1/employees/{id}``               软删除（FR-010：历史会话保留溯源）
* ``GET    /api/v1/employees/catalog/resources``  资源目录（工具 / Skill / 知识库）
* ``POST   /api/v1/employees/{id}/api-keys``      创建员工级 API Key（T021，明文一次性）
* ``GET    /api/v1/employees/{id}/api-keys``      员工 Key 列表
* ``DELETE /api/v1/employees/{id}/api-keys/{key}`` 撤销员工 Key

与 006 岗位角色（人的 RBAC）隔离：员工实体沿用其白名单范式与
``AGENT_CAPABILITY_KEYS``，但不改造 ``position_roles`` 逻辑。管理端操作经
``system_audit`` 中间件（宪法 III）+ 员工自身 001 审计流。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.core.db import get_db
from app.employees.repository import EmployeeRepository
from app.employees.profile import validate_employee_references, EmployeeReferenceError
from app.employees.api_keys import EmployeeApiKeyRepository, KEY_SCOPES
from app.services.organization_tools import organization_tool_query

router = APIRouter()


class EmployeeKeyCreatePayload(BaseModel):
    label: str = Field(default="", max_length=120)
    scope: str = Field(default="read+session", pattern=r"^(read|session|read\+session)$")
    ttlDays: int | None = Field(default=None, ge=1, le=3650)


class EmployeePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    status: str = Field(default="active", pattern=r"^(active|disabled|archived)$")
    capabilities: dict[str, bool] = Field(default_factory=dict)
    toolAccessMode: str = Field(default="selected", pattern=r"^(all|selected)$")
    toolIds: list[str] = Field(default_factory=list)
    skillAccessMode: str = Field(default="selected", pattern=r"^(all|selected)$")
    skillIds: list[str] = Field(default_factory=list)
    knowledge_base_ids: list[str] = Field(default_factory=list)
    memory_scope: str = Field(default="personal", pattern=r"^(personal|project|department)$")
    model_settings: dict[str, Any] = Field(default_factory=dict)
    harness_profile_ref: str = Field(default="", max_length=256)
    member_user_ids: list[str] = Field(default_factory=list)


class EmployeeStatusPayload(BaseModel):
    status: str = Field(pattern=r"^(active|disabled|archived)$")


def _tenant_id(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or "default")


def _actor(user: dict[str, Any]) -> str:
    return str(user.get("username") or user.get("display_name") or user.get("_id") or "admin")


def _payload_dict(payload: EmployeePayload) -> dict[str, Any]:
    data = payload.model_dump()
    # model_settings 是对外契约字段（避开 Pydantic 保留名 model_config），
    # 落库前映射回仓库期望的 model_config。
    if "model_settings" in data:
        data["model_config"] = data.pop("model_settings")
    return data


def _repo() -> EmployeeRepository:
    return EmployeeRepository()


@router.get("")
async def list_employees(current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = _tenant_id(current_user)
    repo = _repo()
    rows = await repo.list_tenant(tenant_id)
    items = [EmployeeRepository.serialize(row) for row in rows]
    return {"items": items, "total": len(items)}


@router.get("/catalog/resources")
async def employee_resource_catalog(current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    """员工档案配置可选的资源目录（工具 / Skill / 知识库）。"""
    tenant_id = _tenant_id(current_user)
    db = get_db()
    tools = await db.external_tools.find(organization_tool_query(tenant_id, status="active")).sort("name", 1).to_list(length=5000)
    skills = await db.skills.find({"tenant_id": tenant_id, "enabled": True}).sort("name", 1).to_list(length=5000)
    return {
        "tools": [{"id": str(row.get("_id")), "name": row.get("name", ""), "type": row.get("type", "http")} for row in tools],
        "skills": [{"id": str(row.get("_id")), "name": row.get("name", ""), "type": row.get("type", "")} for row in skills],
    }


@router.get("/{employee_id}")
async def get_employee(employee_id: str, current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = _tenant_id(current_user)
    row = await _repo().get(tenant_id, employee_id)
    if not row:
        raise HTTPException(status_code=404, detail="员工不存在")
    return EmployeeRepository.serialize(row)


@router.post("", status_code=201)
async def create_employee(payload: EmployeePayload, current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = _tenant_id(current_user)
    actor = _actor(current_user)
    repo = _repo()
    data = _payload_dict(payload)
    try:
        await validate_employee_references(
            tenant_id,
            tool_ids=data.get("toolIds", data.get("tool_ids", [])),
            skill_ids=data.get("skillIds", data.get("skill_ids", [])),
            knowledge_base_ids=data.get("knowledge_base_ids", []),
            harness_profile_ref=data.get("harness_profile_ref", ""),
        )
    except EmployeeReferenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    doc = await repo.create(tenant_id, data, actor)
    await repo.audit(tenant_id, actor, "create", str(doc.get("_id") or ""), {"name": doc.get("name")})
    return EmployeeRepository.serialize(doc)


@router.put("/{employee_id}")
async def update_employee(employee_id: str, payload: EmployeePayload, current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = _tenant_id(current_user)
    actor = _actor(current_user)
    repo = _repo()
    data = _payload_dict(payload)
    try:
        await validate_employee_references(
            tenant_id,
            tool_ids=data.get("toolIds", data.get("tool_ids", [])),
            skill_ids=data.get("skillIds", data.get("skill_ids", [])),
            knowledge_base_ids=data.get("knowledge_base_ids", []),
            harness_profile_ref=data.get("harness_profile_ref", ""),
        )
    except EmployeeReferenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        doc = await repo.update(tenant_id, employee_id, data, actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not doc:
        raise HTTPException(status_code=404, detail="员工不存在")
    await repo.audit(tenant_id, actor, "update", employee_id, {"name": doc.get("name")})
    return EmployeeRepository.serialize(doc)


@router.patch("/{employee_id}/status")
async def set_employee_status(employee_id: str, payload: EmployeeStatusPayload, current_user: dict = Depends(get_current_admin_user)) -> dict[str, bool]:
    tenant_id = _tenant_id(current_user)
    actor = _actor(current_user)
    repo = _repo()
    try:
        doc = await repo.set_status(tenant_id, employee_id, payload.status, actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not doc:
        raise HTTPException(status_code=404, detail="员工不存在")
    await repo.audit(tenant_id, actor, f"status.{payload.status}", employee_id, {})
    return {"success": True}


@router.delete("/{employee_id}")
async def delete_employee(employee_id: str, current_user: dict = Depends(get_current_admin_user)) -> dict[str, bool]:
    tenant_id = _tenant_id(current_user)
    actor = _actor(current_user)
    repo = _repo()
    deleted = await repo.soft_delete(tenant_id, employee_id, actor)
    if not deleted:
        raise HTTPException(status_code=404, detail="员工不存在")
    await repo.audit(tenant_id, actor, "delete", employee_id, {})
    return {"success": True}


# --- 员工级 API Key（051 FR-009 / T021；OQ-3 范围=只读+会话，不含档案修改） ---

@router.post("/{employee_id}/api-keys", status_code=201)
async def create_employee_api_key(
    employee_id: str,
    payload: EmployeeKeyCreatePayload,
    current_user: dict = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """签发员工级开放 API Key（明文仅此响应一次，库中只存哈希）。"""
    tenant_id = _tenant_id(current_user)
    actor = _actor(current_user)
    repo = _repo()
    if not await repo.get(tenant_id, employee_id):
        raise HTTPException(status_code=404, detail="员工不存在")
    key_repo = EmployeeApiKeyRepository()
    try:
        row = await key_repo.create_key(
            tenant_id=tenant_id,
            employee_id=employee_id,
            actor=actor,
            label=payload.label,
            scope=payload.scope,
            ttl_days=payload.ttlDays,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await repo.audit(
        tenant_id, actor, "api_key.create", employee_id,
        {"keyId": row.get("_id"), "scope": row.get("scope")},
    )
    return {**EmployeeApiKeyRepository.serialize(row), "plaintext": str(row.get("plaintext") or "")}


@router.get("/{employee_id}/api-keys")
async def list_employee_api_keys(
    employee_id: str, current_user: dict = Depends(get_current_admin_user)
) -> dict[str, Any]:
    """员工 Key 列表（永不回显明文/哈希）。"""
    tenant_id = _tenant_id(current_user)
    repo = _repo()
    if not await repo.get(tenant_id, employee_id):
        raise HTTPException(status_code=404, detail="员工不存在")
    rows = await EmployeeApiKeyRepository().list_keys(tenant_id=tenant_id, employee_id=employee_id)
    return {"items": [EmployeeApiKeyRepository.serialize(row) for row in rows], "total": len(rows)}


@router.delete("/{employee_id}/api-keys/{key_id}")
async def revoke_employee_api_key(
    employee_id: str, key_id: str, current_user: dict = Depends(get_current_admin_user)
) -> dict[str, bool]:
    """撤销员工级 API Key（幂等）。"""
    tenant_id = _tenant_id(current_user)
    actor = _actor(current_user)
    repo = _repo()
    if not await repo.get(tenant_id, employee_id):
        raise HTTPException(status_code=404, detail="员工不存在")
    row = await EmployeeApiKeyRepository().revoke_key(
        tenant_id=tenant_id, key_id=key_id, actor=actor
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Key 不存在或已撤销")
    await repo.audit(
        tenant_id, actor, "api_key.revoke", employee_id, {"keyId": key_id}
    )
    return {"success": True}
