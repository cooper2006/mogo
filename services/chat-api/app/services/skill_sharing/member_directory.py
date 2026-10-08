from __future__ import annotations

import re
from typing import Any

from bson import ObjectId

from app.core.db import get_db
from app.core.tenant import add_tenant_scope, resolve_tenant_id
from app.services.member_identity import masked_account_identifier, public_display_name

from .service import SkillShareError


def _id_after(value: str) -> ObjectId | str | None:
    token = str(value or "").strip()
    if not token:
        return None
    return ObjectId(token) if ObjectId.is_valid(token) else token


def member_id_candidates(values: list[str]) -> list[ObjectId | str]:
    candidates: list[ObjectId | str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        candidates.append(ObjectId(normalized) if ObjectId.is_valid(normalized) else normalized)
    return candidates


class SkillShareMemberDirectory:
    """Tenant-scoped, cursor-paginated lookup over the existing end-user directory."""

    async def search(
        self, *, tenant_id: str, requester_user_id: str, keyword: str = "", cursor: str = "", limit: int = 20,
    ) -> dict[str, Any]:
        db = get_db()
        page_size = min(max(int(limit), 1), 50)
        clauses: list[dict[str, Any]] = [
            {"status": "active"},
            {"_id": {"$ne": _id_after(requester_user_id)}},
        ]
        after = _id_after(cursor)
        if after is not None:
            clauses.append({"_id": {"$gt": after}})
        term = str(keyword or "").strip()
        if term:
            # Anchored, case-sensitive prefixes allow the compound directory
            # indexes to serve large tenants. Login names and emails are stored
            # normalized; display names retain the user's entered casing.
            prefix = {"$regex": f"^{re.escape(term)}"}
            normalized_prefix = {"$regex": f"^{re.escape(term.lower())}"}
            clauses.append({"$or": [
                {"name": prefix}, {"login_name": normalized_prefix},
                {"email": normalized_prefix}, {"mobile": prefix},
            ]})
        query = add_tenant_scope({"$and": clauses}, resolve_tenant_id(tenant_id))
        rows = await db.end_users.find(
            query,
            {"name": 1, "login_name": 1, "email": 1},
        ).sort("_id", 1).limit(page_size + 1).to_list(length=page_size + 1)
        has_more = len(rows) > page_size
        page = rows[:page_size]
        return {
            "items": [self.member_view(row) for row in page],
            "nextCursor": str(page[-1].get("_id") or "") if has_more and page else "",
            "hasMore": has_more,
        }

    async def require_members(self, *, tenant_id: str, requester_user_id: str, user_ids: list[str]) -> list[dict[str, Any]]:
        unique_ids = list(dict.fromkeys(str(value or "").strip() for value in user_ids if str(value or "").strip()))
        if not unique_ids:
            raise SkillShareError("skill_share_recipients_required", "Choose at least one recipient")
        if len(unique_ids) > 100:
            raise SkillShareError("skill_share_too_many_recipients", "At most 100 recipients may be selected")
        if str(requester_user_id) in unique_ids:
            raise SkillShareError("skill_share_self_recipient", "A Skill cannot be shared with its owner")
        rows = await get_db().end_users.find(add_tenant_scope({
            "_id": {"$in": member_id_candidates(unique_ids)}, "status": "active",
        }, tenant_id), {"name": 1, "login_name": 1, "email": 1}).to_list(length=len(unique_ids) + 1)
        by_id = {str(row.get("_id") or ""): row for row in rows}
        if any(user_id not in by_id for user_id in unique_ids):
            raise SkillShareError("skill_share_recipient_invalid", "A recipient is unavailable in this organization", status_code=404)
        return [by_id[user_id] for user_id in unique_ids]

    @staticmethod
    def member_view(row: dict[str, Any]) -> dict[str, str]:
        return {
            "userId": str(row.get("_id") or ""),
            "displayName": public_display_name(row),
            "username": masked_account_identifier(row.get("login_name")),
            "email": masked_account_identifier(row.get("email")),
        }

    @staticmethod
    def member_view_batch(
        rows: list[dict[str, Any]],
        ordered_ids: list[str],
    ) -> list[dict[str, str]]:
        """Map end-user rows to member views, preserving ``ordered_ids`` order.

        IDs missing from ``rows`` (inactive / cross-tenant / unknown) fall back
        to ``{"userId": id, "displayName": "", "username": "", "email": ""}``
        so callers can still render the raw identifier.
        """
        from bson import ObjectId

        def _norm(value: str) -> str:
            token = str(value or "").strip()
            return str(ObjectId(token)) if ObjectId.is_valid(token) else token

        by_id: dict[str, dict[str, str]] = {}
        for row in rows:
            key = _norm(row.get("_id"))
            if key:
                by_id[key] = SkillShareMemberDirectory.member_view(row)
        output: list[dict[str, str]] = []
        for raw_id in ordered_ids:
            key = _norm(raw_id)
            view = by_id.get(key)
            if view is not None:
                output.append(view)
            else:
                output.append({
                    "userId": str(raw_id),
                    "displayName": "",
                    "username": "",
                    "email": "",
                })
        return output
