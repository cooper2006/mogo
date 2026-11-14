"""053-plaza-template-distribution：模板管理 + 广场查询 + 克隆/升级端点（T008 / T013）.

端点（admin JWT 鉴权，``get_current_admin_user``）：

* ``GET    /api/templates``            广场目录（租户内，FR-008）
* ``GET    /api/templates/{id}``       模板详情（含版本序列 + 克隆记录）
* ``POST   /api/templates``            创建模板草稿（管理员）
* ``POST   /api/templates/{id}/publish``    上架（门禁 + 审批接线）
* ``POST   /api/templates/{id}/unpublish``  下架（不伤副本）
* ``POST   /api/templates/{id}/clone``      克隆到克隆者名下（US2）
* ``POST   /api/templates/{id}/upgrade``    副本手动升级（US3）
* ``GET    /api/templates/{id}/clones``     克隆记录查询

契约：025 错误码风格（``{"code": 0, "message": ..., "data": ...}``）；
GET 无副作用；跨租户 fail-closed（FR-008）。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.core.db import get_db

from app.services.skill_market import record_skill_call

from app.services.templates import (
    EMPLOYEE_TEMPLATE,
    SOP_TEMPLATE,
    TEMPLATE_ASSET_TYPES,
    AssetTemplate,
    CloneError,
    PublishBlocked,
    TemplateError,
    TemplateRepository,
    UpgradeError,
    clone_template,
    has_newer_version,
    publish_template,
    unpublish_template,
    upgrade_clone,
)
from app.services.templates.model import make_template_id, utcnow

router = APIRouter(tags=["templates"])


class TemplatePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    asset_type: str = Field(..., max_length=64)
    content: dict[str, Any] = Field(default_factory=dict)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=64)
    owner_id: str = Field(default="", max_length=128)


class ClonePayload(BaseModel):
    cloner_id: str = Field(..., min_length=1, max_length=128)
    name: str | None = Field(default=None, max_length=200)


class UpgradePayload(BaseModel):
    operator_id: str = Field(..., min_length=1, max_length=128)
    target_type: str = Field(..., max_length=64)
    target_key: str = Field(..., min_length=1, max_length=256)


def _tenant_id(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or "default")


def _actor(user: dict[str, Any]) -> str:
    return str(user.get("username") or user.get("display_name") or "")


def _repo() -> TemplateRepository:
    return TemplateRepository()


def _require_template_type(asset_type: str) -> None:
    if asset_type not in TEMPLATE_ASSET_TYPES:
        raise HTTPException(status_code=400, detail=f"unsupported template asset_type: {asset_type!r}")


async def _get_template_or_404(template_id: str, tenant_id: str) -> AssetTemplate:
    template = await _repo().get_template(template_id, tenant_id=tenant_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template_not_found")
    return template


# ---------------------------------------------------------------------------
# 广场目录 / 详情（FR-008 租户内；跨租户 fail-closed）
# ---------------------------------------------------------------------------


@router.get("")
async def list_templates(
    asset_type: Optional[str] = None,
    state: Optional[str] = None,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """模板管理目录：租户内全部状态（草稿 / 已上架 / 已下架），跨租户 fail-closed。

    用户侧广场只读已上架模板，由 chat-api ``/api/v1/plaza/templates`` 独立过滤；
    管理侧必须能看到草稿，否则新建后无法上架。``state`` 显式传入时按状态过滤。
    """
    tenant_id = _tenant_id(current_user)
    if asset_type:
        _require_template_type(asset_type)
    templates = await _repo().list_templates(
        tenant_id=tenant_id, asset_type=asset_type, state=state
    )
    items = [
        {
            "template_id": t.template_id,
            "name": t.name,
            "asset_type": t.asset_type,
            "version": t.version,
            "state": t.state,
            "category": t.category,
            "description": t.description,
            "owner_id": t.owner_id,
            "digest": t.digest(),
            "readonly": t.is_readonly,
            "updated_at": t.updated_at.isoformat(),
        }
        for t in templates
    ]
    return {"code": 0, "message": "ok", "data": {"items": items, "total": len(items)}}


@router.get("/{template_id}")
async def get_template(
    template_id: str,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """模板详情（含版本序列 + 内容 + 克隆记录）。"""
    tenant_id = _tenant_id(current_user)
    template = await _get_template_or_404(template_id, tenant_id)
    clones = await _repo().list_clones(tenant_id=tenant_id, template_id=template_id)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            **template.as_dict(include_content=True),
            "clones": [c.as_dict() for c in clones],
        },
    }


# ---------------------------------------------------------------------------
# 模板管理（US1）：创建 / 上架 / 下架
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
async def create_template(
    payload: TemplatePayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """创建模板草稿（管理员）。"""
    _require_template_type(payload.asset_type)
    tenant_id = _tenant_id(current_user)
    template = AssetTemplate(
        template_id=make_template_id(),
        tenant_id=tenant_id,
        name=payload.name,
        asset_type=payload.asset_type,
        content=dict(payload.content or {}),
        state="draft",
        owner_id=payload.owner_id or _actor(current_user),
        description=payload.description,
        category=payload.category,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    await _repo().save_template(template)
    await _repo().audit(
        tenant_id=tenant_id, actor=_actor(current_user), action="create",
        detail={"template_id": template.template_id, "asset_type": payload.asset_type},
    )
    return {"code": 0, "message": "created", "data": template.as_dict(include_content=False)}


@router.post("/{template_id}/publish")
async def publish_endpoint(
    template_id: str,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """上架：032 门禁（SOP）/ 引用校验（员工）→ 001 审批接线 → 审计。

    门禁失败返回 409（fail-closed，不静默上架）。
    """
    tenant_id = _tenant_id(current_user)
    template = await _get_template_or_404(template_id, tenant_id)
    try:
        await publish_template(template, actor=_actor(current_user), repo=_repo())
    except PublishBlocked as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.reason) from exc
    return {"code": 0, "message": "published", "data": template.as_dict(include_content=False)}


@router.post("/{template_id}/unpublish")
async def unpublish_endpoint(
    template_id: str,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """下架（FR-006）：不撤销已克隆副本；仅标记 offline。"""
    tenant_id = _tenant_id(current_user)
    template = await _get_template_or_404(template_id, tenant_id)
    await unpublish_template(template, actor=_actor(current_user), repo=_repo())
    return {"code": 0, "message": "unpublished", "data": template.as_dict(include_content=False)}


# ---------------------------------------------------------------------------
# 克隆 / 升级（US2 / US3）
# ---------------------------------------------------------------------------


@router.post("/{template_id}/clone", status_code=201)
async def clone_endpoint(
    template_id: str,
    payload: ClonePayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """克隆模板到克隆者名下新实体（US2）。

    副本落既有实体集合（SOP → dag_definitions；员工 → employees），
    记录 template_ref；凭证不复制（FR-004）；原件只读。
    """
    tenant_id = _tenant_id(current_user)
    template = await _get_template_or_404(template_id, tenant_id)
    if not template.is_published:
        raise HTTPException(status_code=409, detail="template_not_published")
    try:
        clone, target_doc = await clone_template(
            template, cloner_id=payload.cloner_id or _actor(current_user), name=payload.name, repo=_repo()
        )
    except CloneError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # 落既有实体集合（027 门面）。SOP → dag_definitions；员工 → employees。
    await _persist_clone_target(clone, target_doc, tenant_id)
    # T019：副本默认**未开通**——登记 listing 使其可走 037 申领，但**不写授权**
    # （无 permission_grants），使用须经申领审批 fail-closed（FR-007）。
    await _register_clone_listing(clone, tenant_id, current_user)
    # T022 质量信号（FR-011）：克隆数经 016 既有监控面（skill_quality_metrics
    # 桶，skill_key=template_id，adopted=1 表示一次克隆采纳）；不新建评分。
    try:
        await record_skill_call(
            get_db(), tenant_id=tenant_id, skill_key=template.template_id, adopted=1
        )
    except Exception:  # noqa: BLE001 - 016 监控面写入失败不阻断克隆（软依赖）
        pass

    return {
        "code": 0,
        "message": "cloned",
        "data": {"clone": clone.as_dict(), "target_type": clone.target_type, "target_key": clone.target_key},
    }


async def _register_clone_listing(clone: Any, tenant_id: str, current_user: dict[str, Any]) -> None:
    """克隆副本登记 portal_listings（可申领）；不写 permission_grants（未开通）。"""
    db = get_db()
    await db["portal_listings"].update_one(
        {"tenant_id": tenant_id, "asset_type": clone.target_type, "asset_key": clone.target_key},
        {
            "$set": {
                "tenant_id": tenant_id,
                "asset_type": clone.target_type,
                "asset_key": clone.target_key,
                "category": "template_clone",
                "published_by": _actor(current_user),
                "published_at": utcnow(),
            },
            "$unset": {"unpublished_at": ""},
        },
        upsert=True,
    )


async def _persist_clone_target(clone: Any, target_doc: dict[str, Any], tenant_id: str) -> None:
    """克隆副本落既有实体集合（副本即普通实体，plan Structure Decision）。"""
    db = get_db()
    if clone.target_type == "dag_definition":
        header = target_doc.get("orchestration") or {}
        await db["dag_definitions"].update_one(
            {"tenant_id": tenant_id, "orchestration_id": clone.target_key},
            {
                "$set": {
                    "orchestration_id": clone.target_key,
                    "tenant_id": tenant_id,
                    "user_id": clone.cloner_id,
                    "version": str(header.get("version") or "1"),
                    "status": "published",
                    "document": target_doc,
                    "template_ref": clone.template_ref,
                    "updated_at": utcnow(),
                },
                "$setOnInsert": {"created_at": utcnow()},
            },
            upsert=True,
        )
    elif clone.target_type == "employee":
        await db["employees"].update_one(
            {"tenant_id": tenant_id, "employee_id": clone.target_key},
            {
                "$set": {
                    "employee_id": clone.target_key,
                    "tenant_id": tenant_id,
                    "created_by": clone.cloner_id,
                    "status": "active",
                    **target_doc,
                    "template_ref": clone.template_ref,
                    "updated_at": utcnow(),
                },
                "$setOnInsert": {"created_at": utcnow()},
            },
            upsert=True,
        )
    else:
        raise HTTPException(status_code=400, detail=f"unsupported target_type: {clone.target_type!r}")


@router.post("/{template_id}/upgrade")
async def upgrade_endpoint(
    template_id: str,
    payload: UpgradePayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """副本手动升级（US3）：整份替换 + 旧快照 + template_ref 更新 + 审计。"""
    tenant_id = _tenant_id(current_user)
    template = await _get_template_or_404(template_id, tenant_id)
    try:
        record = await upgrade_clone(
            tenant_id=tenant_id,
            template=template,
            target_type=payload.target_type,
            target_key=payload.target_key,
            operator_id=payload.operator_id or _actor(current_user),
            repo=_repo(),
        )
    except UpgradeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"code": 0, "message": "upgraded", "data": record.as_dict()}


@router.get("/{template_id}/clones")
async def list_clones_endpoint(
    template_id: str,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """克隆记录查询（版本提示 / 下钻用）。"""
    tenant_id = _tenant_id(current_user)
    await _get_template_or_404(template_id, tenant_id)
    clones = await _repo().list_clones(tenant_id=tenant_id, template_id=template_id)
    template = await _repo().get_template(template_id, tenant_id=tenant_id)
    items = []
    for c in clones:
        item = c.as_dict()
        if template is not None:
            item["has_newer_version"] = has_newer_version(template, current_ref_version=c.template_version)
            item["source_version"] = template.version
        items.append(item)
    return {"code": 0, "message": "ok", "data": {"items": items, "total": len(items)}}


__all__ = ["router"]
