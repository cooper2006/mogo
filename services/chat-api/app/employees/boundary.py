"""员工能力边界热路径执法（051 FR-002）。

员工白名单与 001 门禁取交集：员工边界只做「额外收窄」——任一拒绝即拒绝，
**不得**实现为「员工白名单绕过门禁」。R4 红线不受员工档案影响（001 门禁在
``run_gate_plan`` 恒生效）。

热路径只读会话内快照（``chat_sessions.employee_profile``），不重复查员工表
（plan.md Performance Goals）。
"""

from __future__ import annotations

from typing import Any

from app.core.db import get_db
from app.core.tenant import add_tenant_scope

from .injection import employee_profile_from_session

#: 001 单一审计汇（gate_events），与员工审计同 schema。
AUDIT_COLLECTION = "gate_events"


async def session_employee_profile(db: Any, session_id: str) -> Any | None:
    """热路径读取会话员工档案快照（无则 None；未知会话也返回 None）。"""
    if not session_id:
        return None
    try:
        from app.core.ids import to_backend_id

        oid = to_backend_id(str(session_id))
    except Exception:
        return None
    row = await db.chat_sessions.find_one({"_id": oid}, {"employee_profile": 1})
    if not row:
        return None
    return employee_profile_from_session(row)


async def enforce_employee_skill_boundary(
    *,
    tenant_id: str,
    user_id: str,
    session_id: str,
    selected_skill_id: str,
    db: Any | None = None,
) -> bool:
    """员工边界：白名单外 Skill 拒绝（返回 False 表示被拒）。"""
    db = db if db is not None else get_db()
    profile = await session_employee_profile(db, session_id)
    if profile is None:
        return True
    if profile.allows_skill(selected_skill_id):
        return True
    await _audit(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="employee.denied",
        target="skill",
        detail={"skill_id": selected_skill_id, "employee_id": profile.employee_id},
    )
    return False


async def enforce_employee_tool_boundary(
    *,
    tenant_id: str,
    user_id: str,
    session_id: str,
    tool_name: str,
    capability_ref: str = "",
    external_tool_id: str = "",
    db: Any | None = None,
) -> bool:
    """员工边界：白名单外工具 / 能力拒绝（返回 False 表示被拒）。

    * 内部能力（``capability_ref`` 非空）：按能力键判定；
    * 外部工具（``external_tool_id`` 非空）：按工具白名单判定。
    """
    db = db if db is not None else get_db()
    profile = await session_employee_profile(db, session_id)
    if profile is None:
        return True
    if capability_ref:
        allowed = profile.allows_capability(_capability_key(capability_ref))
    else:
        allowed = profile.allows_external_tool(external_tool_id)
    if allowed:
        return True
    await _audit(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="employee.denied",
        target="tool",
        detail={"tool_name": tool_name, "employee_id": profile.employee_id},
    )
    return False


def _capability_key(capability_ref: str) -> str:
    """001 内部能力引用 → 能力键（沿用 006 ``INTERNAL_CAPABILITY_REQUIREMENTS``）。"""
    mapping = {
        "content.produce@v1": "content_generation",
        "presentation.create@v1": "content_generation",
        "document.pdf_retain_pages@v1": "content_generation",
        "image.generate@v1": "image_generation",
        "browser.task@v1": "browser_automation",
        "knowledge.search@v1": "internal_knowledge",
    }
    return mapping.get(str(capability_ref or ""), str(capability_ref or ""))


async def _audit(
    db: Any,
    *,
    tenant_id: str,
    user_id: str,
    action: str,
    target: str,
    detail: dict[str, Any],
) -> None:
    import uuid
    from datetime import datetime, timezone

    try:
        await db[AUDIT_COLLECTION].insert_one(
            {
                "event_id": uuid.uuid4().hex,
                "occurred_at": datetime.now(timezone.utc),
                "tenant_id": tenant_id,
                "user_id": str(user_id or ""),
                "roles": [],
                "tool": action,
                "risk_level": "",
                "autonomy_level": "",
                "decision": "deny",
                "layer": "employee",
                "reason": action,
                "detail": dict(detail),
            }
        )
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "employee boundary audit failed tenant=%s action=%s", tenant_id, action
        )


__all__ = [
    "enforce_employee_skill_boundary",
    "enforce_employee_tool_boundary",
    "session_employee_profile",
]
