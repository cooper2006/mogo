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

049-project-members: projects carry ``member_user_ids`` (creator stays in
``user_id``). ``GET /projects`` returns 「我的 ∪ 我作为成员的 ∪ 本租户默认项目」;
``PATCH /projects/{id}`` lets only the creator change members. The member
picker reads ``GET /projects/departments`` (active org_units) and
``GET /projects/member-candidates`` (active end_users, filtered by department
subtree through ``end_user_org_relations``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.api.endpoints.auth import _resolve_session_user
from app.core.db import get_db
from app.core.tenant import add_tenant_scope, resolve_tenant_id


router = APIRouter(tags=["projects"])

DEFAULT_PROJECT_ID = "default"

# 049 FR-004: 成员候选的数据源（与 admin 用户管理同源）。
DEPARTMENT_COLLECTION = "org_units"
USER_COLLECTION = "end_users"
USER_ORG_REL_COLLECTION = "end_user_org_relations"

#: 049 FR-001: 单个项目的成员上限（spec 规定 500；官方 UI 不会一次选这么多）。
MAX_PROJECT_MEMBERS = 500


class DesktopProjectCreate(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=200)
    worktree: bool = False


class ApiResponse(BaseModel):
    code: int = 0
    message: str | None = None
    data: object | None = None


class ProjectPatch(BaseModel):
    """允许变更 `status`（active | archived）与 `title`（重命名，侧边栏扩展项）。

    046 Edge Case 3：默认项目（``_id = "default"``）不可归档、不可删除；重命名默认
    项目亦拒绝，避免用户把「默认工作区」改名后失去兜底语义。
    """
    status: Optional[str] = Field(None, description="active | archived")
    title: Optional[str] = Field(None, min_length=1, max_length=200, description="项目标题（重命名）")
    member_user_ids: Optional[list[str]] = Field(
        None, description="049 FR-001: 项目成员（仅创建者可改；创建者不落此字段）"
    )


def _serialize_project(doc: dict) -> dict:
    return {
        "_id": str(doc.get("_id") or ""),
        "tenant_id": str(doc.get("tenant_id") or ""),
        "user_id": str(doc.get("user_id") or ""),
        "workspace_id": str(doc.get("workspace_id") or ""),
        "title": str(doc.get("title") or ""),
        "worktree": bool(doc.get("worktree")),
        "status": str(doc.get("status") or "active"),
        "member_user_ids": [str(item) for item in (doc.get("member_user_ids") or []) if str(item)],
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
    # 049 FR-002: 可见性从「我的」扩展为「我的 ∪ 我作为成员的 ∪ 本租户默认项目」。
    # 默认项目 `_id = "default"` 在存储层全局唯一（pg_compat 表主键 id），因此它是
    # 本租户的共享兜底项——所有租户内用户都能看到（046 FR-003/FR-004 的兜底语义）。
    visible = {
        "tenant_id": tenant_id,
        "$or": [
            {"user_id": user_id},
            {"member_user_ids": user_id},
            {"_id": DEFAULT_PROJECT_ID},
        ],
    }
    cursor = get_db().projects.find(visible).sort("updated_at", -1)
    return ApiResponse(data=[_serialize_project(item) async for item in cursor])


@router.patch("/projects/{project_id}", response_model=ApiResponse)
async def patch_project(
    project_id: str,
    payload: ProjectPatch,
    authorization: str | None = Header(default=None),
):
    """更新 `status` / `title` / `member_user_ids`。

    046 Edge Case 3：默认项目（``_id = "default"``）返回 400。
    049 FR-003：只有项目创建者（``doc.user_id``）可修改；其他成员 403。
    """
    tenant_id, user_id = await _identity(authorization)
    if project_id == DEFAULT_PROJECT_ID:
        return ApiResponse(code=400, message="默认项目不可归档或删除")
    db = get_db()
    scope = {"tenant_id": tenant_id, "_id": project_id}
    existing = await db.projects.find_one(scope)
    if not existing:
        return ApiResponse(code=404, message="项目不存在")
    if str(existing.get("user_id") or "") != user_id:
        return ApiResponse(code=403, message="只有项目创建者可以修改项目")

    now = datetime.now(tz=timezone.utc)
    set_value: Dict[str, Any] = {"updated_at": now}
    if payload.status is not None:
        if payload.status not in ("active", "archived"):
            return ApiResponse(code=400, message="项目状态只能是 active 或 archived")
        set_value["status"] = payload.status
    if payload.title is not None:
        title = str(payload.title).strip()
        if not title:
            return ApiResponse(code=400, message="项目标题不能为空")
        set_value["title"] = title[:200]
    if payload.member_user_ids is not None:
        # 049 FR-001：去空、去重保序；创建者不落 member_user_ids（计算时并入 user_id）。
        members: list[str] = []
        for item in payload.member_user_ids:
            member_id = str(item or "").strip()
            if member_id and member_id != user_id and member_id not in members:
                members.append(member_id)
        if len(members) > MAX_PROJECT_MEMBERS:
            return ApiResponse(code=400, message="项目成员数量超出上限")
        set_value["member_user_ids"] = members
    if set(set_value) == {"updated_at"}:
        return ApiResponse(code=400, message="无可更新字段")
    outcome = await db.projects.update_one(scope, {"$set": set_value})
    if outcome.matched_count == 0:
        return ApiResponse(code=404, message="项目不存在")
    project = await db.projects.find_one(scope)
    return ApiResponse(data=_serialize_project(project))


@router.get("/projects/departments", response_model=ApiResponse)
async def list_project_departments(authorization: str | None = Header(default=None)):
    """049 FR-004: 成员弹窗左侧部门树（本租户 active 部门，扁平表 + parentId）。

    租户口径与 ``end_user_session.resolve_session_user`` 保持一致：默认租户
    额外兼容早期未带 ``tenant_id`` / 空值的历史行（严格相等会静默查空）。
    """
    tenant_id, _user_id = await _identity(authorization)
    rows = await get_db()[DEPARTMENT_COLLECTION].find(
        add_tenant_scope({"status": "active"}, tenant_id),
        {"_id": 1, "name": 1, "parent_id": 1, "path_ids": 1},
    ).to_list(length=2000)
    departments = [
        {
            "id": str(row.get("_id") or ""),
            "name": str(row.get("name") or ""),
            "parentId": str(row.get("parent_id") or ""),
            "depth": len(row.get("path_ids") or []),
        }
        for row in rows
    ]
    departments.sort(key=lambda item: (item.get("depth", 0), item.get("name", "")))
    return ApiResponse(data={"departments": departments})


@router.get("/projects/member-candidates", response_model=ApiResponse)
async def list_project_member_candidates(
    department_id: str = "",
    keyword: str = "",
    authorization: str | None = Header(default=None),
):
    """049 FR-004: 项目成员候选（active end_users，可按部门子树过滤）。

    ``department_id`` 非空时按 ``org_units.path_ids`` 取该部门及下级子树，
    再经 ``end_user_org_relations`` 关联到人（与 admin 用户管理同款实现）。

    租户不用请求参数传：由 ``_identity`` 从会话解析，所有查询统一走
    ``add_tenant_scope``（与登录会话校验同口径，兼容无租户标记的历史行）。
    业务条件先攒齐、最后统一套租户 scope，避免 ``$and`` 与顶层条件混用。
    """
    tenant_id, _user_id = await _identity(authorization)
    db = get_db()
    query: Dict[str, Any] = {"status": "active"}
    if keyword.strip():
        pattern = {"$regex": keyword.strip(), "$options": "i"}
        query["$or"] = [
            {"name": pattern},
            {"login_name": pattern},
            {"mobile": pattern},
            {"email": pattern},
        ]
    if department_id:
        children = await db[DEPARTMENT_COLLECTION].find(
            add_tenant_scope({"path_ids": department_id}, tenant_id),
            {"_id": 1},
        ).to_list(length=5000)
        department_ids = [department_id] + [str(row.get("_id") or "") for row in children]
        relation_rows = await db[USER_ORG_REL_COLLECTION].find(
            add_tenant_scope({"org_id": {"$in": department_ids}}, tenant_id),
        ).to_list(length=20000)
        candidate_ids = [str(row.get("user_id") or "") for row in relation_rows if row.get("user_id")]
        if not candidate_ids:
            return ApiResponse(data={"items": [], "total": 0})
        query["_id"] = {"$in": candidate_ids}
    users = await db[USER_COLLECTION].find(
        add_tenant_scope(query, tenant_id)
    ).sort("updated_at", -1).to_list(length=5000)

    # 部门名：优先 is_primary 关系，回退 primary_org_id。
    primary_rows = await db[USER_ORG_REL_COLLECTION].find(
        add_tenant_scope({"is_primary": True}, tenant_id),
    ).to_list(length=20000)
    primary_map = {
        str(row.get("user_id") or ""): str(row.get("org_id") or "")
        for row in primary_rows
        if row.get("user_id")
    }
    department_rows = await db[DEPARTMENT_COLLECTION].find(
        add_tenant_scope({}, tenant_id),
        {"_id": 1, "name": 1},
    ).to_list(length=5000)
    department_name_map = {str(row.get("_id") or ""): str(row.get("name") or "") for row in department_rows}

    items = []
    for user in users:
        uid = str(user.get("_id") or "")
        dept_id = primary_map.get(uid) or str(user.get("primary_org_id") or "")
        items.append({
            "id": uid,
            "name": str(user.get("name") or ""),
            "loginName": str(user.get("login_name") or user.get("username") or ""),
            "mobile": str(user.get("mobile") or ""),
            "email": str(user.get("email") or ""),
            "departmentId": dept_id,
            "departmentName": department_name_map.get(dept_id, ""),
        })
    return ApiResponse(data={"items": items, "total": len(items)})
