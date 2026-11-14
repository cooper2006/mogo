"""员工级开放 API Key 认证依赖（051 FR-009 / T021）。

``X-API-Key`` 头携带员工级开放 Key（``ek_live_<token>``），解析后得到以员工
身份访问的 principal。与既有 ``Authorization``（end_user 会话）通道并行：员工
只读/会话端点同时接受两种认证，未携带任何认证 → 401。

范围（OQ-3）：``read``（员工只读查询）/ ``session``（以员工身份创建/追加会话
消息）/ ``read+session``（并集，默认）。不含档案修改。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Header, HTTPException

from .api_keys import EmployeeApiKeyRepository, scope_allows

#: HTTP 头名（员工级开放 Key）。
API_KEY_HEADER = "X-API-Key"

#: 鉴权失败统一返回（不区分失效原因，防枚举侧信道）。
_INVALID_KEY_STATUS = 401
_INVALID_KEY_DETAIL = "invalid_employee_api_key"


@dataclass(frozen=True)
class EmployeeApiKeyPrincipal:
    """Key 解析成功后的身份（员工侧访问主体）。"""

    employee_id: str
    tenant_id: str
    scope: str
    key_id: str
    key_prefix: str
    employee_name: str = ""
    created_by: str = ""

    def allows(self, *required: str) -> bool:
        return scope_allows(self.scope, *required)


def _principal_from_resolved(resolved: dict[str, Any]) -> EmployeeApiKeyPrincipal:
    key = resolved["key"]
    employee = resolved["employee"]
    return EmployeeApiKeyPrincipal(
        employee_id=str(employee.get("_id") or key.get("employee_id") or ""),
        tenant_id=str(key.get("tenant_id") or ""),
        scope=str(key.get("scope") or ""),
        key_id=str(key.get("_id") or ""),
        key_prefix=str(key.get("key_prefix") or ""),
        employee_name=str(employee.get("name") or ""),
        created_by=str(employee.get("creator_id") or ""),
    )


async def resolve_employee_key(
    x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
) -> EmployeeApiKeyPrincipal:
    """FastAPI 依赖：解析 ``X-API-Key`` 头 → 员工 principal。

    头缺失 / Key 无效 / Key 失效 / 员工停用 → 统一 401。
    """
    if not isinstance(x_api_key, str) or not x_api_key.strip():
        raise HTTPException(status_code=_INVALID_KEY_STATUS, detail=_INVALID_KEY_DETAIL)
    resolved = await EmployeeApiKeyRepository().resolve_key(
        tenant_id="", plaintext=x_api_key
    )
    if resolved is None:
        raise HTTPException(status_code=_INVALID_KEY_STATUS, detail=_INVALID_KEY_DETAIL)
    return _principal_from_resolved(resolved)


def require_scope(*required: str):
    """返回一个依赖：校验 principal 具备全部所需 scope。

    用法：``employee: EmployeeApiKeyPrincipal = Depends(require_scope("read"))``。
    """

    async def _dependency(
        principal: EmployeeApiKeyPrincipal = Depends(resolve_employee_key),
    ) -> EmployeeApiKeyPrincipal:
        if not principal.allows(*required):
            raise HTTPException(status_code=403, detail="employee_api_key_scope_denied")
        return principal

    return _dependency


__all__ = [
    "API_KEY_HEADER",
    "EmployeeApiKeyPrincipal",
    "require_scope",
    "resolve_employee_key",
]
