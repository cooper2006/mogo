from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.services.personal_knowledge_lifecycle import activate_indexed_document, update_current_resource


def _matches(row, query):
    return all(row.get(key) == value for key, value in query.items())


class _Result:
    def __init__(self, matched_count):
        self.matched_count = matched_count


class _Collection:
    def __init__(self, row):
        self.row = row

    async def find_one(self, query):
        return dict(self.row) if _matches(self.row, query) else None

    async def update_one(self, query, update):
        if not _matches(self.row, query):
            return _Result(0)
        self.row.update(update["$set"])
        return _Result(1)


class _Db:
    def __init__(self, resource):
        self.knowledge_resources = _Collection(resource)


def _document(document_id):
    return {
        "_id": document_id,
        "main_id": "tenant",
        "scope": "personal",
        "resource_id": "resource",
    }


def test_only_latest_processing_document_can_update_resource_status():
    db = _Db({
        "_id": "resource",
        "main_id": "tenant",
        "deleted_at": None,
        "active_document_id": "old-active",
        "processing_document_id": "latest",
        "status": "pending_parse",
    })

    changed = asyncio.run(update_current_resource(db, _document("stale"), {"status": "failed"}))

    assert changed is False
    assert db.knowledge_resources.row["status"] == "pending_parse"


def test_latest_indexed_document_switches_active_version_atomically():
    db = _Db({
        "_id": "resource",
        "main_id": "tenant",
        "deleted_at": None,
        "active_document_id": "old-active",
        "processing_document_id": "latest",
        "status": "parsed",
    })

    activated, previous = asyncio.run(activate_indexed_document(
        db,
        _document("latest"),
        updated_at=datetime.now(timezone.utc),
    ))

    assert activated is True
    assert previous == "old-active"
    assert db.knowledge_resources.row["active_document_id"] == "latest"
    assert db.knowledge_resources.row["processing_document_id"] == ""
    assert db.knowledge_resources.row["status"] == "indexed"


def test_stale_index_completion_cannot_replace_latest_version():
    db = _Db({
        "_id": "resource",
        "main_id": "tenant",
        "deleted_at": None,
        "active_document_id": "old-active",
        "processing_document_id": "latest",
        "status": "pending_parse",
    })

    activated, previous = asyncio.run(activate_indexed_document(
        db,
        _document("stale"),
        updated_at=datetime.now(timezone.utc),
    ))

    assert activated is False
    assert previous == ""
    assert db.knowledge_resources.row["active_document_id"] == "old-active"
    assert db.knowledge_resources.row["processing_document_id"] == "latest"
