from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.db import get_db
from app.services.shortcut_preferences import apply_preferences, normalize_groups


SCHEME_COLLECTION = "organization_shortcut_schemes"
PREFERENCE_COLLECTION = "user_shortcut_preferences"


class ShortcutService:
    async def _scheme(self, main_id: str, user_id: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], bool]:
        scheme = await get_db()[SCHEME_COLLECTION].find_one({"main_id": main_id, "scheme_key": "default"})
        entries = [dict(item) for item in (scheme or {}).get("entries") or [] if item.get("enabled", True)]
        groups = normalize_groups([dict(item) for item in (scheme or {}).get("groups") or []], entries)
        scheme_key = "default"
        configured = bool(scheme)
        from app.product.extensions import get_product_extension
        resolver = get_product_extension().shortcut_scheme_resolver
        if resolver is not None:
            resolved = await resolver.resolve(main_id=main_id, user_id=user_id, default_entries=entries)
            if isinstance(resolved, dict):
                if resolved.get("matched"):
                    entries = [dict(item) for item in resolved.get("entries") or [] if item.get("enabled", True)]
                    groups = normalize_groups([dict(item) for item in resolved.get("groups") or []], entries)
                    scheme_key = str(resolved.get("schemeKey") or "default")
                    configured = True
            elif isinstance(resolved, tuple):
                entries, matched = resolved
                configured = configured or matched
            else:
                entries = resolved
                configured = configured or bool(entries)
        return scheme_key, entries, groups, configured

    async def effective(self, main_id: str, user_id: str) -> dict[str, Any]:
        scheme_key, entries, groups, configured = await self._scheme(main_id, user_id)
        preference = await get_db()[PREFERENCE_COLLECTION].find_one(
            {"main_id": main_id, "user_id": user_id, "scheme_key": scheme_key}
        ) or {}
        if not preference and scheme_key == "default":
            legacy = await get_db()[PREFERENCE_COLLECTION].find_one(
                {"main_id": main_id, "user_id": user_id, "scheme_key": {"$exists": False}}
            ) or {}
            if legacy:
                preference = {"personal_entries": legacy.get("personal_entries") or []}
                if legacy.get("order_customized"):
                    by_id = {str(item.get("id")): str(item.get("categoryKey")) for item in entries + list(preference["personal_entries"])}
                    orders: dict[str, list[str]] = {}
                    for item_id in legacy.get("order") or []:
                        key = by_id.get(str(item_id))
                        if key:
                            orders.setdefault(key, []).append(str(item_id))
                    preference["group_orders"] = orders
        rows, groups, preferences = apply_preferences(entries, groups, preference)
        return {
            "entries": rows, "groups": groups, "schemeKey": scheme_key,
            "defaultOrder": [str(item.get("id")) for item in entries if item.get("id")],
            "configured": configured, "preferences": preferences,
        }

    async def save_preferences(self, main_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        scheme_key, entries, groups, _ = await self._scheme(main_id, user_id)
        unlocked = {str(group.get("key")) for group in groups if not group.get("locked")}
        valid_ids = {key: {str(item.get("id")) for item in entries if item.get("categoryKey") == key} for key in unlocked}
        requested = payload.get("groupOrders") or {}
        group_orders = {
            key: list(dict.fromkeys(item for item in value if not entries or item in valid_ids.get(key, set())))
            for key, value in requested.items() if (key in unlocked or not entries) and isinstance(value, list) and key != "personal"
        }
        personal = [dict(item) for item in (payload.get("personalEntries") or [])[:6]]
        personal = [item for item in personal if item.get("type") in {"prompt", "skill"}]
        personal_ids = {str(item.get("id")) for item in personal}
        if "personal" in requested and isinstance(requested["personal"], list):
            group_orders["personal"] = list(dict.fromkeys(item for item in requested["personal"] if item in personal_ids))
        now = datetime.now(timezone.utc)
        values = {
            "main_id": main_id, "user_id": user_id, "scheme_key": scheme_key,
            "group_orders": group_orders,
            "personal_group": dict(payload.get("personalGroup") or {}),
            "personal_entries": personal, "updated_at": now,
        }
        await get_db()[PREFERENCE_COLLECTION].update_one(
            {"main_id": main_id, "user_id": user_id, "scheme_key": scheme_key},
            {"$set": values, "$setOnInsert": {"created_at": now}}, upsert=True,
        )
        return await self.effective(main_id, user_id)
