"""Normalize group-scoped shortcut preferences without changing scheme structure."""

from __future__ import annotations

from typing import Any


PERSONAL_GROUP_KEY = "personal"


def normalize_groups(groups: list[dict[str, Any]], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not groups:
        groups = list({str(entry.get("categoryKey")): {
            "key": str(entry.get("categoryKey")),
            "label": str(entry.get("categoryLabel") or entry.get("categoryKey")),
            "iconKey": str(entry.get("categoryIconKey") or "grid"),
            "iconSvg": str(entry.get("categoryIconSvg") or ""),
        } for entry in entries if entry.get("categoryKey")}.values())
    return [{**group, "locked": bool(group.get("locked")) or any(
        entry.get("categoryKey") == group.get("key") and entry.get("locked") for entry in entries
    )} for group in groups]


def apply_preferences(
    entries: list[dict[str, Any]], groups: list[dict[str, Any]], preference: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Only unlocked groups may have a user-defined order; groups never move."""
    groups = normalize_groups(groups, entries)
    personal = [dict(item) for item in (preference.get("personal_entries") or [])[:6]]
    personal_group = dict(preference.get("personal_group") or {})
    if personal or personal_group.get("key") == PERSONAL_GROUP_KEY:
        personal_group = {
            "key": PERSONAL_GROUP_KEY,
            "label": str(personal_group.get("label") or "我的常用")[:80],
            "iconKey": str(personal_group.get("iconKey") or "grid")[:40],
            "iconSvg": str(personal_group.get("iconSvg") or ""),
            "locked": False,
            "personal": True,
        }
        groups = [group for group in groups if group.get("key") != PERSONAL_GROUP_KEY]
        groups.append(personal_group)

    group_orders = {str(key): list(map(str, value)) for key, value in (preference.get("group_orders") or {}).items() if isinstance(value, list)}
    normalized_orders: dict[str, list[str]] = dict(group_orders) if not entries else {}
    rows: list[dict[str, Any]] = []
    all_entries = [dict(item) for item in entries]
    for item in personal:
        item.update(categoryKey=PERSONAL_GROUP_KEY, categoryLabel=personal_group["label"], personal=True, enabled=True)
        all_entries.append(item)
    for group in groups:
        key = str(group.get("key") or "")
        members = [item for item in all_entries if item.get("categoryKey") == key]
        if not group.get("locked"):
            requested = group_orders.get(key, [])
            position = {entry_id: index for index, entry_id in enumerate(requested)}
            original = {str(item.get("id")): index for index, item in enumerate(members)}
            members.sort(key=lambda item: (position.get(str(item.get("id")), len(position)), original.get(str(item.get("id")), 0)))
            normalized_orders[key] = [str(item.get("id")) for item in members]
        rows.extend(members)
    result = {
        "groupOrders": normalized_orders,
        "personalGroup": personal_group if personal_group.get("key") == PERSONAL_GROUP_KEY else None,
        "personalEntries": personal,
    }
    return rows, groups, result
