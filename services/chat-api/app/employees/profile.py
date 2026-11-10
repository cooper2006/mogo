"""档案物化（051 FR-003 / FR-010 / Edge Cases）。

会话创建时一次性物化 ``EmployeeProfile`` 快照（引用校验 + 快照），注入只发生
在创建时——在途会话不受档案变更影响（FR-010），热路径零额外员工表查询
（plan.md Performance Goals）。引用资产失效按 OQ-2 未定口径采取「显式报错」
（Edge Cases：不静默使用失效资产），后续 clarify 可切降级策略。
"""

from __future__ import annotations

from typing import Any

from app.core.db import get_db
from app.core.tenant import add_tenant_scope

from .model import EmployeeProfile

#: OQ-2 未定口径前的默认策略：引用失效显式报错（不静默降级）。
REFERENCE_POLICY = "reject"


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
    """校验档案引用（Edge Cases：无效引用显式报错，不静默使用失效资产）。

    * 工具：必须存在且 enabled（企业级 external_tools 集合）；
    * Skill：必须存在且 enabled（skills 集合）；
    * 知识库：必须存在（005 口径）；
    * Harness profile：存在即放行（019 引用，允许空）。
    """
    db = db if db is not None else get_db()
    errors: list[str] = []

    unique_tool_ids = list(dict.fromkeys(str(item) for item in (tool_ids or []) if str(item)))
    if unique_tool_ids:
        count = await db.external_tools.count_documents(
            add_tenant_scope({"_id": {"$in": unique_tool_ids}, "enabled": True}, tenant_id)
        )
        if count != len(unique_tool_ids):
            errors.append("包含不存在或未启用的 MCP/工具")

    unique_skill_ids = list(dict.fromkeys(str(item) for item in (skill_ids or []) if str(item)))
    if unique_skill_ids:
        count = await db.skills.count_documents(
            add_tenant_scope({"_id": {"$in": unique_skill_ids}, "enabled": True}, tenant_id)
        )
        if count != len(unique_skill_ids):
            errors.append("包含不存在或未启用的企业 Skill")

    unique_kb_ids = list(dict.fromkeys(str(item) for item in (knowledge_base_ids or []) if str(item)))
    if unique_kb_ids:
        try:
            count = await db.knowledge_documents.count_documents(
                add_tenant_scope({"_id": {"$in": unique_kb_ids}}, tenant_id)
            )
        except Exception:
            count = 0
        if count != len(unique_kb_ids):
            errors.append("包含不存在或不可用的知识库")

    if errors:
        raise EmployeeReferenceError("；".join(errors))


async def materialize_employee_profile(
    tenant_id: str,
    employee_id: str,
    db: Any | None = None,
) -> EmployeeProfile | None:
    """读取员工文档并物化档案快照（引用校验 + 快照）。

    返回 ``None`` 表示员工不存在 / 已软删除 / 非 active（调用方 fail-closed）。
    """
    db = db if db is not None else get_db()
    row = await db["employees"].find_one(
        add_tenant_scope({"_id": str(employee_id), "deleted_at": None}, tenant_id)
    )
    if not row:
        return None
    if str(row.get("status") or "") != "active":
        return None
    profile = EmployeeProfile.from_document(row)
    await validate_employee_references(
        tenant_id,
        tool_ids=profile.tool_ids,
        skill_ids=profile.skill_ids,
        knowledge_base_ids=profile.knowledge_base_ids,
        harness_profile_ref=profile.harness_profile_ref,
        db=db,
    )
    return profile


__all__ = ["EmployeeProfile", "EmployeeReferenceError", "materialize_employee_profile", "validate_employee_references"]
