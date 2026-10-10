from __future__ import annotations

import asyncio

from app.services import skill_lifecycle as lifecycle_module
from app.services.skill_lifecycle import OrganizationSkillLifecycle


def _matches(row, query):
    return all(row.get(key) == value for key, value in query.items())


class Cursor:
    def __init__(self, rows): self.rows = rows
    def sort(self, key, direction): self.rows.sort(key=lambda row: row.get(key), reverse=direction < 0); return self
    def limit(self, value): self.rows = self.rows[:value]; return self
    async def to_list(self, length): return [dict(row) for row in self.rows[:length]]


class Collection:
    def __init__(self): self.rows = {}
    async def find_one(self, query, projection=None):
        for row in self.rows.values():
            if _matches(row, query): return dict(row)
        return None
    async def insert_one(self, row): self.rows[row["_id"]] = dict(row)
    async def update_one(self, query, update):
        for key, row in self.rows.items():
            if _matches(row, query): row.update(update.get("$set") or {}); self.rows[key] = row
    def find(self, query): return Cursor([dict(row) for row in self.rows.values() if _matches(row, query)])


class Database:
    def __init__(self): self.skills = Collection(); self.organization_skill_releases = Collection()
    def __getitem__(self, name): return getattr(self, name)


def test_enterprise_draft_does_not_replace_runtime_until_publish(monkeypatch):
    db = Database()
    db.skills.rows["skill"] = {"_id": "skill", "tenant_id": "tenant", "name": "Published", "type": "workflow", "enabled": True}
    monkeypatch.setattr(lifecycle_module, "get_db", lambda: db)
    lifecycle = OrganizationSkillLifecycle()

    asyncio.run(lifecycle.save(tenant_id="tenant", skill_id="skill", draft={"name": "Draft", "type": "workflow", "config": {}}))
    assert db.skills.rows["skill"]["name"] == "Published"
    assert db.skills.rows["skill"]["draft"]["name"] == "Draft"
    assert db.skills.rows["skill"]["published_version"] == "1.0.0"

    published, release = asyncio.run(lifecycle.publish(tenant_id="tenant", skill_id="skill", notes="ready"))
    assert published["name"] == "Draft"
    assert published["published_version"] == "1.0.1"
    assert release["release_notes"] == "ready"


def test_enterprise_release_history_lazily_migrates_existing_skill(monkeypatch):
    db = Database()
    db.skills.rows["skill"] = {"_id": "skill", "tenant_id": "tenant", "name": "Legacy", "type": "writing_style"}
    monkeypatch.setattr(lifecycle_module, "get_db", lambda: db)

    releases = asyncio.run(OrganizationSkillLifecycle().releases(tenant_id="tenant", skill_id="skill"))
    assert [release["version"] for release in releases] == ["1.0.0"]
    assert db.skills.rows["skill"]["published_version"] == "1.0.0"


def test_verify_release_detects_tampered_digest():
    """004 FR-5: a stored release whose digest no longer matches its snapshot is
    rejected, and the release view now exposes its digest for verification."""
    from app.services.skill_lifecycle import OrganizationSkillLifecycle, digest as compute_digest

    lifecycle = OrganizationSkillLifecycle()
    snapshot = {"name": "Skill", "type": "workflow", "config": {}}
    row = {"_id": "rel-1", "tenant_id": "tenant", "skill_id": "skill",
           "version": "1.0.0", "snapshot": snapshot, "digest": compute_digest(snapshot)}
    assert lifecycle.verify_release(row=row) is True

    # Tamper the snapshot: the stored digest no longer matches.
    tampered = dict(row)
    tampered["snapshot"] = dict(snapshot, name="Hijacked")
    assert lifecycle.verify_release(row=tampered) is False
    # An empty digest can never verify.
    assert lifecycle.verify_release(row={"_id": "x", "snapshot": snapshot, "digest": ""}) is False

    # The caller can verify candidate content against a known digest.
    assert lifecycle.verify_release(digest=compute_digest(snapshot), snapshot=snapshot) is True
    assert lifecycle.verify_release(digest=compute_digest(snapshot), snapshot={"name": "Nope"}) is False
