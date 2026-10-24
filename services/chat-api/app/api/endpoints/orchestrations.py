"""可视化编排画布 —— 终端用户侧编排定义读写端点（特性 039）。

特性定位：为 010 DAG 编排引擎补前端可视化画布（``specs/039-visual-orchestration``）。
**文档（YAML/JSON）为权威定义、画布为投影**：画布 ↔ 引擎文档的互转由前端
``apps/user-web/src/components/orchestration/canvasSchema.ts`` 作为唯一转换层完成，
本模块**不引入第三种定义格式**，只负责持久化、校验与版本/发布门禁。

分工（与 010 ``store.py`` / ``loader.py`` 的关系）：
* 校验口径与引擎侧完全一致 —— 复用 ``load_orchestration_document``，任何非法图
  （环、自环、孤立语义、畸形 condition）都在此以 422 返回，错误信息与
  ``topo.CycleError`` / ``graph.GraphError`` 同格式。
* 保存草稿（``status=draft``）与发布（``status=published``）分离：**编排权**即本人可
  保存自己的编排；**发布权**走 001 权限码门禁 ``orchestration:publish``，未持有即
  fail-closed 拒绝（画布不绕过 001 gatekeeper）。

存储：``dag_definitions`` 集合（与 010 FR-8 同表，**不新增集合、不做迁移**）。
``document`` 字段保存完整权威文档（可被 ``load_orchestration_persisted`` 原样装载并
被引擎真实执行），``layout`` 为可丢失的投影元数据（FR-12）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.principal import ApiPrincipal, require_end_user_principal
from app.core.db import get_db
from app.orchestration.loader import load_orchestration_document
from app.orchestration.store import DAG_DEFINITIONS_COLLECTION
from app.security.gatekeeper import GatekeeperDenied
from app.services.orchestration_permission import can_publish_orchestration

#: 发布权权限码（001 权限码模型 ``<resource>:<action>[:<target>]``）。
PUBLISH_PERMISSION = "orchestration:publish"

router = APIRouter(prefix="/api/orchestrations", dependencies=[Depends(require_end_user_principal)])


class ApiResponse(BaseModel):
    code: int = 0
    message: Optional[str] = None
    data: Optional[Any] = None


class OrchestrationDocumentPayload(BaseModel):
    """画布提交的编排文档（引擎侧权威格式）+ 可丢失的投影元数据。"""

    document: dict[str, Any]
    layout: Optional[dict[str, Any]] = None
    release_notes: Optional[str] = Field(default=None, validation_alias="releaseNotes")


class PublishPayload(OrchestrationDocumentPayload):
    """发布请求：文档 + 布局 + 发布说明。"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _owning_scope(principal: ApiPrincipal, orchestration_id: str) -> dict[str, Any]:
    """当前租户 + 指定编排的归属过滤条件（端用户只见自己的编排）。"""
    return {"tenant_id": principal.tenant_id, "orchestration_id": orchestration_id}


def _validate_document(document: dict[str, Any]) -> None:
    """按 010 引擎同口径校验文档；不合法即抛 422（错误信息与引擎侧一致）。

    除 ``load_orchestration_document`` 自带的形状/condition 校验外，额外做：
    * 空图不保存（FR-011 边界）；
    * 环检测 —— 复用引擎 ``topological_order``，报错格式与 ``topo.CycleError`` 完全一致
      （``cycle detected: A -> B -> C -> A``，FR-003）。引擎 010 本身在装载期不做拓扑
      校验（执行期才判环），此处补上以在画布保存前阻断。
    """
    if not isinstance(document, dict):
        raise HTTPException(status_code=422, detail="orchestration document invalid: expected an object")
    nodes = document.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise HTTPException(status_code=422, detail="orchestration document invalid: at least one node is required")
    try:
        loaded = load_orchestration_document(document)
    except Exception as exc:  # OrchestrationLoadError / GraphError / RegistryError
        raise HTTPException(status_code=422, detail=f"orchestration document invalid: {exc}") from exc

    from app.orchestration.topo import CycleError, topological_order

    try:
        topological_order(loaded.definition.to_graph())
    except CycleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive; to_graph already validated
        raise HTTPException(status_code=422, detail=f"orchestration document invalid: {exc}") from exc


def _require_layout(layout: Any) -> dict[str, Any]:
    """layout 仅接受 ``{node_id: {x, y}}`` 形状；损坏/异常一律丢弃（投影可丢失，FR-12）。"""
    if not isinstance(layout, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for node_id, point in layout.items():
        if not isinstance(node_id, str):
            continue
        if not isinstance(point, dict):
            continue
        try:
            x = float(point.get("x"))
            y = float(point.get("y"))
        except (TypeError, ValueError):
            continue
        if x != x or y != y:  # NaN
            continue
        cleaned[node_id] = {"x": x, "y": y}
    return cleaned


async def _assert_can_publish(principal: ApiPrincipal) -> None:
    """001 发布权门禁：未持有 ``orchestration:publish`` 权限码即 fail-closed 拒绝。"""
    if not await can_publish_orchestration(principal.tenant_id, principal.user_id):
        raise GatekeeperDenied(f"missing permission code {PUBLISH_PERMISSION}")


def _overview(document: dict[str, Any]) -> dict[str, Any]:
    header = document.get("orchestration") or {}
    return {
        "orchestrationId": header.get("id"),
        "version": header.get("version"),
        "mode": header.get("mode"),
        "nodeCount": len(document.get("nodes") or []),
        "edgeCount": len(document.get("edges") or []),
    }


# --------------------------------------------------------------------------- list

@router.get("", response_model=ApiResponse)
async def list_orchestrations(
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> ApiResponse:
    """当前用户可见的编排清单（仅自身 + 租户作用域，FR-010 版本化入口）。"""
    db = get_db()
    if db is None:
        return ApiResponse(data=[])
    cursor = db[DAG_DEFINITIONS_COLLECTION].find({"tenant_id": principal.tenant_id}).sort(
        "updated_at", -1
    )
    items: list[dict[str, Any]] = []
    async for doc in cursor:
        items.append(
            {
                "orchestrationId": doc.get("orchestration_id"),
                "version": doc.get("version"),
                "status": doc.get("status", "draft"),
                "mode": (doc.get("document") or {}).get("orchestration", {}).get("mode"),
                "updatedAt": doc.get("updated_at"),
                "detail": _overview(doc.get("document") or {}),
            }
        )
    return ApiResponse(data=items)


# --------------------------------------------------------------------------- read

@router.get("/{orchestration_id}", response_model=ApiResponse)
async def get_orchestration(
    orchestration_id: str,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> ApiResponse:
    """读取单个编排（文档 + 投影布局 + 版本历史）。"""
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="data backend not initialized")
    doc = await db[DAG_DEFINITIONS_COLLECTION].find_one(
        _owning_scope(principal, orchestration_id)
    )
    if doc is None:
        raise HTTPException(status_code=404, detail=f"orchestration {orchestration_id!r} not found")
    return ApiResponse(
        data={
            "orchestrationId": doc.get("orchestration_id"),
            "version": doc.get("version"),
            "status": doc.get("status", "draft"),
            "document": doc.get("document") or {},
            "layout": _require_layout(doc.get("layout")),
            "history": doc.get("history") or [],
            "updatedAt": doc.get("updated_at"),
        }
    )


# --------------------------------------------------------------------------- draft

@router.post("/{orchestration_id}/drafts", response_model=ApiResponse)
async def save_orchestration_draft(
    orchestration_id: str,
    payload: OrchestrationDocumentPayload,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> ApiResponse:
    """保存草稿：校验通过后落库（``status=draft``）。编排权 = 本人。"""
    document = payload.document
    header = document.get("orchestration") or {}
    if str(header.get("id") or "") != orchestration_id:
        raise HTTPException(status_code=422, detail="orchestration.id must match the URL id")
    _validate_document(document)

    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="data backend not initialized")

    version = _next_version(await db[DAG_DEFINITIONS_COLLECTION].find_one(
        _owning_scope(principal, orchestration_id)
    ))
    now = _utcnow()
    document = dict(document)
    document["orchestration"] = dict(header)
    document["orchestration"]["version"] = str(version)

    await _upsert(
        db,
        _owning_scope(principal, orchestration_id),
        {
            "orchestration_id": orchestration_id,
            "tenant_id": principal.tenant_id,
            "user_id": principal.user_id,
            "version": version,
            "status": "draft",
            "document": document,
            "layout": _require_layout(payload.layout),
            "updated_at": now,
        },
        {"created_at": now},
    )
    return ApiResponse(data={"orchestrationId": orchestration_id, "version": version, "status": "draft"})


# --------------------------------------------------------------------------- publish

@router.post("/{orchestration_id}/publish", response_model=ApiResponse)
async def publish_orchestration(
    orchestration_id: str,
    payload: PublishPayload,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> ApiResponse:
    """发布：同口径校验 + 001 发布权门禁，通过后 bump 版本并标记 ``published``。"""
    try:
        await _assert_can_publish(principal)
    except GatekeeperDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    document = payload.document
    header = document.get("orchestration") or {}
    if str(header.get("id") or "") != orchestration_id:
        raise HTTPException(status_code=422, detail="orchestration.id must match the URL id")
    _validate_document(document)

    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="data backend not initialized")

    existing = await db[DAG_DEFINITIONS_COLLECTION].find_one(
        _owning_scope(principal, orchestration_id)
    )
    previous = int(existing.get("version") or 0) if existing else 0
    version = previous + 1
    now = _utcnow()

    document = dict(document)
    document["orchestration"] = dict(header)
    document["orchestration"]["version"] = str(version)

    history = list(existing.get("history") or [])
    if existing and existing.get("document"):
        history.append(
            {
                "version": existing.get("version"),
                "status": existing.get("status", "draft"),
                "document": existing.get("document"),
                "layout": _require_layout(existing.get("layout")),
                "updatedAt": existing.get("updated_at"),
                "releaseNotes": payload.release_notes,
            }
        )

    await _upsert(
        db,
        _owning_scope(principal, orchestration_id),
        {
            "orchestration_id": orchestration_id,
            "tenant_id": principal.tenant_id,
            "user_id": principal.user_id,
            "version": version,
            "status": "published",
            "document": document,
            "layout": _require_layout(payload.layout),
            "history": history,
            "updated_at": now,
        },
        {"created_at": now},
    )
    return ApiResponse(
        data={"orchestrationId": orchestration_id, "version": version, "status": "published"}
    )


# --------------------------------------------------------------------------- helpers

def _next_version(existing: dict[str, Any] | None) -> int:
    return (int(existing.get("version") or 0) + 1) if existing else 1


async def _upsert(db: Any, scope: dict[str, Any], values: dict[str, Any], insert: dict[str, Any]) -> None:
    await db[DAG_DEFINITIONS_COLLECTION].update_one(
        scope,
        {"$set": values, "$setOnInsert": insert},
        upsert=True,
    )