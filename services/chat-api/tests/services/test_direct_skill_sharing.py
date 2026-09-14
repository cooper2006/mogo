from __future__ import annotations

import asyncio
import re

import pytest

from app.services.skill_packages import installer as installer_module
from app.services.skill_sharing import direct_service as direct_module
from app.services.skill_sharing import distribution as distribution_module
from app.services.skill_sharing import member_directory as directory_module
from app.services.skill_sharing import legacy_migration as migration_module
from app.services.skill_sharing import service as share_module
from app.services.skill_sharing.direct_service import DirectSkillShareService
from app.services.skill_sharing.member_directory import SkillShareMemberDirectory
from app.services.skill_sharing.service import SkillShareError
from app.services.skill_sharing.distribution import SkillDistributionService
from app.services.skill_sharing.legacy_migration import LegacySkillShareMigration


def _value_matches(value, condition):
    if not isinstance(condition, dict):
        return value == condition
    if "$options" in condition and len(condition) == 1:
        return True
    for operator, expected in condition.items():
        if operator == "$options":
            continue
        if operator == "$in" and value not in expected:
            return False
        if operator == "$ne" and value == expected:
            return False
        if operator == "$gt" and not (value > expected):
            return False
        if operator == "$lt" and not (value < expected):
            return False
        if operator == "$regex":
            flags = re.I if "i" in str(condition.get("$options") or "") else 0
            if re.search(str(expected), str(value or ""), flags) is None:
                return False
    return True


def _matches(row, query):
    if "$and" in query and not all(_matches(row, part) for part in query["$and"]):
        return False
    if "$or" in query and not any(_matches(row, part) for part in query["$or"]):
        return False
    return all(
        _value_matches(row.get(key), value)
        for key, value in query.items()
        if key not in {"$and", "$or"}
    )


class Result:
    def __init__(self, matched_count=1):
        self.matched_count = matched_count


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction):
        self.rows.sort(key=lambda row: row.get(key), reverse=direction < 0)
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    async def to_list(self, length):
        return [dict(row) for row in self.rows[:length]]


class Collection:
    def __init__(self):
        self.rows = {}

    def find(self, query, projection=None):
        rows = [self._project(row, projection) for row in self.rows.values() if _matches(row, query)]
        return Cursor(rows)

    async def find_one(self, query, projection=None):
        rows = await self.find(query, projection).to_list(1)
        return rows[0] if rows else None

    async def insert_one(self, row):
        self.rows[row["_id"]] = dict(row)

    async def insert_many(self, rows):
        for row in rows:
            await self.insert_one(row)

    async def update_one(self, query, update):
        for key, row in self.rows.items():
            if _matches(row, query):
                row.update(update["$set"])
                self.rows[key] = row
                return Result(1)
        return Result(0)

    async def update_many(self, query, update):
        count = 0
        for key, row in self.rows.items():
            if _matches(row, query):
                row.update(update["$set"])
                self.rows[key] = row
                count += 1
        return Result(count)

    async def count_documents(self, query):
        return sum(1 for row in self.rows.values() if _matches(row, query))

    async def delete_one(self, query):
        for key, row in list(self.rows.items()):
            if _matches(row, query):
                self.rows.pop(key)
                return

    async def delete_many(self, query):
        for key, row in list(self.rows.items()):
            if _matches(row, query):
                self.rows.pop(key)

    @staticmethod
    def _project(row, projection):
        if not projection:
            return dict(row)
        return {key: value for key, value in row.items() if key == "_id" or projection.get(key)}


class Database:
    def __init__(self):
        self.user_skills = Collection()
        self.skill_packages = Collection()
        self.skill_shares = Collection()
        self.skill_share_deliveries = Collection()
        self.skill_distributions = Collection()
        self.skill_distribution_releases = Collection()
        self.skill_distribution_members = Collection()
        self.skill_update_notifications = Collection()
        self.end_users = Collection()
        self.skills = Collection()

    def __getitem__(self, name):
        return getattr(self, name)


def _install_db(monkeypatch, db):
    monkeypatch.setattr(direct_module, "get_db", lambda: db)
    monkeypatch.setattr(distribution_module, "get_db", lambda: db)
    monkeypatch.setattr(directory_module, "get_db", lambda: db)
    monkeypatch.setattr(share_module, "get_db", lambda: db)
    monkeypatch.setattr(installer_module, "get_db", lambda: db)
    monkeypatch.setattr(migration_module, "get_db", lambda: db)


def _seed(db):
    db.end_users.rows = {
        "owner": {"_id": "owner", "main_id": "tenant", "status": "active", "name": "Owner", "login_name": "owner"},
        "alice": {"_id": "alice", "main_id": "tenant", "status": "active", "name": "Alice", "login_name": "alice"},
        "bob": {"_id": "bob", "main_id": "tenant", "status": "active", "name": "Bob", "login_name": "bob"},
        "outsider": {"_id": "outsider", "main_id": "other", "status": "active", "name": "Outsider", "login_name": "out"},
    }
    db.user_skills.rows["source"] = {
        "_id": "source", "main_id": "tenant", "user_id": "owner",
        "name": "Team Helper", "description": "Shared safely", "skill_markdown": "Follow the team rules.",
        "config": {"tone": "clear", "api_key": "never-share"},
    }


def test_direct_share_creates_one_snapshot_and_recipient_inboxes(monkeypatch):
    db = Database()
    _seed(db)
    _install_db(monkeypatch, db)
    service = DirectSkillShareService()

    result = asyncio.run(service.create(
        main_id="tenant", owner_user_id="owner", skill_id="source", recipient_user_ids=["alice", "bob"],
    ))
    assert result["recipientCount"] == 2
    assert len(db.skill_shares.rows) == 1
    assert len(db.skill_share_deliveries.rows) == 2
    snapshot = next(iter(db.skill_shares.rows.values()))
    assert snapshot["profile"]["config"] == {"tone": "clear"}

    inbox = asyncio.run(service.inbox(main_id="tenant", recipient_user_id="alice"))
    assert inbox["pendingCount"] == 1
    assert asyncio.run(service.pending_count(main_id="tenant", recipient_user_id="alice")) == 1
    assert asyncio.run(service.pending_count(main_id="other", recipient_user_id="alice")) == 0
    assert inbox["items"][0]["name"] == "Team Helper"
    assert inbox["items"][0]["sender"]["displayName"] == "Owner"

    asyncio.run(service.create(
        main_id="tenant", owner_user_id="owner", skill_id="source", recipient_user_ids=["alice"],
    ))
    alice_rows = [row for row in db.skill_share_deliveries.rows.values() if row["recipient_user_id"] == "alice"]
    assert sorted(row["status"] for row in alice_rows) == ["pending", "superseded"]


def test_member_directory_is_tenant_scoped_searchable_and_paginated(monkeypatch):
    db = Database()
    _seed(db)
    _install_db(monkeypatch, db)
    directory = SkillShareMemberDirectory()

    first = asyncio.run(directory.search(
        main_id="tenant", requester_user_id="owner", keyword="", limit=1,
    ))
    assert [item["userId"] for item in first["items"]] == ["alice"]
    assert first["hasMore"] is True
    second = asyncio.run(directory.search(
        main_id="tenant", requester_user_id="owner", keyword="", cursor=first["nextCursor"], limit=1,
    ))
    assert [item["userId"] for item in second["items"]] == ["bob"]
    match = asyncio.run(directory.search(
        main_id="tenant", requester_user_id="owner", keyword="bo", limit=10,
    ))
    assert [item["displayName"] for item in match["items"]] == ["Bob"]


def test_recipient_accepts_independent_copy_and_cannot_cross_tenant(monkeypatch):
    db = Database()
    _seed(db)
    _install_db(monkeypatch, db)
    service = DirectSkillShareService()
    created = asyncio.run(service.create(
        main_id="tenant", owner_user_id="owner", skill_id="source", recipient_user_ids=["alice"],
    ))
    delivery_id = next(iter(db.skill_share_deliveries.rows))

    installed = asyncio.run(service.accept(
        main_id="tenant", recipient_user_id="alice", delivery_id=delivery_id,
    ))
    assert installed["name"] == "Team Helper"
    recipient_skill = next(row for row in db.user_skills.rows.values() if row.get("user_id") == "alice")
    assert recipient_skill["visibility"] == "private"
    assert recipient_skill["config"] == {"tone": "clear"}
    assert recipient_skill["package_source"]["kind"] == "movo_share"
    assert recipient_skill["package_source"]["mode"] == "direct"
    assert recipient_skill["package_source"]["sender"]["displayName"] == "Owner"
    assert db.skill_share_deliveries.rows[delivery_id]["status"] == "accepted"
    assert asyncio.run(service.inbox(main_id="tenant", recipient_user_id="alice"))["pendingCount"] == 0

    with pytest.raises(SkillShareError) as cross_tenant:
        asyncio.run(service.accept(main_id="other", recipient_user_id="alice", delivery_id=delivery_id))
    assert cross_tenant.value.code == "skill_share_delivery_unavailable"
    assert created["recipientCount"] == 1


def test_invalid_recipient_is_rejected_and_decline_removes_pending(monkeypatch):
    db = Database()
    _seed(db)
    _install_db(monkeypatch, db)
    service = DirectSkillShareService()

    with pytest.raises(SkillShareError) as outsider:
        asyncio.run(service.create(
            main_id="tenant", owner_user_id="owner", skill_id="source", recipient_user_ids=["outsider"],
        ))
    assert outsider.value.code == "skill_share_recipient_invalid"

    asyncio.run(service.create(
        main_id="tenant", owner_user_id="owner", skill_id="source", recipient_user_ids=["bob"],
    ))
    delivery_id = next(iter(db.skill_share_deliveries.rows))
    asyncio.run(service.decline(main_id="tenant", recipient_user_id="bob", delivery_id=delivery_id))
    assert db.skill_share_deliveries.rows[delivery_id]["status"] == "declined"
    assert asyncio.run(service.inbox(main_id="tenant", recipient_user_id="bob"))["pendingCount"] == 0


def test_published_change_notifies_recipient_and_updates_same_copy(monkeypatch):
    db = Database()
    _seed(db)
    _install_db(monkeypatch, db)
    service = DirectSkillShareService()
    asyncio.run(service.create(
        main_id="tenant", owner_user_id="owner", skill_id="source", recipient_user_ids=["alice"],
    ))
    inbox = asyncio.run(service.inbox(main_id="tenant", recipient_user_id="alice"))
    installed = asyncio.run(service.accept(
        main_id="tenant", recipient_user_id="alice", delivery_id=inbox["items"][0]["deliveryId"],
    ))
    installed_id = installed["id"]
    db.user_skills.rows["source"]["skill_markdown"] = "Updated shared instructions."
    release = asyncio.run(SkillDistributionService().publish_from_skill(
        main_id="tenant", owner_user_id="owner", source_skill_id="source", version="1.0.1", release_notes="Improved",
    ))
    assert release is not None
    updates = asyncio.run(SkillDistributionService().list_updates(main_id="tenant", recipient_user_id="alice"))
    assert updates["pendingCount"] == 1
    assert updates["items"][0]["currentVersion"] == "1.0.0"
    assert updates["items"][0]["newVersion"] == "1.0.1"
    assert updates["items"][0]["releaseNotes"] == "Improved"
    assert "instructions" in updates["items"][0]["changes"]
    result = asyncio.run(SkillDistributionService().install_update(
        main_id="tenant", recipient_user_id="alice", notification_id=updates["items"][0]["id"],
    ))
    assert result["id"] == installed_id
    assert db.user_skills.rows[installed_id]["skill_markdown"] == "Updated shared instructions."


def test_legacy_shared_install_is_backfilled_without_resharing(monkeypatch):
    db = Database()
    _seed(db)
    _install_db(monkeypatch, db)
    service = DirectSkillShareService()
    asyncio.run(service.create(
        main_id="tenant", owner_user_id="owner", skill_id="source", recipient_user_ids=["alice"],
    ))
    delivery_id = next(iter(db.skill_share_deliveries.rows))
    installed = asyncio.run(service.accept(
        main_id="tenant", recipient_user_id="alice", delivery_id=delivery_id,
    ))

    share = next(iter(db.skill_shares.rows.values()))
    share.pop("distribution_id", None); share.pop("release_id", None); share.pop("release_version", None)
    recipient = db.user_skills.rows[installed["id"]]
    source = dict(recipient["package_source"])
    source.pop("distributionId", None); source.pop("releaseId", None)
    recipient["package_source"] = source
    recipient.pop("distribution_id", None)
    db.skill_distributions.rows.clear(); db.skill_distribution_releases.rows.clear(); db.skill_distribution_members.rows.clear()

    migration = LegacySkillShareMigration()
    asyncio.run(migration.migrate_owned(main_id="tenant", owner_user_id="owner"))
    assert db.skill_shares.rows[share["_id"]]["distribution_id"]
    asyncio.run(migration.migrate_installed(
        main_id="tenant", recipient_user_id="alice",
    ))

    migrated = db.user_skills.rows[installed["id"]]
    assert migrated["package_source"]["distributionId"]
    assert migrated["package_source"]["releaseId"]
    assert len(db.skill_distribution_members.rows) == 1
