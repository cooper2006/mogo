from __future__ import annotations

import asyncio
import datetime

from app.services.personal_knowledge import feedback_summary as summary_module
from app.services.personal_knowledge import service as service_module
from app.services.personal_knowledge.service import PersonalKnowledgeService


def matches(row, query):
    for key, expected in query.items():
        value = row.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$nin" in expected and value in expected["$nin"]:
                return False
        elif value != expected:
            return False
    return True


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction):
        self.rows.sort(key=lambda row: row.get(key), reverse=direction < 0)
        return self

    def skip(self, value):
        self.rows = self.rows[value:]
        return self

    def limit(self, value):
        self.rows = self.rows[:value]
        return self

    async def to_list(self, length):
        return [dict(row) for row in self.rows[:length]]


class Collection:
    def __init__(self, rows=None):
        self.rows = {str(row["_id"]): dict(row) for row in (rows or [])}

    def find(self, query, projection=None):
        return Cursor([row for row in self.rows.values() if matches(row, query)])

    async def count_documents(self, query):
        return len([row for row in self.rows.values() if matches(row, query)])

    def aggregate(self, pipeline):
        matched = [row for row in self.rows.values() if matches(row, pipeline[0]["$match"])]
        grouped = {}
        for row in matched:
            key = row["resource_id"]
            target = grouped.setdefault(key, {"_id": key, "count": 0, "latest": row["created_at"]})
            target["count"] += 1
            target["latest"] = max(target["latest"], row["created_at"])
        return Cursor(list(grouped.values()))


class Db:
    def __init__(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.knowledge_resources = Collection([
            {"_id": "old", "main_id": "tenant", "owner_user_id": "A", "directory_id": "", "deleted_at": None, "name": "旧文档", "updated_at": now},
            {"_id": "unread", "main_id": "tenant", "owner_user_id": "A", "directory_id": "", "deleted_at": None, "name": "有新评论", "updated_at": now - datetime.timedelta(days=2)},
            {"_id": "new", "main_id": "tenant", "owner_user_id": "A", "directory_id": "", "deleted_at": None, "name": "普通文档", "updated_at": now - datetime.timedelta(days=1)},
        ])
        self.resource_feedback_notifications = Collection([
            {"_id": "notification", "resource_id": "unread", "main_id": "tenant", "resource_type": "personal_knowledge", "recipient_user_id": "A", "status": "unread", "created_at": now},
        ])
        self.resource_grants = Collection([
            {"_id": "grant", "resource_id": "unread", "main_id": "tenant", "resource_type": "personal_knowledge", "recipient_user_id": "B", "status": "active"},
        ])
        self.personal_knowledge_directories = Collection()
        self.end_users = Collection([{"_id": "A", "main_id": "tenant", "name": "所有者"}])

    def __getitem__(self, name):
        return getattr(self, name)


def test_unread_feedback_is_prioritized_across_pages(monkeypatch):
    db = Db()
    monkeypatch.setattr(service_module, "get_db", lambda: db)
    monkeypatch.setattr(summary_module, "get_db", lambda: db)

    service = PersonalKnowledgeService()
    first_page = asyncio.run(service.list_resources(main_id="tenant", user_id="A", view="mine", page=1, page_size=2))
    second_page = asyncio.run(service.list_resources(main_id="tenant", user_id="A", view="mine", page=2, page_size=2))

    assert [item["id"] for item in first_page["items"]] == ["unread", "old"]
    assert first_page["items"][0]["feedback"]["unreadCount"] == 1
    assert first_page["items"][0]["feedback"]["latestUnreadAt"]
    assert first_page["items"][0]["share"] == {"shared": True, "recipientCount": 1}
    assert [item["id"] for item in second_page["items"]] == ["new"]
