from __future__ import annotations

import asyncio

import pytest

from app.services.personal_knowledge import access as access_module
from app.services.personal_knowledge import service as service_module
from app.services.personal_knowledge import inactive_access as inactive_access_module
from app.services.personal_knowledge.access import PersonalKnowledgeAccessService
from app.services.personal_knowledge.inactive_access import PersonalKnowledgeInactiveAccessService
from app.services.personal_knowledge.service import PersonalKnowledgeService


def matches(row, query):
    for key, expected in query.items():
        value = row.get(key)
        if isinstance(expected, dict) and "$in" in expected:
            if value not in expected["$in"]: return False
        elif value != expected: return False
    return True


class Cursor:
    def __init__(self, rows): self.rows = rows
    def sort(self, key, direction): return self
    async def to_list(self, length): return [dict(row) for row in self.rows[:length]]


class Collection:
    def __init__(self): self.rows = {}
    async def find_one(self, query, projection=None):
        return next((dict(row) for row in self.rows.values() if matches(row, query)), None)
    def find(self, query, projection=None): return Cursor([dict(row) for row in self.rows.values() if matches(row, query)])
    async def insert_one(self, row): self.rows[row["_id"]] = dict(row)
    async def update_one(self, query, update):
        for key, row in self.rows.items():
            if matches(row, query): row.update(update["$set"]); self.rows[key] = row; return
    async def update_many(self, query, update):
        for key, row in self.rows.items():
            if matches(row, query): row.update(update["$set"]); self.rows[key] = row


class Db:
    def __init__(self):
        self.knowledge_resources = Collection(); self.resource_grants = Collection()
        self.personal_knowledge_directories = Collection(); self.knowledge_documents = Collection()
        self.end_users = Collection(); self.resource_feedback_notifications = Collection()
    def __getitem__(self, name): return getattr(self, name)


class Members:
    async def require_members(self, *, user_ids, **kwargs):
        return [{"_id": item, "name": item, "login_name": item} for item in user_ids]
    @staticmethod
    def member_view(row): return {"userId": str(row["_id"]), "displayName": row.get("name", "")}


def install(monkeypatch):
    db = Db()
    db.knowledge_resources.rows["knowledge"] = {
        "_id": "knowledge", "main_id": "tenant", "owner_user_id": "A", "deleted_at": None,
        "name": "制度", "status": "indexed",
    }
    monkeypatch.setattr(access_module, "get_db", lambda: db)
    monkeypatch.setattr(service_module, "get_db", lambda: db)
    monkeypatch.setattr(inactive_access_module, "get_db", lambda: db)
    return db


def test_owner_and_shared_user_can_view_but_outsider_cannot(monkeypatch):
    db = install(monkeypatch)
    access = PersonalKnowledgeAccessService()
    assert asyncio.run(access.require_view(main_id="tenant", user_id="A", resource_id="knowledge")).is_owner
    db.resource_grants.rows["B"] = {
        "_id": "B", "main_id": "tenant", "resource_type": "personal_knowledge",
        "resource_id": "knowledge", "recipient_user_id": "B", "status": "active", "can_reshare": True,
    }
    assert asyncio.run(access.require_view(main_id="tenant", user_id="B", resource_id="knowledge")).can_share
    with pytest.raises(PermissionError):
        asyncio.run(access.require_view(main_id="tenant", user_id="C", resource_id="knowledge"))
    with pytest.raises(LookupError):
        asyncio.run(access.require_view(main_id="other", user_id="A", resource_id="knowledge"))


def test_reshare_permission_and_owner_revoke(monkeypatch):
    db = install(monkeypatch)
    service = PersonalKnowledgeService(); service.members = Members()
    asyncio.run(service.share(main_id="tenant", user_id="A", resource_id="knowledge", recipients=[{"userId": "B", "canReshare": True}]))
    asyncio.run(service.share(main_id="tenant", user_id="B", resource_id="knowledge", recipients=[{"userId": "C", "canReshare": False}]))
    by_recipient = {row["recipient_user_id"]: row for row in db.resource_grants.rows.values()}
    assert by_recipient["B"]["can_reshare"] is True
    assert by_recipient["C"]["granted_by_user_id"] == "B"
    with pytest.raises(PermissionError):
        asyncio.run(service.share(main_id="tenant", user_id="C", resource_id="knowledge", recipients=[{"userId": "D", "canReshare": False}]))
    asyncio.run(service.revoke(main_id="tenant", user_id="A", resource_id="knowledge", recipient_user_id="B"))
    assert by_recipient["B"]["status"] == "revoked"
    assert by_recipient["C"]["status"] == "active"


def test_sharer_can_only_revoke_people_they_shared_to(monkeypatch):
    db = install(monkeypatch)
    service = PersonalKnowledgeService(); service.members = Members()
    asyncio.run(service.share(main_id="tenant", user_id="A", resource_id="knowledge", recipients=[{"userId": "B", "canReshare": True}, {"userId": "D", "canReshare": False}]))
    asyncio.run(service.share(main_id="tenant", user_id="B", resource_id="knowledge", recipients=[{"userId": "C", "canReshare": False}]))
    asyncio.run(service.revoke(main_id="tenant", user_id="B", resource_id="knowledge", recipient_user_id="C"))
    with pytest.raises(PermissionError):
        asyncio.run(service.revoke(main_id="tenant", user_id="B", resource_id="knowledge", recipient_user_id="D"))


def test_owner_can_revoke_an_entire_reshare_chain(monkeypatch):
    db = install(monkeypatch)
    service = PersonalKnowledgeService(); service.members = Members()
    asyncio.run(service.share(main_id="tenant", user_id="A", resource_id="knowledge", recipients=[{"userId": "B", "canReshare": True}]))
    asyncio.run(service.share(main_id="tenant", user_id="B", resource_id="knowledge", recipients=[{"userId": "C", "canReshare": True}]))
    asyncio.run(service.share(main_id="tenant", user_id="C", resource_id="knowledge", recipients=[{"userId": "D", "canReshare": False}]))
    asyncio.run(service.revoke(main_id="tenant", user_id="A", resource_id="knowledge", recipient_user_id="B", cascade=True))
    statuses = {row["recipient_user_id"]: row["status"] for row in db.resource_grants.rows.values()}
    assert statuses == {"B": "revoked", "C": "revoked", "D": "revoked"}


def test_resharing_to_an_existing_recipient_does_not_steal_the_grant(monkeypatch):
    db = install(monkeypatch)
    service = PersonalKnowledgeService(); service.members = Members()
    asyncio.run(service.share(main_id="tenant", user_id="A", resource_id="knowledge", recipients=[{"userId": "B", "canReshare": True}, {"userId": "C", "canReshare": False}]))
    asyncio.run(service.share(main_id="tenant", user_id="B", resource_id="knowledge", recipients=[{"userId": "C", "canReshare": True}]))
    grant = next(row for row in db.resource_grants.rows.values() if row["recipient_user_id"] == "C")
    assert grant["granted_by_user_id"] == "A"
    assert grant["can_reshare"] is False


def test_shared_list_keeps_each_new_share_unread_until_detail_is_opened(monkeypatch):
    db = install(monkeypatch)
    db.resource_grants.rows["B"] = {
        "_id": "B", "main_id": "tenant", "resource_type": "personal_knowledge",
        "resource_id": "knowledge", "recipient_user_id": "B", "status": "active",
        "granted_by_user_id": "A", "can_reshare": False, "seen_at": None,
    }

    async def no_feedback(**kwargs):
        return {}

    monkeypatch.setattr(
        service_module.personal_knowledge_feedback_summary_service,
        "unread_by_resource",
        no_feedback,
    )
    result = asyncio.run(PersonalKnowledgeService().list_resources(
        main_id="tenant", user_id="B", view="shared",
    ))
    assert result["items"][0]["seen"] is False
    assert db.resource_grants.rows["B"]["seen_at"] is None


def test_deleted_knowledge_tombstone_can_be_acknowledged_without_restoring_access(monkeypatch):
    db = install(monkeypatch)
    db.knowledge_resources.rows["knowledge"].update({
        "status": "deleted", "deleted_at": service_module._now(),
        "active_document_id": "document",
    })
    db.resource_grants.rows["B"] = {
        "_id": "B", "main_id": "tenant", "resource_type": "personal_knowledge",
        "resource_id": "knowledge", "recipient_user_id": "B", "status": "revoked",
        "granted_by_user_id": "A", "can_reshare": True, "seen_at": None,
    }
    db.resource_feedback_notifications.rows["notice"] = {
        "_id": "notice", "main_id": "tenant", "resource_type": "personal_knowledge",
        "resource_id": "knowledge", "recipient_user_id": "B", "status": "unread",
    }

    inactive_service = PersonalKnowledgeInactiveAccessService()
    access = asyncio.run(inactive_service.resolve(main_id="tenant", user_id="B", resource_id="knowledge"))
    assert access is not None and access.deleted
    asyncio.run(inactive_service.acknowledge(access=access, user_id="B"))
    assert db.resource_grants.rows["B"]["seen_at"] is not None
    assert db.resource_feedback_notifications.rows["notice"]["status"] == "read"

    view = PersonalKnowledgeService.resource_view(access.resource, grant=db.resource_grants.rows["B"])
    assert view["accessStatus"] == "deleted"
    assert view["activeDocumentId"] == ""
    assert view["canReshare"] is False

    asyncio.run(inactive_service.dismiss_deleted(main_id="tenant", user_id="B", resource_id="knowledge"))
    assert db.resource_grants.rows["B"]["status"] == "dismissed"
    assert asyncio.run(inactive_service.resolve(main_id="tenant", user_id="B", resource_id="knowledge")) is None
