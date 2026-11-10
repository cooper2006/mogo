"""档案引用校验（051 Edge Cases / OQ-2）—— admin-api 侧。

与 chat-api ``app/employees/profile.py`` 同口径：引用资产失效时显式报错
（OQ-2 未定口径前不静默降级），管理端创建 / 更新时校验。
"""

from __future__ import annotations

from typing import Any

from app.core.db import get_db
from app.services.organization_tools import organization_tool_query


class EmployeeReferenceError(ValueError):
    """员工档案引用的资产失效 / 不存在。"""


async def validate_employee_references(
    tenant_id: str,
    *,
    tool_ids: list[str] | None = None,
    skill_ids: list[str] | None = None,
    knowledge_base_ids: list[str] | None = None,
    harness_profile_ref: str = "",
    db: Any | None = None,
) -> None:
    db = db if db is not None else get_db()
    errors: list[str] = []

    unique_tool_ids = list(dict.fromkeys(str(item) for item in (tool_ids or []) if str(item)))
    if unique_tool_ids:
        count = await db.external_tools.count_documents(organization_tool_query(
            tenant_id, _id={"$in": unique_tool_ids}, status="active"
        ))
        if count != len(unique_tool_ids):
            errors.append("包含不存在、未启用或非企业级的 MCP/工具")

    unique_skill_ids = list(dict.fromkeys(str(item) for item in (skill_ids or []) if str(item)))
    if unique_skill_ids:
        count = await db.skills.count_documents({
            "tenant_id": tenant_id,
            "_id": {"$in": unique_skill_ids},
            "enabled": True,
        })
        if count != len(unique_skill_ids):
            errors.append("包含不存在或未启用的企业 Skill")

    unique_kb_ids = list(dict.fromkeys(str(item) for item in (knowledge_base_ids or []) if str(item)))
    if unique_kb_ids:
        try:
            count = await db.knowledge_documents.count_documents(
                {"_id": {"$in": unique_kb_ids}}
            )
        except Exception:
            count = 0
        if count != len(unique_kb_ids):
            errors.append("包含不存在或不可用的知识库")

    if errors:
        raise EmployeeReferenceError("；".join(errors))
