"""数字员工集合访问（051 FR-001 / FR-005 / FR-010）—— admin-api 侧。

双服务共用 ``employees`` 集合（027 门面双后端），口径与 chat-api
``app/employees/repository.py`` 完全一致（049 双服务同口径先例）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from app.core.db import get_db

EMPLOYEE_COLLECTION = "employees"
AUDIT_COLLECTION = "gate_events"

CAPABILITY_KEYS: tuple[str, ...] = (
    "content_generation",
    "image_generation",
    "code_generation",
    "browser_automation",
    "internal_knowledge",
)
EMPLOYEE_STATUSES: tuple[str, ...] = ("active", "disabled", "archived")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _scope(tenant_id: str) -> dict[str, Any]:
    """租户隔离（default 租户兼容未带 tenant_id 的历史行，同 chat-api 口径）。"""
    if str(tenant_id or "") in {"", "default"}:
        return {
            "$or": [
                {"tenant_id": tenant_id},
                {"tenant_id": {"$exists": False}},
                {"tenant_id": ""},
                {"tenant_id": None},
            ]
        }
    return {"tenant_id": tenant_id}


def add_tenant_scope(query: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    base = dict(query or {})
    scope = _scope(tenant_id)
    if "$or" in scope:
        return {"$and": [base, scope]}
    base.update(scope)
    return base


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

    async def create(
        self, tenant_id: str, payload: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        now = utcnow()
        doc: dict[str, Any] = {
            "tenant_id": tenant_id,
            "name": str(payload.get("name") or ""),
            "description": str(payload.get("description") or ""),
            "capabilities": {
                key: bool((payload.get("capabilities") or {}).get(key, False))
                for key in CAPABILITY_KEYS
            },
            "tool_access_mode": str(payload.get("toolAccessMode") or payload.get("tool_access_mode") or "selected"),
            "tool_ids": list(payload.get("toolIds", payload.get("tool_ids", [])) or []),
            "skill_access_mode": str(payload.get("skillAccessMode") or payload.get("skill_access_mode") or "selected"),
            "skill_ids": list(payload.get("skillIds", payload.get("skill_ids", [])) or []),
            "knowledge_base_ids": list(payload.get("knowledge_base_ids") or []),
            "memory_scope": str(payload.get("memory_scope") or "personal"),
            "model_config": dict(payload.get("model_config") or {}),
            "harness_profile_ref": str(payload.get("harness_profile_ref") or ""),
            "status": str(payload.get("status") or "active"),
            "creator_id": str(actor or ""),
            "member_user_ids": list(payload.get("member_user_ids") or []),
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
            "created_by": str(actor or ""),
            "_id": uuid.uuid4().hex,
        }
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

    async def audit(
        self,
        tenant_id: str,
        actor: str,
        action: str,
        target_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
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
            import logging

            logging.getLogger(__name__).warning(
                "employee audit write failed tenant=%s action=%s target=%s",
                tenant_id, action, target_id,
            )

    @staticmethod
    def serialize(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row.get("_id") or row.get("employee_id") or ""),
            "name": str(row.get("name") or ""),
            "description": str(row.get("description") or ""),
            "status": str(row.get("status") or "active"),
            "capabilities": {
                key: bool((row.get("capabilities") or {}).get(key, False))
                for key in CAPABILITY_KEYS
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
