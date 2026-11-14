from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from fastapi import HTTPException, status

from .constants import AGENT_CAPABILITY_KEYS, FULL_ACCESS_ROLE_KEY, POSITION_ROLE_COLLECTION, USER_ROLE_COLLECTION
from .repository import PositionRoleRepository, utcnow
from app.services.organization_tools import organization_tool_query


def normalized_capabilities(value: Any) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}
    return {key: bool(source.get(key, False)) for key in AGENT_CAPABILITY_KEYS}


def serialize_role(row: dict[str, Any], member_count: int = 0) -> dict[str, Any]:
    return {
        "id": str(row.get("_id") or ""),
        "name": str(row.get("name") or ""),
        "description": str(row.get("description") or ""),
        "status": str(row.get("status") or "active"),
        "protected": bool(row.get("protected")),
        "systemKey": str(row.get("system_key") or ""),
        "capabilities": normalized_capabilities(row.get("capabilities")),
        "toolAccessMode": str(row.get("tool_access_mode") or "selected"),
        "toolIds": [str(item) for item in row.get("tool_ids") or []],
        "skillAccessMode": str(row.get("skill_access_mode") or "selected"),
        "skillIds": [str(item) for item in row.get("skill_ids") or []],
        "memberCount": member_count,
        "createdAt": _iso(row.get("created_at")),
        "updatedAt": _iso(row.get("updated_at")),
    }


def _iso(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class PositionRoleService:
    def __init__(self, repository: PositionRoleRepository | None = None) -> None:
        self.repository = repository or PositionRoleRepository()
        self.db = self.repository.db

    async def list_roles(self, tenant_id: str) -> list[dict[str, Any]]:
        await self.repository.ensure_full_access_role(tenant_id)
        rows = await self.db[POSITION_ROLE_COLLECTION].find({"tenant_id": tenant_id}).sort("created_at", 1).to_list(length=1000)
        counts = await self.db[USER_ROLE_COLLECTION].aggregate([
            {"$match": {"tenant_id": tenant_id}}, {"$group": {"_id": "$role_id", "count": {"$sum": 1}}}
        ]).to_list(length=1000)
        count_map = {str(item.get("_id")): int(item.get("count") or 0) for item in counts}
        return [serialize_role(row, count_map.get(str(row.get("_id")), 0)) for row in rows]

    async def create_role(self, tenant_id: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        doc = self._document(tenant_id, payload)
        await self._ensure_unique_name(tenant_id, doc["name"])
        await self.validate_resource_ids(tenant_id, doc["tool_ids"], doc["skill_ids"])
        doc.update({"_id": uuid.uuid4().hex, "protected": False, "created_at": utcnow(), "updated_at": utcnow()})
        await self.db[POSITION_ROLE_COLLECTION].insert_one(doc)
        await self.repository.audit(tenant_id, actor, "create", "position_role", doc["_id"], serialize_role(doc))
        return serialize_role(doc)

    async def update_role(self, tenant_id: str, role_id: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        existing = await self._role(tenant_id, role_id)
        if existing.get("system_key") == FULL_ACCESS_ROLE_KEY:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="全能力管理员由系统维护，不能修改")
        patch = self._document(tenant_id, payload)
        await self._ensure_unique_name(tenant_id, patch["name"], exclude_role_id=role_id)
        await self.validate_resource_ids(tenant_id, patch["tool_ids"], patch["skill_ids"])
        patch["updated_at"] = utcnow()
        await self.db[POSITION_ROLE_COLLECTION].update_one({"_id": role_id, "tenant_id": tenant_id}, {"$set": patch})
        updated = {**existing, **patch}
        await self.repository.audit(tenant_id, actor, "update", "position_role", role_id, serialize_role(updated))
        return serialize_role(updated)

    async def copy_role(self, tenant_id: str, role_id: str, name: str, actor: str) -> dict[str, Any]:
        source = await self._role(tenant_id, role_id)
        # 006 FR-6：源角色若为 'all' 模式，复制出的角色也拥有全量工具/技能权限，
        # 必须限制只有 full_access_admin 才能复制此类高权限角色（防绕过审批）。
        src_mode = str(source.get("tool_access_mode") or "selected")
        if src_mode == "all":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="不能复制全量工具访问模式的岗位角色；请使用创建接口并走审批流程",
            )
        skill_mode = str(source.get("skill_access_mode") or "selected")
        if skill_mode == "all":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="不能复制全量技能访问模式的岗位角色；请使用创建接口并走审批流程",
            )
        return await self.create_role(tenant_id, {**serialize_role(source), "name": name, "status": "active"}, actor)

    async def set_status(self, tenant_id: str, role_id: str, enabled: bool, actor: str) -> None:
        existing = await self._role(tenant_id, role_id)
        if existing.get("system_key") == FULL_ACCESS_ROLE_KEY and not enabled:
            raise HTTPException(status_code=409, detail="全能力管理员不能停用")
        await self.db[POSITION_ROLE_COLLECTION].update_one(
            {"_id": role_id, "tenant_id": tenant_id}, {"$set": {"status": "active" if enabled else "disabled", "updated_at": utcnow()}}
        )
        await self.repository.audit(tenant_id, actor, "enable" if enabled else "disable", "position_role", role_id, {})

    async def delete_role(self, tenant_id: str, role_id: str, actor: str) -> None:
        existing = await self._role(tenant_id, role_id)
        if existing.get("protected"):
            raise HTTPException(status_code=409, detail="系统保障岗位角色不能删除")
        members = await self.db[USER_ROLE_COLLECTION].count_documents({"tenant_id": tenant_id, "role_id": role_id})
        if members:
            raise HTTPException(status_code=409, detail="该岗位角色仍有员工，请先迁移员工")
        await self.db[POSITION_ROLE_COLLECTION].delete_one({"_id": role_id, "tenant_id": tenant_id})
        await self.repository.audit(tenant_id, actor, "delete", "position_role", role_id, {"name": existing.get("name")})

    async def validate_roles(self, tenant_id: str, role_ids: list[str], primary_role_id: str) -> None:
        unique = list(dict.fromkeys(str(item) for item in role_ids if str(item)))
        if not primary_role_id or primary_role_id not in unique:
            raise HTTPException(status_code=400, detail="必须选择主要岗位角色")
        count = await self.db[POSITION_ROLE_COLLECTION].count_documents({
            "tenant_id": tenant_id, "_id": {"$in": unique}, "status": "active"
        })
        if count != len(unique):
            raise HTTPException(status_code=400, detail="岗位角色不存在或已停用")

    async def validate_resource_ids(self, tenant_id: str, tool_ids: list[str], skill_ids: list[str]) -> None:
        if tool_ids:
            count = await self.db.external_tools.count_documents(organization_tool_query(
                tenant_id,
                _id={"$in": list(dict.fromkeys(tool_ids))},
                status="active",
            ))
            if count != len(set(tool_ids)):
                raise HTTPException(status_code=400, detail="包含不存在、未启用或非企业级的 MCP/工具")
        if skill_ids:
            count = await self.db.skills.count_documents({
                "tenant_id": tenant_id,
                "_id": {"$in": list(dict.fromkeys(skill_ids))},
                "enabled": True,
            })
            if count != len(set(skill_ids)):
                raise HTTPException(status_code=400, detail="包含不存在或未启用的企业 Skill")

    async def _role(self, tenant_id: str, role_id: str) -> dict[str, Any]:
        row = await self.db[POSITION_ROLE_COLLECTION].find_one({"_id": role_id, "tenant_id": tenant_id})
        if not row:
            raise HTTPException(status_code=404, detail="岗位角色不存在")
        return dict(row)

    async def _ensure_unique_name(self, tenant_id: str, name: str, exclude_role_id: str = "") -> None:
        query: dict[str, Any] = {"tenant_id": tenant_id, "name": name}
        if exclude_role_id:
            query["_id"] = {"$ne": exclude_role_id}
        if await self.db[POSITION_ROLE_COLLECTION].find_one(query, {"_id": 1}):
            raise HTTPException(status_code=409, detail="岗位角色名称已存在")

    @staticmethod
    def _document(tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="岗位角色名称不能为空")
        tool_mode = str(payload.get("toolAccessMode") or payload.get("tool_access_mode") or "selected")
        skill_mode = str(payload.get("skillAccessMode") or payload.get("skill_access_mode") or "selected")
        if tool_mode not in {"all", "selected"} or skill_mode not in {"all", "selected"}:
            raise HTTPException(status_code=400, detail="资源授权模式无效")
        return {
            "tenant_id": tenant_id,
            "name": name[:120],
            "description": str(payload.get("description") or "").strip()[:1000],
            "status": str(payload.get("status") or "active"),
            "capabilities": normalized_capabilities(payload.get("capabilities")),
            "tool_access_mode": tool_mode,
            "tool_ids": [] if tool_mode == "all" else list(dict.fromkeys(str(item) for item in payload.get("toolIds", payload.get("tool_ids", [])) if str(item))),
            "skill_access_mode": skill_mode,
            "skill_ids": [] if skill_mode == "all" else list(dict.fromkeys(str(item) for item in payload.get("skillIds", payload.get("skill_ids", [])) if str(item))),
        }
