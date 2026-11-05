"""项目读路径（049 收口：读 046 统一后的 ``projects`` 表，``quota_projects`` 退役）。

042 时代本模块维护 ``quota_projects`` 项目分组（成员内嵌数组）。046（ADR-8）
把「项目」实体统一到 ``projects`` 表（chat-api 写入，``_id = workspace_id``），
046 FR-012 明确 ``quota_projects`` 成员内嵌数组下线；049（ADR-9）进一步给
``projects`` 加 ``member_user_ids``，项目层配额成员口径 = 成员 ∪ 创建者。

本模块只承载**组织级配额的项目层读路径**：``list_projects`` / ``get_project``
读 ``projects``，``project_view`` 映射为前端 ``QuotaProject`` 契约（``name`` ←
``title``）。``quota_projects`` 表 0 行、无写方（2026-11-05 核查），彻底退役：
不删表壳、不迁移。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.core.db import get_db
from app.core.quota_policy import utc_now

logger = logging.getLogger(__name__)

# 049: 项目实体在 046 统一到 projects 表（chat-api 写入）；quota_projects 退役。
PROJECT_COLLECTION = "projects"
MAX_NAME_LENGTH = 64
MAX_NOTE_LENGTH = 200
MAX_MEMBERS = 5000
# projects 表 status 域（046 FR-002）：active | archived
VALID_STATUSES = ("active", "archived")


def normalize_members(values: Any) -> list[str]:
    """去重保序、丢弃空值、截断到上限（049 FR-001 的规模上界）。"""

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


def project_view(doc: dict[str, Any] | None) -> dict[str, Any]:
    """DB 行（projects）→ camelCase 视图（前端 ``QuotaProject`` 契约）。

    049：``name`` ← ``title``、``memberUserIds`` ← ``member_user_ids or []``
    （创建者不落此字段，ADR-9 OQ-4）、``status`` ∈ active|archived（046 FR-002）。
    """

    row = doc or {}
    created = row.get("created_at")
    updated = row.get("updated_at")
    return {
        "id": str(row.get("_id") or ""),
        "tenantId": str(row.get("tenant_id") or ""),
        "name": str(row.get("title") or row.get("name") or ""),
        "note": str(row.get("note") or ""),
        "memberUserIds": [str(item) for item in (row.get("member_user_ids") or [])],
        "memberCount": len(row.get("member_user_ids") or []),
        "status": str(row.get("status") or "active"),
        "createdAt": created.isoformat() if hasattr(created, "isoformat") else "",
        "updatedAt": updated.isoformat() if hasattr(updated, "isoformat") else "",
    }


async def list_projects(tenant_id: str, *, include_deleted: bool = False) -> list[dict[str, Any]]:
    """项目列表（049：读 projects；archived 也返回，由前端「已归档」分组消费）。"""

    db = get_db()
    query: dict[str, Any] = {"tenant_id": tenant_id}
    rows = await db[PROJECT_COLLECTION].find(query).to_list(length=2000)
    return [project_view(row) for row in rows]


async def get_project(tenant_id: str, project_id: str) -> dict[str, Any] | None:
    db = get_db()
    doc = await db[PROJECT_COLLECTION].find_one({"tenant_id": tenant_id, "_id": project_id})
    return doc


# 049 FR-007：写端点（POST/PUT/DELETE /projects）已下线，项目只能由 user-web 创建。
# 以下函数保留为 042 时代的历史实现，标记退役——无任何调用方；若未来需要
# "组织级自定义分组"（与 projects 实体无关）再单独立项，不复用这些函数。


async def create_project(
    tenant_id: str,
    *,
    name: str,
    note: str = "",
    member_user_ids: Any = None,
    actor: str = "",
) -> dict[str, Any]:
    """[049 退役] 042 时代新建 quota_projects 分组；049 起无调用方。"""

    normalized_name = str(name or "").strip()[:MAX_NAME_LENGTH]
    if not normalized_name:
        raise ValueError("项目名称不能为空")
    raise RuntimeError("049：quota_projects 写路径已退役，项目由 user-web 创建（见 ADR-9）")


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
    """[049 退役] 042 时代局部更新 quota_projects；049 起无调用方。"""

    raise RuntimeError("049：quota_projects 写路径已退役，项目由 user-web 创建（见 ADR-9）")


async def delete_project(tenant_id: str, project_id: str, *, actor: str = "") -> bool:
    """[049 退役] 042 时代软删除 quota_projects；049 起无调用方。"""

    raise RuntimeError("049：quota_projects 写路径已退役，项目由 user-web 创建（见 ADR-9）")


async def active_project_exists(tenant_id: str, project_id: str) -> bool:
    """049：项目是否存在且未归档（projects.status == active）。"""

    db = get_db()
    doc = await db[PROJECT_COLLECTION].find_one(
        {"tenant_id": tenant_id, "_id": project_id, "status": "active"}
    )
    return doc is not None
