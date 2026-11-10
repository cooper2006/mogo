"""数字员工数据模型（051 FR-001 / FR-010）。

与 ``PositionRolePayload`` 同范式（006）：capabilities 开关 + tool/skill
access mode 与显式列表（沿用 ``AGENT_CAPABILITY_KEYS`` 白名单），但绑定对象
是 agent 会话而非人。状态机 active / disabled / archived，删除为软删除
（``deleted_at`` 非空 = 已删，历史会话保留 ``employee_id`` 溯源）。

档案字段（FR-001）：
* name / description / capabilities / tool_access_mode / tool_ids /
  skill_access_mode / skill_ids（能力白名单）；
* knowledge_base_ids（知识库挂载）、memory_scope（personal|project|department）、
  model_config（模型配置）、harness_profile_ref（019 引用）；
* status（active|disabled|archived）、creator_id、member_user_ids（049 口径）、
  tenant_id、created_at / updated_at / deleted_at。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

#: 001/006 共享的能力键白名单（沿用 006 预留常量口径）。
EMPLOYEE_CAPABILITY_KEYS: tuple[str, ...] = (
    "content_generation",
    "image_generation",
    "code_generation",
    "browser_automation",
    "internal_knowledge",
)

#: employees 集合（027 门面双后端：chat-api 写 / admin-api 写读）。
EMPLOYEE_COLLECTION = "employees"

#: 员工状态机。
EMPLOYEE_STATUSES: tuple[str, ...] = ("active", "disabled", "archived")

#: 记忆 scope（017 三范围）。
MEMORY_SCOPES: tuple[str, ...] = ("personal", "project", "department")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Employee:
    """数字员工档案（FR-001）。"""

    tenant_id: str
    name: str
    description: str = ""
    capabilities: dict[str, bool] = field(default_factory=dict)
    tool_access_mode: str = "selected"
    tool_ids: list[str] = field(default_factory=list)
    skill_access_mode: str = "selected"
    skill_ids: list[str] = field(default_factory=list)
    knowledge_base_ids: list[str] = field(default_factory=list)
    memory_scope: str = "personal"
    model_config: dict[str, Any] = field(default_factory=dict)
    harness_profile_ref: str = ""
    status: str = "active"
    creator_id: str = ""
    member_user_ids: list[str] = field(default_factory=list)
    employee_id: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    def normalized_capabilities(self) -> dict[str, bool]:
        source = self.capabilities if isinstance(self.capabilities, dict) else {}
        return {key: bool(source.get(key, False)) for key in EMPLOYEE_CAPABILITY_KEYS}

    def is_visible_to(self, user_id: str) -> bool:
        """可见性 = 「我的 ∪ 我参与的」（049 口径）。"""
        if str(user_id or "") == str(self.creator_id or ""):
            return True
        return str(user_id) in {str(item) for item in (self.member_user_ids or [])}

    def to_document(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "description": self.description,
            "capabilities": self.normalized_capabilities(),
            "tool_access_mode": self.tool_access_mode,
            "tool_ids": list(self.tool_ids or []),
            "skill_access_mode": self.skill_access_mode,
            "skill_ids": list(self.skill_ids or []),
            "knowledge_base_ids": list(self.knowledge_base_ids or []),
            "memory_scope": self.memory_scope,
            "model_config": dict(self.model_config or {}),
            "harness_profile_ref": self.harness_profile_ref,
            "status": self.status,
            "creator_id": self.creator_id,
            "member_user_ids": list(self.member_user_ids or []),
            "created_at": self.created_at or utcnow(),
            "updated_at": self.updated_at or utcnow(),
            "deleted_at": self.deleted_at,
        }


@dataclass
class EmployeeProfile:
    """档案注入快照（会话创建时物化，FR-010）。

    在途会话不受档案变更影响：注入只发生在创建时，快照内嵌会话文档。
    """

    employee_id: str
    name: str = ""
    capabilities: dict[str, bool] = field(default_factory=dict)
    tool_access_mode: str = "selected"
    tool_ids: list[str] = field(default_factory=list)
    skill_access_mode: str = "selected"
    skill_ids: list[str] = field(default_factory=list)
    knowledge_base_ids: list[str] = field(default_factory=list)
    memory_scope: str = "personal"
    model_config: dict[str, Any] = field(default_factory=dict)
    harness_profile_ref: str = ""

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> "EmployeeProfile":
        return cls(
            employee_id=str(doc.get("employee_id") or doc.get("_id") or ""),
            name=str(doc.get("name") or ""),
            capabilities={
                key: bool((doc.get("capabilities") or {}).get(key, False))
                for key in EMPLOYEE_CAPABILITY_KEYS
            },
            tool_access_mode=str(doc.get("tool_access_mode") or "selected"),
            tool_ids=[str(item) for item in doc.get("tool_ids") or []],
            skill_access_mode=str(doc.get("skill_access_mode") or "selected"),
            skill_ids=[str(item) for item in doc.get("skill_ids") or []],
            knowledge_base_ids=[str(item) for item in doc.get("knowledge_base_ids") or []],
            memory_scope=str(doc.get("memory_scope") or "personal"),
            model_config=dict(doc.get("model_config") or {}),
            harness_profile_ref=str(doc.get("harness_profile_ref") or ""),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "name": self.name,
            "capabilities": dict(self.capabilities),
            "tool_access_mode": self.tool_access_mode,
            "tool_ids": list(self.tool_ids or []),
            "skill_access_mode": self.skill_access_mode,
            "skill_ids": list(self.skill_ids or []),
            "knowledge_base_ids": list(self.knowledge_base_ids or []),
            "memory_scope": self.memory_scope,
            "model_config": dict(self.model_config or {}),
            "harness_profile_ref": self.harness_profile_ref,
        }

    def allows_capability(self, key: str) -> bool:
        return bool(self.capabilities.get(key, False))

    def allows_external_tool(self, tool_id: str) -> bool:
        return self.tool_access_mode == "all" or str(tool_id) in {str(item) for item in self.tool_ids}

    def allows_skill(self, skill_id: str) -> bool:
        aliases = {str(skill_id)}
        if str(skill_id).startswith("org_skill:"):
            aliases.add(str(skill_id).removeprefix("org_skill:"))
        allowed = self.skill_access_mode == "all" or any(
            item in {str(x) for x in self.skill_ids} for item in aliases
        )
        return allowed
