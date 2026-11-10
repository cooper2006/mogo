"""数字员工集合访问（051 FR-001 / FR-005 / FR-010）。

双服务共用 ``employees`` 集合（027 门面双后端），口径参照 049 双服务
``quota_policy.py`` 同口径先例。可见性（FR-005）=「我的 ∪ 我参与的」
（049 口径），跨租户 fail-closed（020 口径）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from app.core.db import get_db
from app.core.tenant import add_tenant_scope, resolve_tenant_id

from .model import EMPLOYEE_COLLECTION, EMPLOYEE_STATUSES, Employee, utcnow

#: 001 单一审计汇（gate_events），管理端操作另经 system_audit（宪法 III）。
AUDIT_COLLECTION = "gate_events"


class EmployeeRepository:
    def __init__(self, db: Any | None = None) -> None:
        self.db = db if db is not None else get_db()

    async def ensure_indexes(self) -> None:
        await self.db[EMPLOYEE_COLLECTION].create_index(
            [("tenant_id", 1), ("name", 1)], name="employee_tenant_name"
        )
        await self.db[EMPLOYEE_COLLECTION].create_index(
            [("tenant_id", 1), ("creator_id", 1)], name="employee_tenant_creator"
        )
        await self.db[EMPLOYEE_COLLECTION].create_index(
            [("tenant_id", 1), ("status", 1)], name="employee_tenant_status"
        )

    # --- 基础读写（租户隔离 + 软删除过滤） ----------------------------------

    async def get(self, tenant_id: str, employee_id: str) -> dict[str, Any] | None:
        row = await self.db[EMPLOYEE_COLLECTION].find_one(
            add_tenant_scope({"_id": str(employee_id), "deleted_at": None}, tenant_id)
        )
        return dict(row) if row else None

    async def list_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = await self.db[EMPLOYEE_COLLECTION].find(
            add_tenant_scope({"deleted_at": None}, tenant_id)
        ).sort("created_at", 1).to_list(length=1000)
        return [dict(r) for r in rows]

    async def list_visible(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        """可见性 = 「我的 ∪ 我参与的」（049 口径）。"""
        rows = await self.list_tenant(tenant_id)
        return [r for r in rows if self._visible(r, user_id)]

    @staticmethod
    def _visible(row: dict[str, Any], user_id: str) -> bool:
        if str(user_id or "") == str(row.get("creator_id") or ""):
            return True
        return str(user_id) in {str(item) for item in (row.get("member_user_ids") or [])}

    async def create(
        self, tenant_id: str, payload: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        now = utcnow()
        employee = Employee(
            tenant_id=tenant_id,
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            capabilities=payload.get("capabilities") or {},
            tool_access_mode=str(payload.get("toolAccessMode") or payload.get("tool_access_mode") or "selected"),
            tool_ids=list(payload.get("toolIds", payload.get("tool_ids", [])) or []),
            skill_access_mode=str(payload.get("skillAccessMode") or payload.get("skill_access_mode") or "selected"),
            skill_ids=list(payload.get("skillIds", payload.get("skill_ids", [])) or []),
            knowledge_base_ids=list(payload.get("knowledge_base_ids") or []),
            memory_scope=str(payload.get("memory_scope") or "personal"),
            model_config=dict(payload.get("model_config") or {}),
            harness_profile_ref=str(payload.get("harness_profile_ref") or ""),
            status=str(payload.get("status") or "active"),
            creator_id=str(actor or ""),
            member_user_ids=list(payload.get("member_user_ids") or []),
            employee_id=uuid.uuid4().hex,
        )
        doc = employee.to_document()
        doc["_id"] = employee.employee_id
        doc["created_by"] = str(actor or "")
        await self.db[EMPLOYEE_COLLECTION].insert_one(doc)
        return dict(doc)

    async def update(
        self, tenant_id: str, employee_id: str, payload: dict[str, Any], actor: str
    ) -> dict[str, Any] | None:
        existing = await self.get(tenant_id, employee_id)
        if not existing:
            return None
        patch: dict[str, Any] = {"updated_at": utcnow(), "updated_by": str(actor or "")}
        for field in (
            "name", "description", "capabilities", "knowledge_base_ids", "memory_scope",
            "model_config", "harness_profile_ref", "member_user_ids",
        ):
            if field in payload:
                patch[field] = payload[field]
        if "toolAccessMode" in payload or "tool_access_mode" in payload:
            patch["tool_access_mode"] = str(
                payload.get("toolAccessMode") or payload.get("tool_access_mode") or "selected"
            )
        if "toolIds" in payload or "tool_ids" in payload:
            patch["tool_ids"] = list(payload.get("toolIds", payload.get("tool_ids", [])) or [])
        if "skillAccessMode" in payload or "skill_access_mode" in payload:
            patch["skill_access_mode"] = str(
                payload.get("skillAccessMode") or payload.get("skill_access_mode") or "selected"
            )
        if "skillIds" in payload or "skill_ids" in payload:
            patch["skill_ids"] = list(payload.get("skillIds", payload.get("skill_ids", [])) or [])
        if "status" in payload:
            status = str(payload.get("status") or "")
            if status not in EMPLOYEE_STATUSES:
                raise ValueError(f"invalid status: {status!r}")
            patch["status"] = status
        await self.db[EMPLOYEE_COLLECTION].update_one(
            add_tenant_scope({"_id": employee_id, "deleted_at": None}, tenant_id),
            {"$set": patch},
        )
        return await self.get(tenant_id, employee_id)

    async def set_status(
        self, tenant_id: str, employee_id: str, status: str, actor: str
    ) -> dict[str, Any] | None:
        if status not in EMPLOYEE_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        await self.db[EMPLOYEE_COLLECTION].update_one(
            add_tenant_scope({"_id": employee_id, "deleted_at": None}, tenant_id),
            {"$set": {"status": status, "updated_at": utcnow(), "updated_by": str(actor or "")}},
        )
        return await self.get(tenant_id, employee_id)

    async def soft_delete(self, tenant_id: str, employee_id: str, actor: str) -> bool:
        """软删除（FR-010）：不物理清除运行记录，历史会话保留 employee_id 溯源。"""
        result = await self.db[EMPLOYEE_COLLECTION].update_one(
            add_tenant_scope({"_id": employee_id, "deleted_at": None}, tenant_id),
            {
                "$set": {
                    "deleted_at": utcnow(),
                    "status": "archived",
                    "updated_at": utcnow(),
                    "deleted_by": str(actor or ""),
                }
            },
        )
        return bool(getattr(result, "matched_count", 0))

    # --- 001 审计流（FR-011） ------------------------------------------------

    async def audit(
        self,
        tenant_id: str,
        actor: str,
        action: str,
        target_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """写 gate_events 审计汇（001 单一审计汇同 schema；失败不阻断）。"""
        try:
            await self.db[AUDIT_COLLECTION].insert_one(
                {
                    "event_id": uuid.uuid4().hex,
                    "occurred_at": utcnow(),
                    "tenant_id": tenant_id,
                    "user_id": str(actor or ""),
                    "roles": [],
                    "tool": f"employee.{action}",
                    "risk_level": "",
                    "autonomy_level": "",
                    "decision": "allow",
                    "layer": "employee",
                    "reason": f"employee {action}",
                    "detail": dict(details or {}),
                }
            )
        except Exception:
            # 审计不可用不阻断主流程（001 同口径），但缺口必须可发现。
            import logging

            logging.getLogger(__name__).warning(
                "employee audit write failed tenant=%s action=%s target=%s",
                tenant_id, action, target_id,
            )

    @staticmethod
    def serialize(row: dict[str, Any]) -> dict[str, Any]:
        """员工档案视图（管理端 / 用户侧共用）。"""
        return {
            "id": str(row.get("_id") or row.get("employee_id") or ""),
            "name": str(row.get("name") or ""),
            "description": str(row.get("description") or ""),
            "status": str(row.get("status") or "active"),
            "capabilities": {
                key: bool((row.get("capabilities") or {}).get(key, False))
                for key in ("content_generation", "image_generation", "code_generation", "browser_automation", "internal_knowledge")
            },
            "toolAccessMode": str(row.get("tool_access_mode") or "selected"),
            "toolIds": [str(item) for item in row.get("tool_ids") or []],
            "skillAccessMode": str(row.get("skill_access_mode") or "selected"),
            "skillIds": [str(item) for item in row.get("skill_ids") or []],
            "knowledgeBaseIds": [str(item) for item in row.get("knowledge_base_ids") or []],
            "memoryScope": str(row.get("memory_scope") or "personal"),
            "modelConfig": dict(row.get("model_config") or {}),
            "harnessProfileRef": str(row.get("harness_profile_ref") or ""),
            "creatorId": str(row.get("creator_id") or ""),
            "memberUserIds": [str(item) for item in row.get("member_user_ids") or []],
            "createdAt": _iso(row.get("created_at")),
            "updatedAt": _iso(row.get("updated_at")),
            "deletedAt": _iso(row.get("deleted_at")),
        }


def _iso(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


__all__ = ["EmployeeRepository", "AUDIT_COLLECTION"]
