"""055 菜单管理 —— 租户级默认方案存取。

只存**差异覆盖层**：没有记录时返回空 ``nodes``，前端据此渲染静态默认菜单。
GET 不写库（025 GET 无副作用）；tenant_id 由调用方从认证主体传入，
不接受请求体覆盖。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.db import get_db
from app.menu_settings.models import (
    MenuNode,
    MenuPlanPayload,
    MenuPlanResponse,
    node_from_row,
)

logger = logging.getLogger(__name__)

COLLECTION = "organization_menu_schemes"
SCHEME_KEY = "default"


class MenuSettingsService:
    def _filter(self, tenant_id: str) -> dict[str, str]:
        return {"tenant_id": tenant_id, "scheme_key": SCHEME_KEY}

    async def get_plan(self, tenant_id: str) -> MenuPlanResponse:
        row = await get_db()[COLLECTION].find_one(self._filter(tenant_id))
        if not row:
            return MenuPlanResponse(nodes=[])
        return self._public(row)

    async def save_plan(
        self, tenant_id: str, admin_id: str, payload: MenuPlanPayload
    ) -> MenuPlanResponse:
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "tenant_id": tenant_id,
            "scheme_key": SCHEME_KEY,
            "nodes": [item.model_dump(exclude_none=True) for item in payload.nodes],
            "version": 1,
            "updated_at": now,
            "updated_by": admin_id,
        }
        await get_db()[COLLECTION].update_one(
            self._filter(tenant_id),
            {"$set": values, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        return self._public(values)

    async def delete_plan(self, tenant_id: str) -> bool:
        """恢复默认：删除本租户默认方案；无记录时同样成功（幂等）。"""
        await get_db()[COLLECTION].delete_one(self._filter(tenant_id))
        return True

    @staticmethod
    def _public(row: dict[str, Any]) -> MenuPlanResponse:
        updated_at = row.get("updated_at")
        raw_nodes = list(row.get("nodes") or [])
        nodes: list[MenuNode] = []
        for item in raw_nodes:
            if not isinstance(item, dict):
                logger.warning("menu_settings: skip malformed node %r", type(item))
                continue
            node = node_from_row(item)
            if node is not None:
                nodes.append(node)
            else:
                logger.warning("menu_settings: skip invalid node %r", item.get("key"))
        return MenuPlanResponse(
            id=SCHEME_KEY,
            schemeKey=str(row.get("scheme_key") or SCHEME_KEY),
            version=int(row.get("version") or 1),
            nodes=nodes,
            updatedAt=updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at or ""),
            updatedBy=str(row.get("updated_by") or ""),
        )
