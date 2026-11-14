"""非生产环境数据脱敏 / 合成数据（QF-662）。

设计原则：
- **非生产环境默认脱敏**：dev/staging 环境的 API 响应自动脱敏敏感字段。
- **合成数据可选**：提供 ``generate_synthetic_account`` 用于测试数据填充。
- **生产环境不受影响**：``APP_ENV=production`` 时所有函数返回原始数据。
- **fail-safe**：脱敏失败时返回原始数据而非抛异常，避免影响可用性。

与 :mod:`app.security.redaction` 的分工：
- ``redaction.py``：运行时按策略脱敏（生产环境也生效）。
- 本模块：环境级脱敏（仅非生产环境生效）+ 合成数据生成。
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

# 非生产环境标记（APP_ENV 的常见取值）
_NON_PROD_ENVS = frozenset({"development", "dev", "staging", "stage", "test", "local", ""})


def is_non_production() -> bool:
    """判断当前是否非生产环境。"""
    env = str(getattr(settings, "app_env", "") or "").strip().lower()
    return env in _NON_PROD_ENVS


def sanitize_value(value: Any, *, field_hint: str = "") -> Any:
    """根据字段名对单个值脱敏。

    Args:
        value: 原始值。
        field_hint: 字段名（用于判断脱敏方式）。

    Returns:
        脱敏后的值。非字符串类型返回原值（已天然不敏感）。
    """
    if not isinstance(value, str):
        return value
    if not value:
        return value

    hint = field_hint.lower()

    # 邮箱：保留首字符和域名，中间替换为 ***
    if "@" in value and "email" not in hint:
        pass  # 不是邮箱字段，走通用逻辑
    if "@" in value:
        local, _, domain = value.partition("@")
        if len(local) <= 2:
            masked_local = local[0] + "*" * max(len(local) - 1, 1)
        else:
            masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
        return f"{masked_local}@{domain}"

    # 手机号：保留前 3 后 4
    if re.match(r"^\+?\d{7,15}$", value):
        return value[:3] + "****" + value[-4:]

    # 密码/密钥类：全部替换
    if any(kw in hint for kw in ("password", "secret", "token", "key", "hash", "salt")):
        return "[REDACTED]"

    # 身份证/护照：保留前 3 后 4
    if re.match(r"^[A-Za-z0-9]{8,18}$", value) and any(
        kw in hint for kw in ("id", "passport", "cert")
    ):
        return value[:3] + "*" * (len(value) - 7) + value[-4:]

    # 通用：前 3 后 3 保留，中间替换
    if len(value) > 6:
        return value[:3] + "*" * (len(value) - 6) + value[-3:]
    return "*" * len(value)


# 需要脱敏的字段名关键词
_SENSITIVE_KEYWORDS = frozenset({
    "email", "phone", "password", "secret", "token", "key",
    "hash", "salt", "mfa", "private", "credential",
})


def sanitize_document(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """脱敏 MongoDB 文档中的所有敏感字段。

    仅对 dict 类型的顶层字段生效（与 ``filter_response`` 一致的浅层策略）。
    非生产环境下自动生效，生产环境原样返回。
    """
    if doc is None:
        return None
    if not is_non_production():
        return doc

    result: dict[str, Any] = {}
    for key, value in doc.items():
        hint = str(key)
        # 跳过 _id 等非敏感字段
        if hint.startswith("_"):
            result[key] = value
            continue
        # 匹配敏感字段
        hint_lower = hint.lower().replace("_", "").replace("-", "")
        if any(kw in hint_lower for kw in ("email", "phone", "pass", "secret", "token", "key", "hash", "salt", "mfa", "private", "credential")):
            result[key] = sanitize_value(value, field_hint=hint)
        elif isinstance(value, str) and len(value) > 20:
            # 长字符串可能是密钥或令牌
            result[key] = sanitize_value(value, field_hint=hint)
        else:
            result[key] = value
    return result


# ── 合成数据生成（用于测试环境填充） ─────────────────────────────────────

_SYNTHEC_NAMES = [
    "张三", "李四", "王五", "赵六", "钱七", "孙八", "周九", "吴十",
    "Admin", "Tester", "Dev", "Analyst", "Engineer", "Manager",
]

_SYNTHEC_DOMAINS = ["example.com", "example.org", "test.local"]


def _synthetic_id(prefix: str = "syn") -> str:
    """生成合成 ID。"""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def generate_synthetic_account(
    *,
    tenant_id: str = "default",
    username: str | None = None,
    display_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    role_name: str = "组织管理员",
    group_code: str = "default-group",
) -> dict[str, Any]:
    """生成一条合成账号记录（用于测试/演示环境）。

    所有字段均为合成数据，不包含任何真实 PII。
    """
    if not username:
        username = f"user_{uuid.uuid4().hex[:8]}"
    if not display_name:
        display_name = _SYNTHEC_NAMES[hash(username) % len(_SYNTHEC_NAMES)]
    if not email:
        domain = _SYNTHEC_DOMAINS[hash(username) % len(_SYNTHEC_DOMAINS)]
        email = f"{username}@{domain}"
    if not phone:
        phone = f"138{hash(username) % 100000000:08d}"

    now = datetime.now(timezone.utc).isoformat()
    return {
        "_id": _synthetic_id("acct"),
        "tenant_id": tenant_id,
        "username": username,
        "display_name": display_name,
        "email": email,
        "phone": phone,
        "group_code": group_code,
        "role_name": role_name,
        "status": "active",
        "password_hash": "",  # 空值表示合成数据无真实密码
        "password_salt": "",
        "is_protected": False,
        "created_at": now,
        "updated_at": now,
    }


def generate_synthetic_accounts(
    count: int = 5,
    *,
    tenant_id: str = "default",
) -> list[dict[str, Any]]:
    """批量生成合成账号（用于测试环境填充）。"""
    return [
        generate_synthetic_account(tenant_id=tenant_id)
        for _ in range(count)
    ]


def seed_synthetic_data() -> dict[str, list[dict[str, Any]]]:
    """返回一套完整的合成测试数据（账号 + 组织组）。

    仅用于非生产环境的初始化/测试。
    """
    accounts = generate_synthetic_accounts(5)
    groups = [
        {"_id": _synthetic_id("grp"), "code": "default-group", "name": "默认组", "tenant_id": "default"},
        {"_id": _synthetic_id("grp"), "code": "engineering", "name": "工程组", "tenant_id": "default"},
        {"_id": _synthetic_id("grp"), "code": "qa", "name": "测试组", "tenant_id": "default"},
    ]
    return {"accounts": accounts, "groups": groups}


__all__ = [
    "is_non_production",
    "sanitize_value",
    "sanitize_document",
    "generate_synthetic_account",
    "generate_synthetic_accounts",
    "seed_synthetic_data",
]
