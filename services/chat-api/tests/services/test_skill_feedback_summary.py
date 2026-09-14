from __future__ import annotations

import asyncio
import datetime

from app.services.resource_feedback import summary as summary_module
from app.services.resource_feedback.summary import SkillFeedbackSummaryService


def matches(row, query):
    for key, expected in query.items():
        value = row.get(key)
        if isinstance(expected, dict) and "$in" in expected:
            if value not in expected["$in"]: return False
        elif value != expected: return False
    return True


class Cursor:
    def __init__(self, rows): self.rows = rows
    async def to_list(self, length): return [dict(row) for row in self.rows[:length]]


class Collection:
    def __init__(self, rows): self.rows = rows
    def find(self, query): return Cursor([row for row in self.rows if matches(row, query)])
    def aggregate(self, pipeline):
        rows = [row for row in self.rows if matches(row, pipeline[0]["$match"])]
        grouped = {}
        for row in rows:
            key = row["resource_id"]
            target = grouped.setdefault(key, {"_id": key, "count": 0})
            target["count"] += 1
            if "latest" in pipeline[1]["$group"]:
                target["latest"] = max(target.get("latest") or row["created_at"], row["created_at"])
        return Cursor(list(grouped.values()))


class Db:
    def __init__(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.skill_distributions = Collection([
            {"_id": "upstream", "main_id": "tenant", "owner_user_id": "A", "status": "active"},
            {"_id": "downstream", "main_id": "tenant", "owner_user_id": "B", "status": "active"},
        ])
        self.skill_distribution_members = Collection([
            {"distribution_id": "upstream", "main_id": "tenant", "recipient_user_id": "B", "status": "active"},
        ])
        self.resource_comments = Collection([
            {"resource_id": "upstream", "main_id": "tenant", "resource_type": "skill_distribution", "status": "active", "created_at": now},
            {"resource_id": "downstream", "main_id": "tenant", "resource_type": "skill_distribution", "status": "active", "created_at": now},
            {"resource_id": "downstream", "main_id": "tenant", "resource_type": "skill_distribution", "status": "active", "created_at": now},
        ])
        self.resource_feedback_notifications = Collection([
            {"resource_id": "downstream", "main_id": "tenant", "resource_type": "skill_distribution", "recipient_user_id": "B", "status": "unread"},
        ])


def test_summary_keeps_received_and_reshared_feedback_channels_separate(monkeypatch):
    db = Db(); monkeypatch.setattr(summary_module, "get_db", lambda: db)
    skills = [{"id": "skill", "package_source": {"distributionId": "upstream"}, "distribution_id": "downstream"}]
    asyncio.run(SkillFeedbackSummaryService().attach(main_id="tenant", user_id="B", skills=skills))
    feedback = skills[0]["feedback"]
    assert feedback["commentCount"] == 3 and feedback["unreadCount"] == 1
    assert [(item["id"], item["role"]) for item in feedback["channels"]] == [
        ("upstream", "member"), ("downstream", "owner"),
    ]
