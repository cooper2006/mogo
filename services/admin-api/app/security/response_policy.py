"""按调用者权限裁剪响应字段（QF-660 / FR-21）。

设计原则：
- **白名单优于黑名单**：默认不返回任何敏感字段，只有明确授权的字段才出现。
- **角色继承**：高权限角色获得低权限角色的所有字段，再加自己的专属字段。
- **fail-closed**：未知角色回退到最小字段集（只返回 id + displayName）。
- **浅层裁剪**：只作用于响应最外层 dict；深层敏感值由 ``redact_mapping`` 负责。

与 :mod:`app.security.redaction` 的分工：
- ``redact_mapping``：把字段值替换为 ``[REDACTED]``（值级脱敏）。
- ``filter_response`` / 本模块：直接剔除字段（字段级裁剪）。
- 两者互补：裁剪处理「不该看的字段」，脱敏处理「不该看到的值」。
"""

from __future__ import annotations

from typing import Any

from .redaction import filter_response

# ── 字段分级 ──────────────────────────────────────────────────────────
# L0: 基础标识（所有已认证调用者可见）
# L1: 组织信息（租户管理员及以上可见）
# L2: 联系信息（租户管理员及以上可见，平台管理员额外可见）
# L3: 安全状态（仅平台管理员可见）

L0_FIELDS: frozenset[str] = frozenset({
    "id",
    "username",
    "displayName",
})

L1_FIELDS: frozenset[str] = frozenset({
    *L0_FIELDS,
    "tenantId",
    "groupCode",
    "groupName",
    "roleName",
})

L2_FIELDS: frozenset[str] = frozenset({
    *L1_FIELDS,
    "email",
    "phone",
    "status",
    "updatedAt",
})

L3_FIELDS: frozenset[str] = frozenset({
    *L2_FIELDS,
    "isProtected",
    "password_hash",
    "mfa_secret_encrypted",
    "mfa_secret_hash",
    "password_salt",
})

# 角色 → 最高可见字段集
_ROLE_FIELD_LEVEL: dict[str, frozenset[str]] = {
    "平台管理员": L3_FIELDS,
    "platform_admin": L3_FIELDS,
    "租户管理员": L2_FIELDS,
    "组织管理员": L2_FIELDS,
    "组织成员": L1_FIELDS,
    "普通用户": L0_FIELDS,
    "viewer": L0_FIELDS,
}

# 未知角色的回退字段集（fail-closed）
_FALLBACK_FIELDS: frozenset[str] = L0_FIELDS


def allowed_fields_for(caller: dict[str, Any] | None) -> frozenset[str]:
    """根据调用者返回其可见的字段集。

    Args:
        caller: 调用者信息 dict，至少包含 ``role_name`` 字段。
                ``None`` 或空 dict 回退到最小字段集。

    Returns:
        该角色可见的字段名集合。
    """
    if not caller:
        return _FALLBACK_FIELDS
    role = str(caller.get("role_name") or caller.get("role") or "").strip()
    return _ROLE_FIELD_LEVEL.get(role, _FALLBACK_FIELDS)


def format_account_by_role(
    doc: dict[str, Any],
    caller: dict[str, Any] | None,
    group_name_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """按调用者权限格式化账号响应（替代无权限感知的 _format_account）。

    先构建完整响应，再按调用者权限裁剪字段。
    """
    from ..api.routes.organizations import _as_time

    group_code = str(doc.get("group_code", ""))
    full_response: dict[str, Any] = {
        "id": str(doc["_id"]),
        "tenantId": str(doc.get("tenant_id", "")),
        "username": str(doc.get("username", "")),
        "displayName": str(doc.get("display_name", "")),
        "email": str(doc.get("email", "")),
        "phone": str(doc.get("phone", "")),
        "groupCode": group_code,
        "groupName": (group_name_map or {}).get(group_code, group_code),
        "roleName": str(doc.get("role_name", "")),
        "status": str(doc.get("status", "active")),
        "isProtected": bool(doc.get("is_protected", False)),
        "updatedAt": _as_time(doc.get("updated_at")),
    }

    allowed = allowed_fields_for(caller)
    return filter_response(full_response, allowed, deny_all=True)
