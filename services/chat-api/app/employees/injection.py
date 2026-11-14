"""会话注入协议（051 FR-002 / FR-003 / FR-010）。

员工档案在会话创建时物化为 ``employee_profile`` 快照内嵌会话文档。热路径
（skill 选择 / 工具授权）读取该快照与 006 岗位策略取交集（FR-002：任一拒绝
即拒绝；R4 红线不受员工档案影响——001 门禁在 ``run_gate_plan`` 恒生效）。
未声明员工的会话路径零改动（FR-003 零回归硬约束）。
"""

from __future__ import annotations

from typing import Any

from app.core.db import get_db

from .model import EmployeeProfile


def merge_employee_into_session(
    session_doc: dict[str, Any],
    profile: EmployeeProfile,
) -> dict[str, Any]:
    """把员工档案快照内嵌会话文档（创建时一次物化，热路径零额外查询）。"""
    doc = dict(session_doc or {})
    doc["employee_id"] = profile.employee_id
    doc["employee_profile"] = profile.to_document()
    # 模型配置注入（040 模型分级路由）：快照内的 model_config 可覆盖会话模型。
    model_config = dict(profile.model_config or {})
    if model_config:
        doc["employee_model_config"] = model_config
    # 知识库挂载注入：与调用方显式 knowledge_base_ids 取并集（不覆盖调用方）。
    injected_kb = list(dict.fromkeys(str(item) for item in (profile.knowledge_base_ids or []) if str(item)))
    if injected_kb:
        existing = list(dict.fromkeys(str(item) for item in (doc.get("knowledge_base_ids") or []) if str(item)))
        doc["knowledge_base_ids"] = list(dict.fromkeys(existing + injected_kb))
    # 记忆 scope 注入（017 三范围）。
    if profile.memory_scope:
        doc["employee_memory_scope"] = profile.memory_scope
    return doc


def employee_profile_from_session(session_doc: dict[str, Any]) -> EmployeeProfile | None:
    """从会话文档读取已物化的员工档案快照（热路径；无则 None）。"""
    raw = session_doc.get("employee_profile") if isinstance(session_doc, dict) else None
    if not isinstance(raw, dict) or not str(raw.get("employee_id") or ""):
        return None
    return EmployeeProfile(
        employee_id=str(raw.get("employee_id") or ""),
        name=str(raw.get("name") or ""),
        capabilities=dict(raw.get("capabilities") or {}),
        tool_access_mode=str(raw.get("tool_access_mode") or "selected"),
        tool_ids=[str(item) for item in raw.get("tool_ids") or []],
        skill_access_mode=str(raw.get("skill_access_mode") or "selected"),
        skill_ids=[str(item) for item in raw.get("skill_ids") or []],
        knowledge_base_ids=[str(item) for item in raw.get("knowledge_base_ids") or []],
        memory_scope=str(raw.get("memory_scope") or "personal"),
        model_config=dict(raw.get("model_config") or {}),
        harness_profile_ref=str(raw.get("harness_profile_ref") or ""),
    )


async def employee_profile_for_session(db: Any, session_doc: dict[str, Any]) -> EmployeeProfile | None:
    """热路径读取：优先取会话内快照（零额外查询），回退读取当前员工文档。"""
    profile = employee_profile_from_session(session_doc)
    if profile is not None:
        return profile
    employee_id = str((session_doc or {}).get("employee_id") or "")
    if not employee_id:
        return None
    row = await db["employees"].find_one({"_id": employee_id, "deleted_at": None})
    if not row or str(row.get("status") or "") != "active":
        return None
    return EmployeeProfile.from_document(row)


__all__ = [
    "merge_employee_into_session",
    "employee_profile_from_session",
    "employee_profile_for_session",
]
