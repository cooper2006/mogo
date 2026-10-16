"""本体数据权限 —— 主体集合展开（与 chat-api 运行时同源）。

把 ``(tenant_id, user_id)`` 展开成 ``mesc_ontology_grant`` 的**四态主体集合**：

* ``tenant`` —— 租户兜底行（"整套只看一个租户"）。
* ``org``    —— 该用户的组织 **含下级**（``end_user_org_relations`` + ``org_units.path_ids`` 展开）。
* ``role``   —— 该用户的岗位角色（``end_user_position_roles``）。
* ``user``   —— 用户自身。

这些主体侧表都是**通用壳表**（``id/tenant_id/doc``），两种后端都支持，故直接走
``get_db()`` 门面；只有 ``mesc_*`` 与 ``sys_config`` 是结构化表、走原生 SQL。

镜像自 ``services/chat-api/app/services/ontology_permission.py::NativeSubjectProvider``。
两处必须同步修改。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.core.db import get_db

logger = logging.getLogger(__name__)

USER_ORG_REL_TABLE = "end_user_org_relations"
USER_ROLE_TABLE = "end_user_position_roles"
ORG_UNIT_TABLE = "org_units"


@dataclass(frozen=True)
class SubjectSet:
    tenant_id: str
    user_id: str
    org_ids: frozenset[str] = frozenset()
    role_ids: frozenset[str] = frozenset()

    def subjects(self) -> tuple[tuple[str, str], ...]:
        rows: list[tuple[str, str]] = [("tenant", self.tenant_id)]
        rows += [("org", org_id) for org_id in sorted(self.org_ids)]
        rows += [("role", role_id) for role_id in sorted(self.role_ids)]
        rows += [("user", self.user_id)]
        return tuple(rows)


class SubjectExpander:
    """从通用壳表读取用户的组织（含下级）与岗位角色。"""

    def __init__(self, db: Any | None = None) -> None:
        self._db_override = db

    def _db(self) -> Any:
        db = self._db_override if self._db_override is not None else get_db()
        if db is None:
            raise RuntimeError("数据后端未初始化")
        return db

    async def expand(self, tenant_id: str, user_id: str) -> SubjectSet:
        db = self._db()
        org_ids: set[str] = set()
        org_rows = await db[USER_ORG_REL_TABLE].find(
            {"tenant_id": tenant_id, "user_id": user_id, "status": "active"}
        ).to_list(length=500)
        for row in org_rows:
            org_id = str(row.get("org_id") or "")
            if org_id:
                org_ids.add(org_id)
        if org_ids:
            # 组织含下级：org_units.path_ids 为祖先链，凡路径经过用户组织的即为其后代。
            unit_rows = await db[ORG_UNIT_TABLE].find(
                {"tenant_id": tenant_id, "status": "active"}
            ).to_list(length=2000)
            for unit in unit_rows:
                path = [str(item) for item in (unit.get("path_ids") or [])]
                if any(item in org_ids for item in path):
                    org_ids.add(str(unit.get("_id")))
        role_rows = await db[USER_ROLE_TABLE].find(
            {"tenant_id": tenant_id, "user_id": user_id, "status": "active"}
        ).to_list(length=500)
        role_ids = {
            str(row.get("role_id") or row.get("position_id"))
            for row in role_rows
            if (row.get("role_id") or row.get("position_id"))
        }
        return SubjectSet(
            tenant_id=tenant_id,
            user_id=user_id,
            org_ids=frozenset(org_ids),
            role_ids=frozenset(role_ids),
        )


__all__ = ["ORG_UNIT_TABLE", "USER_ORG_REL_TABLE", "USER_ROLE_TABLE", "SubjectExpander", "SubjectSet"]
