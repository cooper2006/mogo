"""本体清单与本体数据权限 —— 管理端接口（设计 §5.7）。

注册：``api_router.include_router(ontologies.router, prefix="/ontologies", tags=["ontologies"])``

鉴权说明：设计稿给这些端点标了 ``ontology:list`` / ``ontology:sync`` / ``ontology:grant``
权限码，但 admin-api **目前没有按路由校验权限码的机制**（既有路由统一只做
``Depends(get_current_admin_user)`` 的租户域校验）。为不引入孤立机制，本模块沿用同一模式：
**租户域管理员即可访问**，越权风险由「租户隔离 + 平台租户拒绝」兜住。
若后续引入权限码，可在这几个依赖上直接挂。

「本体清单」只做展示，**不提供本体 CRUD**（本体定义与数据都在业务系统）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.ontology_permission.constants import (
    ACCESS_MODES,
    DEFAULT_PRIORITY,
    ENTITY_INDEX_TABLE,
    SUBJECT_TYPES,
)
from app.ontology_permission.service import OntologyPermissionService

router = APIRouter()


def _tenant_id(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or "default")


def _actor(user: dict[str, Any]) -> str:
    return str(user.get("username") or user.get("_id") or "admin")


def _user_id(user: dict[str, Any]) -> str:
    return str(user.get("_id") or user.get("id") or user.get("username") or "")


def _validate_subject_type(subject_type: str) -> str:
    if subject_type not in SUBJECT_TYPES:
        raise HTTPException(status_code=422, detail="invalid_subject_type")
    return subject_type


class GrantPayload(BaseModel):
    ontologyIds: list[str] = Field(min_length=1)
    accessMode: str = Field(default="read")
    priority: int = Field(default=DEFAULT_PRIORITY)
    remark: str = Field(default="", max_length=500)


class SyncPayload(BaseModel):
    """业务系统主动推送的清单（可选）。

    当前无业务系统接入时留空即可 —— 端点会回退为「按 MOGO 侧业务实体索引聚合」。
    """

    ontologies: list[dict[str, Any]] = Field(default_factory=list)


class ConfigPayload(BaseModel):
    enforce: bool
    defaultMode: str | None = Field(default=None, pattern=r"^(allow|deny)$")


# ---------------------------------------------------------------------------
# 当前账号可见的本体（展示用）
# ---------------------------------------------------------------------------


@router.get("/mine")
async def list_my_ontologies(current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    """当前账号可见的本体清单（登录即可）。"""
    service = OntologyPermissionService()
    return await service.visible_ontologies(_tenant_id(current_user), _user_id(current_user))


# ---------------------------------------------------------------------------
# 全局开关（灰度用；对应 sys_config['ontology-permission']）
# ---------------------------------------------------------------------------


@router.get("/config")
async def get_ontology_permission_config(
    current_user: dict = Depends(get_current_admin_user),
) -> dict[str, Any]:
    return await OntologyPermissionService().get_config()


@router.put("/config")
async def update_ontology_permission_config(
    payload: ConfigPayload, current_user: dict = Depends(get_current_admin_user)
) -> dict[str, Any]:
    return await OntologyPermissionService().set_enforce(
        tenant_id=_tenant_id(current_user),
        actor=_actor(current_user),
        enforce=payload.enforce,
        default_mode=payload.defaultMode,
    )


# ---------------------------------------------------------------------------
# 全量清单（授权时勾选）
# ---------------------------------------------------------------------------


@router.get("")
async def list_ontologies(current_user: dict = Depends(get_current_admin_user)) -> list[dict[str, Any]]:
    """全量本体清单。

    来源为 MOGO 侧业务实体索引聚合出的 ``ontology_id``，并补上「已授权但索引未出现」
    的本体（否则授权页看不到目标）。设计 §5.4 建议的独立只读副本集合属阶段 4
    （业务系统对接）范畴，本阶段不新增表。
    """
    return await OntologyPermissionService().list_catalog(_tenant_id(current_user))


@router.post("/sync")
async def sync_ontologies(
    payload: SyncPayload | None = None, current_user: dict = Depends(get_current_admin_user)
) -> dict[str, Any]:
    """同步本体只读副本。

    **当前无业务系统接入**（用户已明确：业务系统集成后再接入实际 ``ontology_id``），
    因此本端点不落库，只做一次「按 MOGO 侧业务实体索引重新聚合」，并把结果返回。
    接入业务系统后（设计 §5.10 阶段 4）改为拉取业务系统清单接口并写入独立副本集合。
    """
    catalog = await OntologyPermissionService().list_catalog(_tenant_id(current_user))
    pushed = len(payload.ontologies) if payload and payload.ontologies else 0
    return {
        "source": ENTITY_INDEX_TABLE,
        "synced": len(catalog),
        "pushed": pushed,
        "ontologies": catalog,
        "note": (
            "业务系统尚未接入，清单由 MOGO 侧业务实体索引聚合；"
            "接入后改由业务系统清单接口同步（设计 §5.10 阶段 4）。"
        ),
    }


# ---------------------------------------------------------------------------
# 授权（用户级，设计 §5.7 对外形态）
# ---------------------------------------------------------------------------


@router.get("/users/{user_id}/permissions")
async def get_user_permissions(
    user_id: str, current_user: dict = Depends(get_current_admin_user)
) -> dict[str, Any]:
    return await OntologyPermissionService().list_subject_grants(
        _tenant_id(current_user), "user", user_id
    )


@router.post("/users/{user_id}/permissions")
async def grant_user_permissions(
    user_id: str, payload: GrantPayload, current_user: dict = Depends(get_current_admin_user)
) -> dict[str, Any]:
    """批量授予（纯用户级 → 批量接口很实际，设计 §5.5）。"""
    if payload.accessMode not in ACCESS_MODES:
        raise HTTPException(status_code=422, detail="invalid_access_mode")
    service = OntologyPermissionService()
    result = await service.batch_grant(
        tenant_id=_tenant_id(current_user),
        actor=_actor(current_user),
        subject_type="user",
        subject_id=user_id,
        ontology_ids=payload.ontologyIds,
        access_mode=payload.accessMode,
        priority=payload.priority,
        remark=payload.remark,
    )
    await service.bump_revision(_tenant_id(current_user), _actor(current_user))
    return result


@router.delete("/users/{user_id}/permissions/{ontology_id}")
async def revoke_user_permission(
    user_id: str, ontology_id: str, current_user: dict = Depends(get_current_admin_user)
) -> dict[str, Any]:
    service = OntologyPermissionService()
    result = await service.revoke(
        tenant_id=_tenant_id(current_user),
        actor=_actor(current_user),
        subject_type="user",
        subject_id=user_id,
        ontology_uri=ontology_id,
    )
    await service.bump_revision(_tenant_id(current_user), _actor(current_user))
    return result


# ---------------------------------------------------------------------------
# 授权（四态主体通用形态：tenant / org / role / user）
# ---------------------------------------------------------------------------


@router.get("/subjects/{subject_type}/{subject_id}/permissions")
async def get_subject_permissions(
    subject_type: str, subject_id: str, current_user: dict = Depends(get_current_admin_user)
) -> dict[str, Any]:
    return await OntologyPermissionService().list_subject_grants(
        _tenant_id(current_user), _validate_subject_type(subject_type), subject_id
    )


@router.post("/subjects/{subject_type}/{subject_id}/permissions")
async def grant_subject_permissions(
    subject_type: str,
    subject_id: str,
    payload: GrantPayload,
    current_user: dict = Depends(get_current_admin_user),
) -> dict[str, Any]:
    _validate_subject_type(subject_type)
    if payload.accessMode not in ACCESS_MODES:
        raise HTTPException(status_code=422, detail="invalid_access_mode")
    service = OntologyPermissionService()
    result = await service.batch_grant(
        tenant_id=_tenant_id(current_user),
        actor=_actor(current_user),
        subject_type=subject_type,
        subject_id=subject_id,
        ontology_ids=payload.ontologyIds,
        access_mode=payload.accessMode,
        priority=payload.priority,
        remark=payload.remark,
    )
    await service.bump_revision(_tenant_id(current_user), _actor(current_user))
    return result


@router.delete("/subjects/{subject_type}/{subject_id}/permissions/{ontology_id}")
async def revoke_subject_permission(
    subject_type: str,
    subject_id: str,
    ontology_id: str,
    current_user: dict = Depends(get_current_admin_user),
) -> dict[str, Any]:
    _validate_subject_type(subject_type)
    service = OntologyPermissionService()
    result = await service.revoke(
        tenant_id=_tenant_id(current_user),
        actor=_actor(current_user),
        subject_type=subject_type,
        subject_id=subject_id,
        ontology_uri=ontology_id,
    )
    await service.bump_revision(_tenant_id(current_user), _actor(current_user))
    return result


# ---------------------------------------------------------------------------
# 变更审计
# ---------------------------------------------------------------------------


@router.get("/audit")
async def list_permission_audit(
    limit: int = Query(default=50, ge=1, le=500),
    current_user: dict = Depends(get_current_admin_user),
) -> list[dict[str, Any]]:
    return await OntologyPermissionService().list_audit(_tenant_id(current_user), limit=limit)
