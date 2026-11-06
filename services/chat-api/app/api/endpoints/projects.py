"""Durable metadata for Code projects (046 FR-001/FR-013).

The local DSH workspace registry owns the filesystem binding.  This endpoint
persists the user-visible project record separately, so an empty project is
not dependent on a first chat session being created.

The collection was renamed from ``desktop_projects`` to ``projects`` (046 D6);
the HTTP contract (``/projects`` path, ``workspace_id`` / ``title`` /
``worktree`` response fields) is deliberately unchanged.

A default project (externally ``_id = "default"``) is provisioned **per tenant**
on first list access (046 FR-003 / D2) and reused as the fallback for sessions
without a binding (046 FR-004). Mongo ``_id`` is collection-wide unique, so the
storage primary key is tenant-scoped (``default:<tenant_id>``) while the HTTP
contract keeps the stable ``"default"`` id; see ``_serialize_project``.

049-project-members: projects carry ``member_user_ids`` (creator stays in
``user_id``). ``GET /projects`` returns 「我的 ∪ 我作为成员的 ∪ 本租户默认项目」;
``PATCH /projects/{id}`` lets only the creator change members. The member
picker reads ``GET /projects/departments`` (active org_units) and
``GET /projects/member-candidates`` (active end_users, filtered by department
subtree through ``end_user_org_relations``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.api.endpoints.auth import _resolve_session_user
from app.core.db import get_db
from app.core.tenant import add_tenant_scope, resolve_tenant_id


router = APIRouter(tags=["projects"])

logger = logging.getLogger(__name__)

#: 对外契约 id：HTTP 响应、session.project_id、前端虚拟分组键都用这个值。
DEFAULT_PROJECT_ID = "default"

#: Mongo 的 `_id` 是集合级全局唯一，而默认项目按租户各有一份，因此物理主键
#: 按租户分片；对外仍固定暴露 ``DEFAULT_PROJECT_ID``。早期实现直接用
#: ``"default"`` 当物理主键，第二个租户访问时 upsert 匹配不到却试图 INSERT
#: 同 _id 文档，触发 E11000 → GET /projects 500。
DEFAULT_PROJECT_DOC_PREFIX = "default:"


def _default_project_doc_id(tenant_id: str) -> str:
    return f"{DEFAULT_PROJECT_DOC_PREFIX}{tenant_id}"


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
    raw_id = str(doc.get("_id") or "")
    # 默认项目物理主键按租户分片（或历史裸 "default"），对外统一暴露 "default"，
    # 保证 046/049 的 HTTP、session.project_id 与前端虚拟分组键契约不变。
    if (
        doc.get("is_default")
        or raw_id == DEFAULT_PROJECT_ID
        or raw_id.startswith(DEFAULT_PROJECT_DOC_PREFIX)
    ):
        raw_id = DEFAULT_PROJECT_ID
    return {
        "_id": raw_id,
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


def _emit_member_change_audit(
    *,
    project_id: str,
    tenant_id: str,
    actor: str,
    owner_id: str,
    before: list[str],
    after: list[str] | None,
    occurred_at: datetime,
) -> None:
    """C-7（017 design §9.4）：成员 diff → 001 审计（``feature="049"``）。

    ``after is None`` 表示本次 PATCH 未携带 ``member_user_ids``（只改
    title/status）；diff 为空同样不发事件。审计调用失败只留观测日志，绝不
    阻断主流程、不改变响应码/响应结构，也不触碰 049 既有写入语义。
    """
    if after is None:
        return
    before_set, after_set = set(before), set(after)
    added = [m for m in after if m not in before_set]
    removed = [m for m in before if m not in after_set]
    if not added and not removed:
        return

    document = {
        "project_id": project_id,
        "project_owner_id": owner_id,
        "added": added,
        "removed": removed,
        "previous_member_count": len(before),
        "resulting_member_count": len(after),
        "occurred_at": occurred_at.isoformat(),
    }
    events: list[str] = []
    if added:
        events.append("project.member.granted")
    if removed:
        events.append("project.member.revoked")

    try:
        # 与 memory/scope.py 同款纪律：延迟导入，审计桥未接线也不影响导入期。
        from app.services.feature_audit_bridge import emit_feature_event

        for event in events:
            emit_feature_event(
                "049",
                event,
                document,
                tenant_id=tenant_id,
                actor=actor,
            )
    except Exception as exc:  # noqa: BLE001 - 审计绝不阻断 PATCH
        logger.warning(
            "[projects] project.member.* audit emit failed "
            "(project_id=%s, events=%s): %s",
            project_id,
            events,
            exc,
        )


async def _ensure_default_project(tenant_id: str, user_id: str) -> None:
    """幂等生成**本租户**的默认项目（046 FR-003 / D2）。

    仿 `directory_repository.ensure_root_department` 的写法：`$setOnInsert` 保
    首次创建、`$set` 保更新时间、`upsert=True` 保重复调用不产生第二条。

    多租户是这里的根本约束：Mongo 的 `_id` 是集合级全局唯一，而默认项目按
    租户各有一份，所以物理主键必须带租户维度（`default:<tenant_id>`）。早期
    实现直接用裸 `"default"` 当物理主键，第二个租户访问时无论 filter 带不带
    (tenant_id, user_id) 都会撞同一个主键：带 scope 则 upsert 匹配不到却试图
    INSERT 触发 E11000 → GET /projects 500；不带 scope 则全库只剩一份，第二个
    租户根本看不到默认项目。两种写法都没有真正考虑多租户。

    对外契约不变：`_serialize_project` 仍把默认项目输出成 `_id="default"`，
    session.project_id / 前端虚拟分组键 / PATCH 校验都基于这个值。
    """
    now = datetime.now(tz=timezone.utc)
    doc_id = _default_project_doc_id(tenant_id)
    # 同时兼容历史库里那条裸 `_id="default"` 文档：它属于最初创建它的租户，
    # 命中时只补 is_default 标记，不做数据迁移（sessions 不按该物理 id 引用）。
    # filter 不带 user_id —— 同租户第二个用户访问时应复用已有默认项目，而不是
    # 再插一份；外层 tenant_id 保证跨租户不可互见。
    scope = {
        "tenant_id": tenant_id,
        "_id": {"$in": [doc_id, DEFAULT_PROJECT_ID]},
    }
    await get_db().projects.update_one(
        scope,
        {
            "$setOnInsert": {
                "_id": doc_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "title": "默认项目",
                "status": "active",
                "created_at": now,
            },
            "$set": {"updated_at": now, "is_default": True},
        },
        upsert=True,
    )


@router.post("/projects", response_model=ApiResponse)
async def create_desktop_project(
    payload: DesktopProjectCreate,
    authorization: str | None = Header(default=None),
):
    tenant_id, user_id = await _identity(authorization)
    if payload.workspace_id == DEFAULT_PROJECT_ID or payload.workspace_id.startswith(
        DEFAULT_PROJECT_DOC_PREFIX
    ):
        # 保留 id：否则 $setOnInsert._id 会去撞默认项目的物理主键。
        return ApiResponse(code=400, message="workspace_id 不能使用保留的默认项目标识")
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
    # 046 FR-003: 首次访问的租户立刻能看到自己的默认项目分组。
    await _ensure_default_project(tenant_id, user_id)
    # 049 FR-002: 可见性 = 「我的 ∪ 我作为成员的 ∪ 本租户默认项目」。
    # 外层 tenant_id 是硬边界：默认项目物理主键按租户分片，is_default 行只会在
    # 当前租户内命中，不会把别的租户的默认项目泄露过来。
    # 同时保留裸 _id="default" 兼容分支，覆盖尚未打标的历史文档。
    visible = {
        "tenant_id": tenant_id,
        "$or": [
            {"user_id": user_id},
            {"member_user_ids": user_id},
            {"is_default": True},
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
    if project_id == DEFAULT_PROJECT_ID or project_id.startswith(DEFAULT_PROJECT_DOC_PREFIX):
        # 对外 id 与物理分片 id 都不可改，防止绕过 046 Edge Case 3。
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
    # C-7（017 design §9.4）：仅在 update_one 成功之后、返回响应之前按成员 diff
    # 落审计；只改 title/status 或 diff 为空不发，失败只留观测日志不阻断 PATCH。
    _emit_member_change_audit(
        project_id=project_id,
        tenant_id=tenant_id,
        actor=user_id,
        owner_id=str(existing.get("user_id") or ""),
        before=list(existing.get("member_user_ids") or []),
        after=set_value.get("member_user_ids"),
        occurred_at=now,
    )
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
