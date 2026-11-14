"""员工级开放 API Key（051 FR-009 / T021）—— admin-api 侧权威实现。

员工级开放 Key 采用 skill_sharing 已验证的「随机生成 + 单向哈希存储 + 明文
仅显示一次」范式（比可逆加密更安全：哈希不可回读，库泄露不暴露可用 Key）。
scope 按 OQ-3 定「只读 + 会话」，不含档案修改。

Key 明文形态：``ek_live_<token_urlsafe(32)>``；库中仅存 sha256 哈希与前 8 位
前缀（识别用）。范围（scope）：``read`` / ``session`` / ``read+session``。

> 同源副本：chat-api ``app/employees/api_keys.py`` 与本文件一致（哈希/scope
> 纯函数逐字节同步；repository 完整读写仅 admin-api 持有，chat-api 侧为只读
> 解析器）。共享集合 ``employee_api_keys``（027 门面双后端）。
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.db import get_db
from app.employees.repository import add_tenant_scope


def _resolve_tenant_id(tenant_id: str) -> str:
    """admin-api 侧租户归一（repository 本地口径：透传）。"""
    return str(tenant_id or "default")

#: employee_api_keys 集合（027 门面双后端：chat-api 写读）。
EMPLOYEE_API_KEYS_COLLECTION = "employee_api_keys"

#: Key 明文前缀（识别「这是员工级 Key」）。
KEY_PREFIX_LIVE = "ek_live_"

#: Key 状态机。
KEY_STATUSES: tuple[str, ...] = ("active", "revoked")

#: scope 合法取值（OQ-3：只读 + 会话，不含档案修改）。
KEY_SCOPES: tuple[str, ...] = ("read", "session", "read+session")

#: 默认 scope（OQ-3 已定：只读 + 会话）。
DEFAULT_KEY_SCOPE = "read+session"

#: 默认有效期（天）。None = 永不过期（与既有 skill_share 口径一致）。
DEFAULT_KEY_TTL_DAYS: int | None = None

#: Key 明文熵长度（token_urlsafe 输出字节数）。
KEY_TOKEN_BYTES = 32


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _normalize_scope(scope: str | None) -> str:
    value = str(scope or DEFAULT_KEY_SCOPE).strip().lower()
    if value not in KEY_SCOPES:
        raise ValueError(f"invalid key scope: {scope!r}")
    return value


def hash_key(plaintext: str) -> str:
    """单向哈希（库中唯一存储形态；明文不可回读）。"""
    value = str(plaintext or "").strip()
    if not value:
        raise ValueError("employee api key must not be empty")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_key_plaintext() -> str:
    """生成一条新 Key 明文（调用方必须「仅返回一次」，随后只存哈希）。"""
    return f"{KEY_PREFIX_LIVE}{secrets.token_urlsafe(KEY_TOKEN_BYTES)}"


def key_prefix_of(plaintext: str) -> str:
    """明文前 8 位（不含 live 前缀），用于列表页识别与审计定位。"""
    token = str(plaintext or "").removeprefix(KEY_PREFIX_LIVE)
    return token[:8]


def scope_allows(scope: str | None, *required: str) -> bool:
    """scope 是否允许全部所需能力（read+session 覆盖一切）。"""
    value = str(scope or DEFAULT_KEY_SCOPE).strip().lower()
    if value == "read+session":
        return True
    return all(item in value.split("+") for item in required)


class EmployeeApiKeyRepository:
    def __init__(self, db: Any | None = None) -> None:
        self.db = db if db is not None else get_db()

    async def ensure_indexes(self) -> None:
        await self.db[EMPLOYEE_API_KEYS_COLLECTION].create_index(
            [("tenant_id", 1), ("employee_id", 1)], name="employee_key_tenant_employee"
        )
        await self.db[EMPLOYEE_API_KEYS_COLLECTION].create_index(
            [("tenant_id", 1), ("key_hash", 1)], name="employee_key_tenant_hash"
        )

    async def create_key(
        self,
        *,
        tenant_id: str,
        employee_id: str,
        actor: str,
        label: str = "",
        scope: str | None = None,
        ttl_days: int | None = DEFAULT_KEY_TTL_DAYS,
    ) -> dict[str, Any]:
        """生成新 Key，返回 {**row, plaintext}（plaintext 仅此一次可见）。"""
        tenant = _resolve_tenant_id(tenant_id)
        now = _utcnow()
        plaintext = generate_key_plaintext()
        key_id = uuid.uuid4().hex
        expires_at = now + timedelta(days=int(ttl_days)) if ttl_days is not None else None
        row = {
            "_id": key_id,
            "tenant_id": tenant,
            "employee_id": str(employee_id),
            "key_hash": hash_key(plaintext),
            "key_prefix": key_prefix_of(plaintext),
            "scope": _normalize_scope(scope),
            "label": str(label or ""),
            "created_by": str(actor or ""),
            "status": "active",
            "created_at": now,
            "last_used_at": None,
            "revoked_at": None,
            "expires_at": expires_at,
        }
        await self.db[EMPLOYEE_API_KEYS_COLLECTION].insert_one(row)
        return {**dict(row), "plaintext": plaintext}

    async def resolve_key(
        self, *, tenant_id: str, plaintext: str
    ) -> dict[str, Any] | None:
        """按明文哈希解析可用 Key（active + 未过期 + 员工 active/未删）。

        ``tenant_id`` 仅作额外约束（调用方已知租户时）；为空时按 Key 文档自带
        租户解析（哈希 256-bit 全局唯一，防跨租户枚举）。返回
        ``{"key": row, "employee": employee_row}`` 或 None（任何失效原因），
        不区分失效原因（防枚举侧信道）。
        """
        lookup: dict[str, Any] = {"key_hash": hash_key(plaintext)}
        tenant = str(tenant_id or "")
        if tenant:
            lookup = add_tenant_scope(lookup, tenant)
        row = await self.db[EMPLOYEE_API_KEYS_COLLECTION].find_one(lookup)
        if row is None:
            return None
        if str(row.get("status") or "") != "active":
            return None
        expires_at = row.get("expires_at")
        if isinstance(expires_at, datetime):
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= _utcnow():
                return None
        employee = await self.db["employees"].find_one(
            add_tenant_scope(
                {"_id": str(row.get("employee_id") or ""), "deleted_at": None},
                _resolve_tenant_id(row.get("tenant_id")),
            )
        )
        if employee is None or str(employee.get("status") or "") != "active":
            return None
        return {"key": dict(row), "employee": dict(employee)}

    async def revoke_key(
        self, *, tenant_id: str, key_id: str, actor: str
    ) -> dict[str, Any] | None:
        """撤销 Key（幂等：已撤销返回现状；不存在返回 None）。"""
        existing = await self.get_key(tenant_id, key_id)
        if existing is None:
            return None
        if str(existing.get("status") or "") != "active":
            return existing
        await self.db[EMPLOYEE_API_KEYS_COLLECTION].update_one(
            add_tenant_scope({"_id": key_id}, _resolve_tenant_id(tenant_id)),
            {"$set": {"status": "revoked", "revoked_at": _utcnow(), "revoked_by": str(actor or "")}},
        )
        return await self.get_key(tenant_id, key_id)

    async def get_key(self, tenant_id: str, key_id: str) -> dict[str, Any] | None:
        row = await self.db[EMPLOYEE_API_KEYS_COLLECTION].find_one(
            add_tenant_scope({"_id": key_id}, _resolve_tenant_id(tenant_id))
        )
        return dict(row) if row else None

    async def list_keys(self, *, tenant_id: str, employee_id: str) -> list[dict[str, Any]]:
        rows = await self.db[EMPLOYEE_API_KEYS_COLLECTION].find(
            add_tenant_scope({"employee_id": str(employee_id)}, _resolve_tenant_id(tenant_id))
        ).sort("created_at", -1).to_list(length=100)
        return [dict(r) for r in rows]

    @staticmethod
    def serialize(row: dict[str, Any]) -> dict[str, Any]:
        """Key 视图（永不回显明文/哈希）。"""
        return {
            "keyId": str(row.get("_id") or ""),
            "employeeId": str(row.get("employee_id") or ""),
            "label": str(row.get("label") or ""),
            "scope": str(row.get("scope") or DEFAULT_KEY_SCOPE),
            "keyPrefix": str(row.get("key_prefix") or ""),
            "status": str(row.get("status") or "active"),
            "createdBy": str(row.get("created_by") or ""),
            "createdAt": _iso(row.get("created_at")),
            "lastUsedAt": _iso(row.get("last_used_at")),
            "expiresAt": _iso(row.get("expires_at")),
        }


__all__ = [
    "DEFAULT_KEY_SCOPE",
    "DEFAULT_KEY_TTL_DAYS",
    "EMPLOYEE_API_KEYS_COLLECTION",
    "KEY_PREFIX_LIVE",
    "KEY_SCOPES",
    "KEY_STATUSES",
    "EmployeeApiKeyRepository",
    "generate_key_plaintext",
    "hash_key",
    "key_prefix_of",
    "scope_allows",
]
