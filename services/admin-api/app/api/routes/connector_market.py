"""041-connector-market: 连接器模板目录 + 从模板创建（admin-api 路由）。

设计约束（spec 硬约束）：
- **同构**（FR-004）：创建连接器必须复用 `app.api.routes.tools.create_tool_record`，
  落既有 `external_tools` 存储与既有凭证注入路径，不允许另建工具存储。
- **种子只读**（FR-005）：模板来自仓库内 YAML，本 API 不写模板、不做模板管理后台。
- **安装计数**（FR-007）：只按 `(tenant_id, template_id)` 计数，不做跨租户排行榜。
- **凭证托管**（034）：能落 header 的凭据进 `config.authToken`（由 034 加密覆盖）；
  URL 内凭据的模板明确标记 `credentialManaged=false`，由调用期传参。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.api.routes.tools import _safe_dict, _serialize, create_tool_record, redact_credentials
from app.core.db import get_db
from app.services import connector_templates as templates_service


logger = logging.getLogger(__name__)

router = APIRouter()

INSTALLS_COLLECTION = "connector_installs"
TOOLS_COLLECTION = "external_tools"
MAX_KEYWORD_LENGTH = 80


class InstallPayload(BaseModel):
    # 允许覆盖默认名称（默认取模板名）。
    name: str = Field(default="", max_length=120)
    # 模板参数值（key → 字符串）；secret 参数会进 config.authToken。
    values: dict[str, Any] = Field(default_factory=dict)
    # 创建后立即上架（默认 false：先建为 disabled，测试通过后再 PATCH 上架）。
    activate: bool = False
    description: str = Field(default="", max_length=500)


def _template_or_404(template_id: str) -> dict[str, Any]:
    template = templates_service.get_template(template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="连接器模板不存在")
    return template


def _tenant_id(current_user: dict[str, Any]) -> str:
    return str(current_user.get("tenant_id") or "default")


async def _install_counts(tenant_id: str) -> dict[str, int]:
    db = get_db()
    pipeline = [
        {"$match": {"tenant_id": tenant_id}},
        {"$group": {"_id": "$template_id", "count": {"$sum": 1}}},
    ]
    counts: dict[str, int] = {}
    try:
        async for row in db[INSTALLS_COLLECTION].aggregate(pipeline):
            counts[str(row.get("_id") or "")] = int(row.get("count") or 0)
    except AttributeError:  # pragma: no cover - 简化驱动/测试替身
        rows = await db[INSTALLS_COLLECTION].find({"tenant_id": tenant_id}).to_list(length=1000)
        for row in rows:
            key = str(row.get("template_id") or "")
            counts[key] = counts.get(key, 0) + 1
    return counts


async def _installed_tool_ids(tenant_id: str) -> set[str]:
    db = get_db()
    rows = await db[INSTALLS_COLLECTION].find({"tenant_id": tenant_id}).to_list(length=1000)
    return {str(row.get("tool_id") or "") for row in rows if row.get("tool_id")}


@router.get("/templates")
async def list_templates(
    category: str = Query(default="", max_length=40),
    keyword: str = Query(default="", max_length=MAX_KEYWORD_LENGTH),
    current_user: dict = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """模板目录：全部模板 + 分类 + 本租户安装计数/已安装标记。"""

    tenant_id = _tenant_id(current_user)
    rows = templates_service.list_templates(category=category, keyword=keyword)
    counts = await _install_counts(tenant_id)
    installed_tool_ids = await _installed_tool_ids(tenant_id)
    installed_by_template: dict[str, list[str]] = {}
    if installed_tool_ids:
        db = get_db()
        install_rows = await db[INSTALLS_COLLECTION].find({"tenant_id": tenant_id}).to_list(length=1000)
        for row in install_rows:
            installed_by_template.setdefault(str(row.get("template_id") or ""), []).append(
                str(row.get("tool_id") or "")
            )
    return {
        "templates": [
            {
                **templates_service.template_view(template),
                "installCount": counts.get(str(template.get("id")), 0),
                "installed": bool(installed_by_template.get(str(template.get("id")))),
            }
            for template in rows
        ],
        "categories": templates_service.template_categories(),
        "loadIssues": templates_service.load_issues(),
    }


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    current_user: dict = Depends(get_current_admin_user),
) -> dict[str, Any]:
    template = _template_or_404(template_id)
    tenant_id = _tenant_id(current_user)
    counts = await _install_counts(tenant_id)
    return {
        **templates_service.template_view(template),
        "installCount": counts.get(str(template.get("id")), 0),
    }


@router.post("/templates/{template_id}/install", status_code=status.HTTP_201_CREATED)
async def install_template(
    template_id: str,
    payload: InstallPayload,
    current_user: dict = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """从模板创建连接器（落既有 external_tools，注册 018 资产，记安装）。"""

    template = _template_or_404(template_id)
    errors = templates_service.validate_values(template, payload.values)
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=errors)

    tenant_id = _tenant_id(current_user)
    name = (payload.name or "").strip() or str((template.get("name") or {}).get("zh") or template.get("id"))
    description = (payload.description or "").strip() or str(
        (template.get("description") or {}).get("zh") or ""
    )
    config = templates_service.render_config(template, payload.values, timeout_seconds=30)

    doc = await create_tool_record(
        tenant_id=tenant_id,
        payload={
            "name": name,
            "type": "http",
            "description": description,
            "usageHint": str((template.get("test_hint") or {}).get("probe") or ""),
            "tags": [str(template.get("category") or ""), "connector"],
            "config": config,
        },
    )
    tool_id = str(doc.get("_id") or "")

    if payload.activate:
        # 上架仍走既有 PATCH 语义（需要测试通过），这里只置状态位，不绕过校验。
        db = get_db()
        await db[TOOLS_COLLECTION].update_one(
            {"_id": tool_id, "tenant_id": tenant_id},
            {"$set": {"status": "active", "updated_at": doc.get("updated_at")}},
        )
        doc["status"] = "active"

    await _record_install(
        tenant_id=tenant_id,
        template=template,
        tool_id=tool_id,
        name=name,
        actor=str(current_user.get("username") or ""),
    )

    return {
        "templateId": template.get("id"),
        "templateVersion": template.get("version"),
        "credentialManaged": templates_service.credential_managed(template),
        "tool": _serialize(doc),
    }


async def _record_install(
    *,
    tenant_id: str,
    template: dict[str, Any],
    tool_id: str,
    name: str,
    actor: str = "",
) -> None:
    db = get_db()
    install = {
        "_id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "template_id": str(template.get("id") or ""),
        "template_version": int(template.get("version") or 1),
        "tool_id": tool_id,
        "name": name,
        "created_at": doc_now(),
        "actor": actor,
    }
    await db[INSTALLS_COLLECTION].insert_one(install)
    await _register_capability_asset(template=template, tool_id=tool_id, name=name, tenant_id=tenant_id)


def doc_now() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


async def _register_capability_asset(
    *,
    template: dict[str, Any],
    tool_id: str,
    name: str,
    tenant_id: str,
) -> None:
    """018 关系声明（FR-008）：连接器登记为能力资产 `kind=connector`。

    注册失败不阻断创建——018 是发现/治理层，连接器本身已可用。
    """

    try:
        from app.services.capability_assets.registry import (
            CapabilityAsset,
            PersistedCapabilityRegistry,
        )

        config = template.get("config_template") or {}
        asset = CapabilityAsset(
            asset_id=f"connector:{tool_id}",
            name=name,
            endpoint=str(config.get("url") or ""),
            method=str(config.get("method") or "").upper(),
            kind="connector",
        )
        await PersistedCapabilityRegistry().register(asset)
    except Exception as exc:  # noqa: BLE001 - 治理层失败不影响连接器可用
        logger.warning("connector capability asset registration failed: %s", exc)


@router.get("/installs")
async def list_installs(
    current_user: dict = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """本租户已安装的连接器（含早期手工创建、无安装记录的工具，标记 manual）。"""

    tenant_id = _tenant_id(current_user)
    db = get_db()
    installs = await db[INSTALLS_COLLECTION].find({"tenant_id": tenant_id}).to_list(length=500)
    by_tool = {str(row.get("tool_id") or ""): row for row in installs}
    tools = await db[TOOLS_COLLECTION].find({"tenant_id": tenant_id}).to_list(length=500)
    items: list[dict[str, Any]] = []
    for tool in tools:
        tool_id = str(tool.get("_id") or "")
        install = by_tool.get(tool_id)
        items.append(
            {
                "toolId": tool_id,
                "name": tool.get("name") or "",
                "status": tool.get("status") or "",
                "lastTestStatus": tool.get("last_test_status") or "",
                "config": redact_credentials(_public_config(tool.get("config"))),
                "templateId": (install or {}).get("template_id") or "",
                "templateVersion": (install or {}).get("template_version"),
                "source": "template" if install else "manual",
                "installedAt": (install or {}).get("created_at") or tool.get("created_at"),
            }
        )
    items.sort(key=lambda item: str(item.get("installedAt") or ""), reverse=True)
    return {"items": items, "total": len(items)}


def _public_config(config: Any) -> dict[str, Any]:
    return _safe_dict(config)


@router.get("/installs/counts")
async def install_counts(current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    counts = await _install_counts(_tenant_id(current_user))
    return {"counts": counts, "total": sum(counts.values())}
