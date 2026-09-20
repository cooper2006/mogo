from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.db import get_db
from app.shortcut_settings.defaults import default_entries
from app.shortcut_settings.models import ShortcutPlanPayload


COLLECTION = "organization_shortcut_schemes"


class ShortcutSettingsService:
    async def get_default_plan(self, main_id: str) -> dict[str, Any]:
        row = await get_db()[COLLECTION].find_one({"main_id": main_id, "scheme_key": "default"})
        if not row:
            return {
                "id": "default",
                "name": "企业默认方案",
                "entries": default_entries(),
                "groups": self._groups_from_entries(default_entries()),
                "customIcons": [],
                "updatedAt": "",
            }
        return self._public(row)

    async def save_default_plan(self, main_id: str, admin_id: str, payload: ShortcutPlanPayload) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        values = {
            "main_id": main_id,
            "scheme_key": "default",
            "name": payload.name,
            "entries": [item.model_dump() for item in payload.entries],
            "groups": [item.model_dump() for item in payload.groups],
            "customIcons": [item.model_dump() for item in payload.customIcons],
            "updated_at": now,
            "updated_by": admin_id,
        }
        await get_db()[COLLECTION].update_one(
            {"main_id": main_id, "scheme_key": "default"},
            {"$set": values, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        return self._public(values)

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        updated_at = row.get("updated_at")
        entries = list(row.get("entries") or [])
        groups = list(row.get("groups") or []) or ShortcutSettingsService._groups_from_entries(entries)
        groups = [{**group, "locked": bool(group.get("locked")) or any(
            entry.get("categoryKey") == group.get("key") and entry.get("locked") for entry in entries
        )} for group in groups]
        return {
            "id": "default",
            "name": str(row.get("name") or "企业默认方案"),
            "entries": entries,
            "groups": groups[:6],
            "customIcons": list(row.get("customIcons") or [])[:100],
            "updatedAt": updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at or ""),
        }

    @staticmethod
    def _groups_from_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for entry in entries:
            key = str(entry.get("categoryKey") or "custom")
            groups.setdefault(key, {
                "key": key,
                "label": str(entry.get("categoryLabel") or key),
                "iconKey": str(entry.get("categoryIconKey") or "grid"),
                "iconSvg": str(entry.get("categoryIconSvg") or ""),
                "locked": bool(entry.get("locked")),
            })
        return list(groups.values())[:6]
