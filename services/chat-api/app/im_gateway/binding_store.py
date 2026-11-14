"""渠道-员工绑定存储（051 B2 / T020，FR-007）。

``channel_employee_bindings`` 集合（027 门面双后端）持久化每条
渠道-员工绑定与路由规则。读写经注入的 DB（``get_db``），与员工
repository 同风格；路由求值本身 DB-free（``routing.resolve_employee``）。
"""

from __future__ import annotations

from typing import Any

from app.core.db import get_db

from .routing import (
    CHANNEL_EMPLOYEE_BINDINGS_COLLECTION,
    ChannelEmployeeBinding,
    RoutingRuleError,
)


class BindingStore:
    """渠道-员工绑定集合读写（租户隔离）。"""

    def __init__(self, db: Any | None = None) -> None:
        self.db = db if db is not None else get_db()

    @property
    def _col(self) -> Any:
        return self.db[CHANNEL_EMPLOYEE_BINDINGS_COLLECTION]

    def _row_to_binding(self, row: dict[str, Any]) -> ChannelEmployeeBinding:
        return ChannelEmployeeBinding(
            channel=str(row.get("channel") or ""),
            employee_id=str(row.get("employee_id") or ""),
            keywords=[str(k) for k in (row.get("keywords") or []) if k],
            is_default=bool(row.get("is_default")),
            tenant_id=str(row.get("tenant_id") or "default"),
            binding_id=str(row.get("binding_id") or ""),
            updated_at=str(row.get("updated_at") or ""),
        )

    async def list_bindings(self, tenant_id: str, channel: str) -> list[ChannelEmployeeBinding]:
        """渠道的全部绑定（按绑定序，与写入序一致）。"""
        rows = await self._col.find(
            {"tenant_id": tenant_id, "channel": str(channel or "").strip()}
        ).to_list(length=10_000)
        return [self._row_to_binding(r) for r in rows]

    async def save_binding(self, binding: ChannelEmployeeBinding) -> None:
        """upsert 一条绑定（按 channel+employee_id 幂等）。"""
        if not binding.binding_id:
            import uuid

            binding.binding_id = uuid.uuid4().hex
        row = binding.as_dict()
        await self._col.update_one(
            {"tenant_id": binding.tenant_id, "channel": binding.channel, "employee_id": binding.employee_id},
            {"$set": row},
            upsert=True,
        )

    async def delete_binding(self, tenant_id: str, channel: str, employee_id: str) -> bool:
        result = await self._col.delete_one(
            {"tenant_id": tenant_id, "channel": str(channel or "").strip(), "employee_id": str(employee_id or "").strip()}
        )
        return bool(getattr(result, "deleted_count", 0))


__all__ = ["BindingStore", "RoutingRuleError"]
