"""042-three-level-quota: 项目分组（``quota_projects``）维护。

与桌面 Code 的 ``projects`` 端点语义隔离（后者是
``services/chat-api/app/api/endpoints/projects.py`` 的工作区绑定，docstring 明示
"persists the user-visible project record"）；本模块只承载组织级配额的项目层，
是跨部门的横向协作分组，**不内嵌额度字段**（额度仍存 ``user_quota_policies``
的 ``scope_type="project"`` 行，见 spec R-4），避免双写。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.core.db import get_db
from app.core.quota_policy import utc_now

logger = logging.getLogger(__name__)

PROJECT_COLLECTION = "quota_projects"
MAX_NAME_LENGTH = 64
MAX_NOTE_LENGTH = 200
MAX_MEMBERS = 5000
VALID_STATUSES = ("active", "disabled", "deleted")


def normalize_members(values: Any) -> list[str]:
    """去重保序、丢弃空值、截断到上限（spec R-5 的规模上界）。"""

    if not isinstance(values, (list, tuple, set)):
        return []
    seen: set[str] = set()
    members: list[str] = []
    for raw in values:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        members.append(item)
        if len(members) >= MAX_MEMBERS:
            break
    return members


def normalize_name(value: Any) -> str:
    return str(value or "").strip()[:MAX_NAME_LENGTH]


def normalize_note(value: Any) -> str:
    return str(value or "").strip()[:MAX_NOTE_LENGTH]


def normalize_status(value: Any) -> str:
    status = str(value or "active").strip().lower()
    return status if status in VALID_STATUSES else "active"


def project_view(doc: dict[str, Any] | None) -> dict[str, Any]:
    """DB 行 → camelCase 视图（前端直接消费）。"""

    row = doc or {}
    created = row.get("created_at")
    updated = row.get("updated_at")
    return {
        "id": str(row.get("_id") or ""),
        "tenantId": str(row.get("tenant_id") or ""),
        "name": str(row.get("name") or ""),
        "note": str(row.get("note") or ""),
        "memberUserIds": [str(item) for item in (row.get("member_user_ids") or [])],
        "memberCount": len(row.get("member_user_ids") or []),
        "status": str(row.get("status") or "active"),
        "createdAt": created.isoformat() if hasattr(created, "isoformat") else "",
        "updatedAt": updated.isoformat() if hasattr(updated, "isoformat") else "",
    }


async def list_projects(tenant_id: str, *, include_deleted: bool = False) -> list[dict[str, Any]]:
    db = get_db()
    query: dict[str, Any] = {"tenant_id": tenant_id}
    if not include_deleted:
        query["status"] = {"$ne": "deleted"}
    rows = await db[PROJECT_COLLECTION].find(query).to_list(length=2000)
    return [project_view(row) for row in rows]


async def get_project(tenant_id: str, project_id: str) -> dict[str, Any] | None:
    db = get_db()
    doc = await db[PROJECT_COLLECTION].find_one({"tenant_id": tenant_id, "_id": project_id})
    return doc


async def create_project(
    tenant_id: str,
    *,
    name: str,
    note: str = "",
    member_user_ids: Any = None,
    actor: str = "",
) -> dict[str, Any]:
    """新建项目分组；``name`` 在租户内唯一（软删除行不计入，spec R-4）。"""

    normalized_name = normalize_name(name)
    if not normalized_name:
        raise ValueError("项目名称不能为空")
    db = get_db()
    existing = await db[PROJECT_COLLECTION].find_one(
        {"tenant_id": tenant_id, "name": normalized_name, "status": {"$ne": "deleted"}}
    )
    if existing:
        raise FileExistsError(f"项目名称已存在：{normalized_name}")
    now = utc_now()
    document = {
        "_id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "name": normalized_name,
        "note": normalize_note(note),
        "member_user_ids": normalize_members(member_user_ids),
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "created_by": str(actor or ""),
        "updated_by": str(actor or ""),
    }
    await db[PROJECT_COLLECTION].insert_one(document)
    return document


async def update_project(
    tenant_id: str,
    project_id: str,
    *,
    name: Any = None,
    note: Any = None,
    member_user_ids: Any = None,
    status: Any = None,
    actor: str = "",
) -> dict[str, Any] | None:
    """局部更新；``member_user_ids`` 传空列表表示清空成员。"""

    db = get_db()
    existing = await db[PROJECT_COLLECTION].find_one({"tenant_id": tenant_id, "_id": project_id})
    if not existing:
        return None
    patch: dict[str, Any] = {"updated_at": utc_now(), "updated_by": str(actor or "")}
    if name is not None:
        normalized_name = normalize_name(name)
        if not normalized_name:
            raise ValueError("项目名称不能为空")
        clash = await db[PROJECT_COLLECTION].find_one(
            {
                "tenant_id": tenant_id,
                "name": normalized_name,
                "status": {"$ne": "deleted"},
                "_id": {"$ne": project_id},
            }
        )
        if clash:
            raise FileExistsError(f"项目名称已存在：{normalized_name}")
        patch["name"] = normalized_name
    if note is not None:
        patch["note"] = normalize_note(note)
    if member_user_ids is not None:
        patch["member_user_ids"] = normalize_members(member_user_ids)
    if status is not None:
        patch["status"] = normalize_status(status)
    await db[PROJECT_COLLECTION].update_one(
        {"tenant_id": tenant_id, "_id": project_id}, {"$set": patch}
    )
    return await db[PROJECT_COLLECTION].find_one({"tenant_id": tenant_id, "_id": project_id})


async def delete_project(tenant_id: str, project_id: str, *, actor: str = "") -> bool:
    """软删除（``status="deleted"``）——策略行保留可回溯，孤儿策略是预期状态。"""

    db = get_db()
    existing = await db[PROJECT_COLLECTION].find_one({"tenant_id": tenant_id, "_id": project_id})
    if not existing:
        return False
    await db[PROJECT_COLLECTION].update_one(
        {"tenant_id": tenant_id, "_id": project_id},
        {"$set": {"status": "deleted", "updated_at": utc_now(), "updated_by": str(actor or "")}},
    )
    return True


async def active_project_exists(tenant_id: str, project_id: str) -> bool:
    db = get_db()
    doc = await db[PROJECT_COLLECTION].find_one(
        {"tenant_id": tenant_id, "_id": project_id, "status": "active"}
    )
    return doc is not None
