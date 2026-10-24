"""编排发布权门禁（特性 039 FR-005 / 决策 5）。

001 gatekeeper 的 RBAC 权限码模型为 ``<resource>:<action>[:<target>]``，
未知权限码 fail-closed（001 spec FR-5）。编排发布权编码为 ``orchestration:publish``，
本模块只回答「该端用户是否持有该权限码」，判权热路径保持 fail-closed：

* 用户在 ``end_users`` 集合的 ``permissions`` 数组显式持有 ``orchestration:publish`` → 放行；
* 用户的 ``roles`` 命中预设组映射（001 FR-6「角色 → 权限码预设组」的向下兼容口径）→ 放行；
* 其余一律拒绝（含「用户不存在」「集合不可用」「字段缺失」），**不存在静默放行分支**。

编排权（本人保存草稿）与发布权分离：本模块只管发布权。
"""

from __future__ import annotations

from typing import Any

from app.core.db import get_db
from app.core.ids import to_backend_id
from app.core.tenant import add_tenant_scope
from app.services.end_user_session import USER_COLLECTION

#: 发布权权限码（001 格式）。
PUBLISH_PERMISSION = "orchestration:publish"

#: 角色 → 权限码预设组（001 FR-6 向下兼容的窄口径；仅声明与编排发布相关的码，
#: 不做全量角色模型 —— 那是 006 position-rbac 的职责）。
_ROLE_PRESETS: dict[str, tuple[str, ...]] = {
    "admin": (PUBLISH_PERMISSION,),
    "operator": (PUBLISH_PERMISSION,),
}


async def can_publish_orchestration(tenant_id: str, user_id: str) -> bool:
    """是否持有 ``orchestration:publish``。任何解析失败都返回 False（fail-closed）。"""
    if not user_id:
        return False
    try:
        db = get_db()
        if db is None:
            return False
        user = await db[USER_COLLECTION].find_one(
            add_tenant_scope({"_id": to_backend_id(user_id)}, tenant_id)
        )
    except Exception:
        return False
    if not user:
        return False
    return _holds_publish(user)


def _holds_publish(user: dict[str, Any]) -> bool:
    """判权：直接权限码命中，或角色预设组命中。"""
    granted = user.get("permissions")
    if isinstance(granted, list):
        for code in granted:
            if str(code).strip() == PUBLISH_PERMISSION:
                return True

    roles = user.get("roles")
    if isinstance(roles, list):
        for role in roles:
            preset = _ROLE_PRESETS.get(str(role).strip())
            if preset and PUBLISH_PERMISSION in preset:
                return True
    return False