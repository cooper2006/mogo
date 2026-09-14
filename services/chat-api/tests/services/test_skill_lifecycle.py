from __future__ import annotations

import asyncio

from app.services.skill_lifecycle import service as lifecycle_module
from app.services.skill_lifecycle.service import SkillLifecycleService
from app.services import skills as skills_module


def _matches(row, query):
    return all(row.get(key) == value for key, value in query.items())


class Result:
    matched_count = 1


class Cursor:
    def __init__(self, rows): self.rows = rows
    def sort(self, key, direction): self.rows.sort(key=lambda row: row.get(key), reverse=direction < 0); return self
    def limit(self, value): self.rows = self.rows[:value]; return self
    async def to_list(self, length): return [dict(row) for row in self.rows[:length]]


class Collection:
    def __init__(self): self.rows = {}
    async def find_one(self, query, projection=None):
        for row in self.rows.values():
            if _matches(row, query):
                return {key: row.get(key) for key in projection if key in row} if projection else dict(row)
        return None
    async def insert_one(self, row): self.rows[row["_id"]] = dict(row)
    async def update_one(self, query, update):
        for key, row in self.rows.items():
            if _matches(row, query):
                row.update(update.get("$set") or {})
                self.rows[key] = row
                return Result()
        result = Result(); result.matched_count = 0; return result
    def find(self, query): return Cursor([dict(row) for row in self.rows.values() if _matches(row, query)])


class Database:
    def __init__(self):
        self.user_skills = Collection()
        self.skill_releases = Collection()
    def __getitem__(self, name): return getattr(self, name)


def test_existing_skill_keeps_published_projection_until_publish(monkeypatch):
    db = Database()
    db.user_skills.rows["skill"] = {
        "_id": "skill", "main_id": "tenant", "user_id": "owner", "type": "writing_style",
        "name": "Published name", "description": "published", "enabled": True,
    }
    monkeypatch.setattr(lifecycle_module, "get_db", lambda: db)

    async def update_skill(user_id, skill_id, updates, main_id="default"):
        await db.user_skills.update_one({"_id": skill_id, "main_id": main_id, "user_id": user_id}, {"$set": updates})
        return await db.user_skills.find_one({"_id": skill_id})
    monkeypatch.setattr(skills_module.user_skill_service, "update_skill", update_skill)
    service = SkillLifecycleService()

    asyncio.run(service.save_draft(main_id="tenant", user_id="owner", skill_id="skill", draft={
        "name": "Draft name", "description": "draft", "type": "writing_style",
    }))
    stored = db.user_skills.rows["skill"]
    assert stored["name"] == "Published name"
    assert stored["draft"]["name"] == "Draft name"
    assert stored["published_version"] == "1.0.0"
    assert stored["has_unpublished_changes"] is True

    published, release = asyncio.run(service.publish(main_id="tenant", user_id="owner", skill_id="skill", release_notes="ready"))
    assert published["name"] == "Draft name"
    assert published["published_version"] == "1.0.1"
    assert published["has_unpublished_changes"] is False
    assert release["release_notes"] == "ready"


def test_new_platform_skill_stays_draft_without_release(monkeypatch):
    db = Database()
    db.user_skills.rows["skill"] = {
        "_id": "skill", "main_id": "tenant", "user_id": "owner", "type": "workflow",
        "name": "Draft workflow", "enabled": False,
    }
    monkeypatch.setattr(lifecycle_module, "get_db", lambda: db)
    row = asyncio.run(SkillLifecycleService().initialize_draft(
        main_id="tenant", user_id="owner", skill_id="skill", draft=db.user_skills.rows["skill"], new_skill=True,
    ))
    assert row["publication_status"] == "draft"
    assert row["has_unpublished_changes"] is True
    assert db.skill_releases.rows == {}


def test_release_history_lazily_migrates_existing_skill(monkeypatch):
    db = Database()
    db.user_skills.rows["skill"] = {
        "_id": "skill", "main_id": "tenant", "user_id": "owner", "type": "writing_style",
        "name": "Legacy Skill", "description": "existing published content", "enabled": True,
    }
    monkeypatch.setattr(lifecycle_module, "get_db", lambda: db)

    releases = asyncio.run(SkillLifecycleService().list_releases(
        main_id="tenant", user_id="owner", skill_id="skill",
    ))

    assert [release["version"] for release in releases] == ["1.0.0"]
    assert db.user_skills.rows["skill"]["published_version"] == "1.0.0"
    assert next(iter(db.skill_releases.rows.values()))["migrated"] is True
