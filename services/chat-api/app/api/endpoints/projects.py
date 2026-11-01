"""Durable metadata for Code projects (046 FR-001/FR-013).

The local DSH workspace registry owns the filesystem binding.  This endpoint
persists the user-visible project record separately, so an empty project is
not dependent on a first chat session being created.

The collection was renamed from ``desktop_projects`` to ``projects`` (046 D6);
the HTTP contract (``/projects`` path, ``workspace_id`` / ``title`` /
``worktree`` response fields) is deliberately unchanged.

A default project (``_id = "default"``) is provisioned on first list access
(046 FR-003 / D2) and reused as the fallback for sessions without a binding
(046 FR-004).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.api.endpoints.auth import _resolve_session_user
from app.core.db import get_db
from app.core.tenant import resolve_tenant_id


router = APIRouter(tags=["projects"])

DEFAULT_PROJECT_ID = "default"


class DesktopProjectCreate(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=200)
    worktree: bool = False


class ApiResponse(BaseModel):
    code: int = 0
    message: str | None = None
    data: object | None = None


class ProjectPatch(BaseModel):
    """只允许变更 `status`（046 FR-009 / Edge Case 3：默认项目不可归档）。"""
    status: str = Field(..., description="active | archived")


def _serialize_project(doc: dict) -> dict:
    return {
        "_id": str(doc.get("_id") or ""),
        "tenant_id": str(doc.get("tenant_id") or ""),
        "user_id": str(doc.get("user_id") or ""),
        "workspace_id": str(doc.get("workspace_id") or ""),
        "title": str(doc.get("title") or ""),
        "worktree": bool(doc.get("worktree")),
        "status": str(doc.get("status") or "active"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


async def _identity(authorization: str | None) -> tuple[str, str]:
    resolved = await _resolve_session_user(authorization if isinstance(authorization, str) else None)
    return resolve_tenant_id(resolved["tenant_id"]), str(resolved["user"].get("_id") or "")


async def _ensure_default_project(tenant_id: str, user_id: str) -> None:
    """幂等生成 `_id = "default"` 的默认项目（046 FR-003 / D2）。

    仿 `directory_repository.ensure_root_department` 的写法：`$setOnInsert` 保
    首次创建、`$set` 保更新时间、`upsert=True` 保重复调用不产生第二条。

    `_id = "default"` 的项目不可归档、不可删除（046 Edge Case 3）—— 这份约束
    由 `PATCH /projects/{id}` 在服务端校验（046 T025），此处只做生成。
    """
    now = datetime.now(tz=timezone.utc)
    scope = {"tenant_id": tenant_id, "user_id": user_id, "_id": DEFAULT_PROJECT_ID}
    await get_db().projects.update_one(
        scope,
        {
            "$setOnInsert": {
                "_id": DEFAULT_PROJECT_ID,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "title": "默认项目",
                "status": "active",
                "created_at": now,
            },
            "$set": {"updated_at": now},
        },
        upsert=True,
    )


@router.post("/projects", response_model=ApiResponse)
async def create_desktop_project(
    payload: DesktopProjectCreate,
    authorization: str | None = Header(default=None),
):
    tenant_id, user_id = await _identity(authorization)
    now = datetime.now(tz=timezone.utc)
    scope = {"tenant_id": tenant_id, "user_id": user_id, "workspace_id": payload.workspace_id}
    await get_db().projects.update_one(
        scope,
        {
            "$setOnInsert": {
                "_id": payload.workspace_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "status": "active",
                "created_at": now,
            },
            "$set": {"title": payload.title.strip(), "worktree": payload.worktree, "updated_at": now},
        },
        upsert=True,
    )
    project = await get_db().projects.find_one(scope)
    return ApiResponse(data=_serialize_project(project or {**scope, "title": payload.title, "worktree": payload.worktree, "created_at": now, "updated_at": now}))


@router.get("/projects", response_model=ApiResponse)
async def list_desktop_projects(authorization: str | None = Header(default=None)):
    tenant_id, user_id = await _identity(authorization)
    # 046 FR-003: 首次访问的 (tenant, user) 立刻能看到默认项目分组。
    await _ensure_default_project(tenant_id, user_id)
    cursor = get_db().projects.find({"tenant_id": tenant_id, "user_id": user_id}).sort("updated_at", -1)
    return ApiResponse(data=[_serialize_project(item) async for item in cursor])


@router.patch("/projects/{project_id}", response_model=ApiResponse)
async def patch_project(
    project_id: str,
    payload: ProjectPatch,
    authorization: str | None = Header(default=None),
):
    """只接受 `status` 变更；`_id = "default"` 返回 400（046 Edge Case 3）。"""
    tenant_id, user_id = await _identity(authorization)
    if project_id == DEFAULT_PROJECT_ID:
        return ApiResponse(code=400, message="默认项目不可归档或删除")
    now = datetime.now(tz=timezone.utc)
    scope = {"tenant_id": tenant_id, "user_id": user_id, "_id": project_id}
    outcome = await get_db().projects.update_one(
        scope, {"$set": {"status": payload.status, "updated_at": now}}
    )
    if outcome.matched_count == 0:
        return ApiResponse(code=404, message="项目不存在")
    project = await get_db().projects.find_one(scope)
    return ApiResponse(data=_serialize_project(project))
