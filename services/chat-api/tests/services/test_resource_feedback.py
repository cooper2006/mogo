from __future__ import annotations

import asyncio

from app.services.resource_feedback import service as feedback_module
from app.services.resource_feedback.access import FeedbackSubject
from app.services.resource_feedback.service import ResourceFeedbackError, ResourceFeedbackService


def matches(row, query):
    for key, expected in query.items():
        value = row.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]: return False
            if "$lt" in expected and not value < expected["$lt"]: return False
        elif value != expected: return False
    return True


class Cursor:
    def __init__(self, rows): self.rows = rows
    def sort(self, key, direction): self.rows.sort(key=lambda row: row.get(key), reverse=direction < 0); return self
    def limit(self, value): self.rows = self.rows[:value]; return self
    async def to_list(self, length): return [dict(row) for row in self.rows[:length]]


class Collection:
    def __init__(self): self.rows = {}
    def find(self, query): return Cursor([dict(row) for row in self.rows.values() if matches(row, query)])
    async def find_one(self, query, projection=None):
        rows = await self.find(query).to_list(1)
        return rows[0] if rows else None
    async def insert_one(self, row): self.rows[row["_id"]] = dict(row)
    async def count_documents(self, query): return len(await self.find(query).to_list(10000))
    async def update_one(self, query, update):
        row = await self.find_one(query)
        if row: row.update(update["$set"]); self.rows[row["_id"]] = row
    async def update_many(self, query, update):
        for row in await self.find(query).to_list(10000): row.update(update["$set"]); self.rows[row["_id"]] = row
    async def delete_one(self, query):
        row = await self.find_one(query)
        if row: self.rows.pop(row["_id"], None)


class Db:
    def __init__(self):
        self.resource_comments = Collection(); self.resource_reactions = Collection()
        self.resource_comment_reactions = Collection()
        self.resource_feedback_notifications = Collection(); self.end_users = Collection()
    def __getitem__(self, name): return getattr(self, name)


class Access:
    async def require(self, **kwargs):
        if kwargs["user_id"] == "outsider": raise PermissionError("feedback_forbidden")
        return FeedbackSubject("skill_distribution", kwargs["resource_id"], "owner")


class RoutedAccess:
    async def require(self, **kwargs):
        owners = {"a-share": "A", "b-share": "B"}
        return FeedbackSubject("skill_distribution", kwargs["resource_id"], owners[kwargs["resource_id"]])


class PersonalAccess:
    async def require(self, **kwargs):
        return FeedbackSubject("personal_knowledge", kwargs["resource_id"], "B")


class ResharedPersonalAccess:
    async def require(self, **kwargs):
        return FeedbackSubject("personal_knowledge", kwargs["resource_id"], "A", "B")


def test_comments_likes_and_owner_notification(monkeypatch):
    db = Db()
    db.end_users.rows["member"] = {"_id": "member", "main_id": "tenant", "name": "Member"}
    monkeypatch.setattr(feedback_module, "get_db", lambda: db)
    service = ResourceFeedbackService(Access())
    comment = asyncio.run(service.comment(main_id="tenant", user_id="member", resource_type="skill_distribution", resource_id="dist", content="很好用"))
    assert comment["content"] == "很好用"
    assert asyncio.run(service.unread_count(main_id="tenant", user_id="owner")) == 1
    liked = asyncio.run(service.toggle_like(main_id="tenant", user_id="member", resource_type="skill_distribution", resource_id="dist"))
    assert liked == {"likedByMe": True, "likes": 1}
    listed = asyncio.run(service.list(main_id="tenant", user_id="member", resource_type="skill_distribution", resource_id="dist"))
    assert listed["likes"] == 1 and listed["likedByMe"] is True and len(listed["items"]) == 1
    unliked = asyncio.run(service.toggle_like(main_id="tenant", user_id="member", resource_type="skill_distribution", resource_id="dist"))
    assert unliked == {"likedByMe": False, "likes": 0}


def test_reply_notifies_parent_author_and_supports_comment_likes(monkeypatch):
    db = Db(); monkeypatch.setattr(feedback_module, "get_db", lambda: db)
    service = ResourceFeedbackService(Access())
    root = asyncio.run(service.comment(main_id="tenant", user_id="member", resource_type="skill_distribution", resource_id="dist", content="建议增加示例"))
    reply = asyncio.run(service.comment(main_id="tenant", user_id="other", resource_type="skill_distribution", resource_id="dist", content="同意", parent_id=root["id"]))
    assert reply["rootId"] == root["id"]
    assert reply["replyTo"]["userId"] == "member"
    recipients = [row["recipient_user_id"] for row in db.resource_feedback_notifications.rows.values()]
    assert recipients == ["owner", "member"]
    result = asyncio.run(service.toggle_comment_like(main_id="tenant", user_id="other", comment_id=root["id"]))
    assert result == {"likedByMe": True, "likes": 1}
    listed = asyncio.run(service.list(main_id="tenant", user_id="other", resource_type="skill_distribution", resource_id="dist"))
    root_view = next(item for item in listed["items"] if item["id"] == root["id"])
    assert root_view["likedByMe"] is True and root_view["likes"] == 1


def test_personal_knowledge_likes_create_feedback_notifications(monkeypatch):
    db = Db(); monkeypatch.setattr(feedback_module, "get_db", lambda: db)
    service = ResourceFeedbackService(PersonalAccess())
    comment = asyncio.run(service.comment(main_id="tenant", user_id="B", resource_type="personal_knowledge", resource_id="knowledge", content="给 A 的评价"))
    asyncio.run(service.toggle_comment_like(main_id="tenant", user_id="A", comment_id=comment["id"]))
    asyncio.run(service.toggle_like(main_id="tenant", user_id="A", resource_type="personal_knowledge", resource_id="knowledge"))
    notifications = list(db.resource_feedback_notifications.rows.values())
    assert {row["kind"] for row in notifications} == {"like"}
    assert {row["recipient_user_id"] for row in notifications} == {"B"}


def test_reshared_personal_knowledge_activity_notifies_direct_sharer(monkeypatch):
    db = Db(); monkeypatch.setattr(feedback_module, "get_db", lambda: db)
    service = ResourceFeedbackService(ResharedPersonalAccess())
    comment = asyncio.run(service.comment(
        main_id="tenant", user_id="C", resource_type="personal_knowledge",
        resource_id="knowledge", content="C 的评价",
    ))
    asyncio.run(service.toggle_like(
        main_id="tenant", user_id="C", resource_type="personal_knowledge", resource_id="knowledge",
    ))
    notifications = list(db.resource_feedback_notifications.rows.values())
    assert [(row["kind"], row["recipient_user_id"]) for row in notifications] == [
        ("comment", "B"), ("like", "B"),
    ]
    listed = asyncio.run(service.list(
        main_id="tenant", user_id="B", resource_type="personal_knowledge", resource_id="knowledge",
    ))
    assert listed["commentCount"] == 1
    assert listed["focus"] == {"kind": "like", "commentId": ""}
    assert db.resource_feedback_notifications.rows[notifications[0]["_id"]]["status"] == "read"
    assert comment["content"] == "C 的评价"


def test_feedback_rejects_non_member(monkeypatch):
    db = Db(); monkeypatch.setattr(feedback_module, "get_db", lambda: db)
    try:
        asyncio.run(ResourceFeedbackService(Access()).list(main_id="tenant", user_id="outsider", resource_type="skill_distribution", resource_id="dist"))
        assert False
    except ResourceFeedbackError as exc:
        assert exc.status_code == 403


def test_reshared_channel_notifies_immediate_sharer_only(monkeypatch):
    db = Db(); monkeypatch.setattr(feedback_module, "get_db", lambda: db)
    asyncio.run(ResourceFeedbackService(RoutedAccess()).comment(
        main_id="tenant", user_id="C", resource_type="skill_distribution", resource_id="b-share", content="C 的评价",
    ))
    recipients = [row["recipient_user_id"] for row in db.resource_feedback_notifications.rows.values()]
    assert recipients == ["B"]


def test_comment_does_not_expose_phone_login_name(monkeypatch):
    db = Db()
    db.end_users.rows["member"] = {
        "_id": "member", "main_id": "tenant", "name": "", "login_name": "13910506485",
    }
    monkeypatch.setattr(feedback_module, "get_db", lambda: db)
    comment = asyncio.run(ResourceFeedbackService(Access()).comment(
        main_id="tenant", user_id="member", resource_type="skill_distribution",
        resource_id="dist", content="不会显示手机号",
    ))
    assert comment["author"] == {"userId": "member", "displayName": ""}


def test_historical_comment_and_reply_phone_names_are_sanitized(monkeypatch):
    db = Db(); monkeypatch.setattr(feedback_module, "get_db", lambda: db)
    db.resource_comments.rows["old"] = {
        "_id": "old", "main_id": "tenant", "resource_type": "skill_distribution",
        "resource_id": "dist", "status": "active", "user_id": "member",
        "author": {"userId": "member", "displayName": "13910506485"},
        "reply_to": {"userId": "other", "displayName": "user@example.com"},
        "content": "历史评价", "created_at": feedback_module._utcnow(),
    }
    item = asyncio.run(ResourceFeedbackService(Access()).list(
        main_id="tenant", user_id="member", resource_type="skill_distribution", resource_id="dist",
    ))["items"][0]
    assert item["author"] == {"userId": "member", "displayName": ""}
    assert item["replyTo"] == {"userId": "other", "displayName": ""}
