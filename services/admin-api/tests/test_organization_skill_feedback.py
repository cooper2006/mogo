from __future__ import annotations

import asyncio
import datetime

from app.services import organization_skill_feedback as feedback_module
from app.services.organization_skill_feedback import OrganizationSkillFeedbackService


def _matches(row, query):
    return all(row.get(key) in value["$in"] if isinstance(value, dict) and "$in" in value else row.get(key) == value for key, value in query.items())


class Cursor:
    def __init__(self, rows): self.rows = rows
    def sort(self, key, direction): self.rows.sort(key=lambda row: row.get(key), reverse=direction < 0); return self
    def limit(self, value): self.rows = self.rows[:value]; return self
    async def to_list(self, length): return [dict(row) for row in self.rows[:length]]


class Collection:
    def __init__(self, rows=None): self.rows = {row["_id"]: row for row in rows or []}
    async def find_one(self, query, projection=None):
        return next((dict(row) for row in self.rows.values() if _matches(row, query)), None)
    def find(self, query): return Cursor([dict(row) for row in self.rows.values() if _matches(row, query)])
    async def count_documents(self, query): return len([row for row in self.rows.values() if _matches(row, query)])


class Database:
    def __init__(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.skills = Collection([{"_id": "skill", "main_id": "tenant"}])
        self.resource_comments = Collection([{"_id": "comment", "main_id": "tenant", "resource_type": "organization_skill", "resource_id": "skill", "status": "active", "content": "建议增加示例", "author": {"displayName": "Member"}, "created_at": now}])
        self.resource_reactions = Collection([{"_id": "like", "main_id": "tenant", "resource_type": "organization_skill", "resource_id": "skill", "reaction": "like"}])
        self.resource_comment_reactions = Collection([{"_id": "comment-like", "main_id": "tenant", "comment_id": "comment", "reaction": "like"}])


def test_admin_can_read_enterprise_skill_feedback(monkeypatch):
    db = Database(); monkeypatch.setattr(feedback_module, "get_db", lambda: db)
    result = asyncio.run(OrganizationSkillFeedbackService().list(main_id="tenant", skill_id="skill"))
    assert result["likes"] == 1
    assert result["items"][0]["content"] == "建议增加示例"
    assert result["items"][0]["likes"] == 1
