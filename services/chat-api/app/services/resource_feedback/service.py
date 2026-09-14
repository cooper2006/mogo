from __future__ import annotations

import datetime
import uuid
from typing import Any

from app.core.db import get_db
from app.core.tenant import resolve_main_id
from app.services.member_identity import public_display_name, public_identity

from .access import FeedbackAccessResolver, FeedbackSubject


COMMENT_COLLECTION = "resource_comments"
REACTION_COLLECTION = "resource_reactions"
COMMENT_REACTION_COLLECTION = "resource_comment_reactions"
NOTIFICATION_COLLECTION = "resource_feedback_notifications"


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class ResourceFeedbackError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class ResourceFeedbackService:
    """Flat discussion and likes for version-stable Skill identities."""

    def __init__(self, access: FeedbackAccessResolver | None = None) -> None:
        self._access = access or FeedbackAccessResolver()

    async def list(self, *, main_id: str, user_id: str, resource_type: str, resource_id: str, limit: int = 30, cursor: str = "") -> dict[str, Any]:
        subject = await self._subject(main_id, user_id, resource_type, resource_id)
        db = get_db()
        query = self._query(resolve_main_id(main_id), subject)
        page_size = min(max(limit, 1), 100)
        comment_query: dict[str, Any] = {**query, "status": "active"}
        cursor_time = self._parse_cursor(cursor)
        if cursor_time is not None:
            comment_query["created_at"] = {"$lt": cursor_time}
        rows = await db[COMMENT_COLLECTION].find(comment_query).sort("created_at", -1).limit(page_size + 1).to_list(length=page_size + 1)
        has_more = len(rows) > page_size
        rows = rows[:page_size]
        comment_ids = [str(row.get("_id") or "") for row in rows]
        comment_reactions = await db[COMMENT_REACTION_COLLECTION].find({
            "main_id": resolve_main_id(main_id), "comment_id": {"$in": comment_ids}, "reaction": "like",
        }).to_list(length=max(len(comment_ids) * 1000, 1)) if comment_ids else []
        like_counts: dict[str, int] = {}
        liked_by_me: set[str] = set()
        for item in comment_reactions:
            comment_id = str(item.get("comment_id") or "")
            like_counts[comment_id] = like_counts.get(comment_id, 0) + 1
            if str(item.get("user_id") or "") == str(user_id):
                liked_by_me.add(comment_id)
        reaction = await db[REACTION_COLLECTION].find_one({**query, "user_id": str(user_id), "reaction": "like"})
        count = await db[REACTION_COLLECTION].count_documents({**query, "reaction": "like"})
        await db[NOTIFICATION_COLLECTION].update_many(
            {**query, "recipient_user_id": str(user_id), "status": "unread"},
            {"$set": {"status": "read", "read_at": _utcnow()}},
        )
        next_cursor = self._cursor(rows[-1].get("created_at")) if has_more and rows else ""
        return {
            "items": [self._comment_view(row, user_id, like_counts, liked_by_me) for row in rows],
            "likes": count, "likedByMe": reaction is not None,
            "hasMore": has_more, "nextCursor": next_cursor,
        }

    async def comment(self, *, main_id: str, user_id: str, resource_type: str, resource_id: str, content: str, parent_id: str = "") -> dict[str, Any]:
        subject = await self._subject(main_id, user_id, resource_type, resource_id)
        text = str(content or "").strip()
        if not text:
            raise ResourceFeedbackError("feedback_content_required", "Comment content is required")
        if len(text) > 2000:
            raise ResourceFeedbackError("feedback_content_too_long", "Comment content is too long")
        db, tenant_id = get_db(), resolve_main_id(main_id)
        parent = None
        if parent_id:
            parent = await db[COMMENT_COLLECTION].find_one({"_id": parent_id, **self._query(tenant_id, subject), "status": "active"})
            if parent is None:
                raise ResourceFeedbackError("feedback_parent_not_found", "The replied comment no longer exists", 404)
        author = await self._author(db, tenant_id, str(user_id))
        row = {
            "_id": uuid.uuid4().hex, **self._query(tenant_id, subject),
            "user_id": str(user_id), "author": author, "content": text,
            "parent_id": str(parent_id or ""), "status": "active",
            "root_id": str((parent or {}).get("root_id") or (parent or {}).get("_id") or ""),
            "reply_to": dict((parent or {}).get("author") or {}),
            "created_at": _utcnow(), "updated_at": _utcnow(),
        }
        await db[COMMENT_COLLECTION].insert_one(row)
        recipient = str((parent or {}).get("user_id") or subject.owner_user_id or "")
        recipients = {recipient} - {"", str(user_id)}
        for recipient in recipients:
            await db[NOTIFICATION_COLLECTION].insert_one({
                "_id": uuid.uuid4().hex, **self._query(tenant_id, subject),
                "recipient_user_id": recipient, "actor": author, "comment_id": row["_id"],
                "kind": "reply" if parent else "comment",
                "status": "unread", "created_at": row["created_at"],
            })
        return self._comment_view(row, user_id, {}, set())

    async def delete_comment(self, *, main_id: str, user_id: str, comment_id: str) -> None:
        db = get_db()
        row = await db[COMMENT_COLLECTION].find_one({"_id": comment_id, "main_id": resolve_main_id(main_id), "status": "active"})
        if row is None:
            raise ResourceFeedbackError("feedback_comment_not_found", "Comment not found", 404)
        await self._subject(main_id, user_id, str(row.get("resource_type") or ""), str(row.get("resource_id") or ""))
        if str(row.get("user_id") or "") != str(user_id):
            raise ResourceFeedbackError("feedback_delete_forbidden", "Only the author can delete this comment", 403)
        await db[COMMENT_COLLECTION].update_one({"_id": comment_id}, {"$set": {"status": "deleted", "updated_at": _utcnow()}})

    async def toggle_like(self, *, main_id: str, user_id: str, resource_type: str, resource_id: str) -> dict[str, Any]:
        subject = await self._subject(main_id, user_id, resource_type, resource_id)
        db, tenant_id = get_db(), resolve_main_id(main_id)
        query = {**self._query(tenant_id, subject), "user_id": str(user_id), "reaction": "like"}
        current = await db[REACTION_COLLECTION].find_one(query)
        if current:
            await db[REACTION_COLLECTION].delete_one({"_id": current["_id"]})
            liked = False
        else:
            await db[REACTION_COLLECTION].insert_one({"_id": uuid.uuid4().hex, **query, "created_at": _utcnow()})
            liked = True
        count = await db[REACTION_COLLECTION].count_documents({**self._query(tenant_id, subject), "reaction": "like"})
        return {"likedByMe": liked, "likes": count}

    async def toggle_comment_like(self, *, main_id: str, user_id: str, comment_id: str) -> dict[str, Any]:
        db, tenant_id = get_db(), resolve_main_id(main_id)
        comment = await db[COMMENT_COLLECTION].find_one({"_id": comment_id, "main_id": tenant_id, "status": "active"})
        if comment is None:
            raise ResourceFeedbackError("feedback_comment_not_found", "Comment not found", 404)
        await self._subject(main_id, user_id, str(comment.get("resource_type") or ""), str(comment.get("resource_id") or ""))
        query = {"main_id": tenant_id, "comment_id": comment_id, "user_id": str(user_id), "reaction": "like"}
        current = await db[COMMENT_REACTION_COLLECTION].find_one(query)
        if current:
            await db[COMMENT_REACTION_COLLECTION].delete_one({"_id": current["_id"]})
            liked = False
        else:
            await db[COMMENT_REACTION_COLLECTION].insert_one({"_id": uuid.uuid4().hex, **query, "created_at": _utcnow()})
            liked = True
        count = await db[COMMENT_REACTION_COLLECTION].count_documents({"main_id": tenant_id, "comment_id": comment_id, "reaction": "like"})
        return {"likedByMe": liked, "likes": count}

    async def unread_count(self, *, main_id: str, user_id: str) -> int:
        return await get_db()[NOTIFICATION_COLLECTION].count_documents({
            "main_id": resolve_main_id(main_id), "recipient_user_id": str(user_id), "status": "unread",
        })

    async def notifications(self, *, main_id: str, user_id: str, limit: int = 20) -> dict[str, Any]:
        db, tenant_id = get_db(), resolve_main_id(main_id)
        query = {"main_id": tenant_id, "recipient_user_id": str(user_id), "status": "unread"}
        rows = await db[NOTIFICATION_COLLECTION].find(query).sort("created_at", -1).limit(min(max(limit, 1), 50)).to_list(length=min(max(limit, 1), 50))
        items = []
        for row in rows:
            resource_type, resource_id = str(row.get("resource_type") or ""), str(row.get("resource_id") or "")
            name = "Skill"
            if resource_type == "skill_distribution":
                distribution = await db.skill_distributions.find_one({"_id": resource_id, "main_id": tenant_id}) or {}
                skill = await db.user_skills.find_one({"_id": str(distribution.get("source_skill_id") or ""), "main_id": tenant_id}) or {}
                name = str(skill.get("name") or name)
            elif resource_type == "organization_skill":
                skill = await db.skills.find_one({"_id": resource_id, "main_id": tenant_id}) or {}
                name = str(skill.get("name") or name)
            created = row.get("created_at")
            items.append({"id": str(row.get("_id") or ""), "resourceType": resource_type, "resourceId": resource_id,
                "name": name, "actor": public_identity(row.get("actor")),
                "createdAt": created.isoformat() if isinstance(created, datetime.datetime) else ""})
        return {"items": items, "unreadCount": await db[NOTIFICATION_COLLECTION].count_documents(query)}

    async def _subject(self, main_id: str, user_id: str, resource_type: str, resource_id: str) -> FeedbackSubject:
        try:
            return await self._access.require(main_id=main_id, user_id=user_id, resource_type=resource_type, resource_id=resource_id)
        except LookupError as exc:
            raise ResourceFeedbackError(str(exc), "Feedback resource not found", 404) from exc
        except PermissionError as exc:
            raise ResourceFeedbackError(str(exc), "You cannot access this discussion", 403) from exc

    @staticmethod
    def _query(main_id: str, subject: FeedbackSubject) -> dict[str, str]:
        return {"main_id": main_id, "resource_type": subject.resource_type, "resource_id": subject.resource_id}

    @staticmethod
    async def _author(db: Any, main_id: str, user_id: str) -> dict[str, str]:
        from app.services.skill_sharing.member_directory import member_id_candidates
        row = await db.end_users.find_one(
            {"_id": {"$in": member_id_candidates([user_id])}, "main_id": main_id},
            {"name": 1, "display_name": 1, "nickname": 1, "login_name": 1},
        ) or {}
        return {"userId": user_id, "displayName": public_display_name(row)}

    @staticmethod
    def _comment_view(row: dict[str, Any], user_id: str, like_counts: dict[str, int], liked_by_me: set[str]) -> dict[str, Any]:
        created = row.get("created_at")
        comment_id = str(row.get("_id") or "")
        return {
            "id": comment_id, "content": str(row.get("content") or ""),
            "parentId": str(row.get("parent_id") or ""),
            "author": public_identity(row.get("author"), user_id=str(row.get("user_id") or "")),
            "rootId": str(row.get("root_id") or row.get("parent_id") or ""),
            "replyTo": public_identity(row.get("reply_to")),
            "likes": int(like_counts.get(comment_id, 0)), "likedByMe": comment_id in liked_by_me,
            "mine": str(row.get("user_id") or "") == str(user_id),
            "createdAt": created.isoformat() if isinstance(created, datetime.datetime) else "",
        }

    @staticmethod
    def _parse_cursor(value: str) -> datetime.datetime | None:
        try:
            parsed = datetime.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _cursor(value: Any) -> str:
        return value.isoformat() if isinstance(value, datetime.datetime) else ""
