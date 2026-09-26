"""002 production wiring: session versioning HTTP endpoints.

Verifies commit / versions / share / co-presence reach the 002 library over
HTTP: commit persists a snapshot to ``session_snapshots``, versions lists it,
share creates a TTL token, and co-presence reports online users.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.session_versioning.co_presence import CoPresence
from app.services.session_versioning.share import SHARE_COLLECTION
from app.services.session_versioning.snapshot import SNAPSHOT_COLLECTION


class _FakeColl:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def insert_one(self, doc: dict) -> Any:
        copy = dict(doc)
        copy["_id"] = len(self._docs) + 1
        self._docs.append(copy)

        class _R:
            inserted_id = copy["_id"]

        return _R()

    def find(self, query: dict, *args, **kwargs):
        matched = [
            doc
            for doc in self._docs
            if all(doc.get(k) == v for k, v in query.items())
        ]
        return _Cursor(matched)

    async def find_one(self, query: dict, *args, **kwargs):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    async def update_one(self, query: dict, update: dict, *args, **kwargs) -> Any:
        upsert = kwargs.get("upsert", False)
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(update.get("$set", {}))
                return _R(1)
        if upsert:
            new_doc = {**query, **update.get("$set", {})}
            new_doc["_id"] = len(self._docs) + 1
            self._docs.append(new_doc)
            return _R(1)
        return _R(0)


class _Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def sort(self, *args, **kwargs):
        key = args[0] if args else None
        if isinstance(key, str):
            self._docs.sort(key=lambda d: d.get(key) or "")
        return self

    async def to_list(self, length: int):
        return self._docs[:length]


class _R:
    def __init__(self, n: int) -> None:
        self.deleted_count = n


@pytest.fixture()
def fake_db():
    collections: dict[str, _FakeColl] = {}

    class _DB:
        def __getitem__(self, name: str) -> _FakeColl:
            if name not in collections:
                collections[name] = _FakeColl([])
            return collections[name]

    return _DB(), collections


@pytest.fixture()
def client(fake_db, monkeypatch):
    from app.api.endpoints import dsh_session_versioning as endpoint
    from app.core import db as db_module

    db_obj, _collections = fake_db
    monkeypatch.setattr(db_module, "get_db", lambda: db_obj)
    monkeypatch.setattr(endpoint, "get_db", lambda: db_obj)

    def _fake_presence(db=None):
        return CoPresence(db_obj)

    monkeypatch.setattr(endpoint, "CoPresence", _fake_presence)

    async def _fake_user(authorization: str | None):
        return {"user": {"_id": "u-1"}, "main_id": "default"}

    monkeypatch.setattr(endpoint, "_resolve_session_user", _fake_user)

    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


def test_session_commit_and_versions(client, fake_db) -> None:
    db_obj, collections = fake_db

    response = client.post(
        "/api/sessions/s-1/commit",
        json={"seq": 3, "trigger": "manual", "summary": "first commit", "changed_refs": ["a", "b"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sessionId"] == "s-1"
    assert body["seq"] == 3
    assert body["summary"] == "first commit"

    versions = client.get("/api/sessions/s-1/versions")
    assert versions.status_code == 200
    assert len(versions.json()) == 1
    assert versions.json()[0]["summary"] == "first commit"

    assert len(collections.get(SNAPSHOT_COLLECTION, _FakeColl([]))._docs) == 1


def test_session_commit_unknown_session_still_persists(client) -> None:
    # commit is a snapshot write; it does not require the session to pre-exist.
    response = client.post(
        "/api/sessions/does-not-exist/commit",
        json={"seq": 1, "trigger": "idle_timeout"},
    )
    assert response.status_code == 200
    assert response.json()["trigger"] == "idle_timeout"


def test_session_share_creates_token(client, fake_db) -> None:
    db_obj, collections = fake_db
    # Seed a snapshot so the share has a target.
    client.post(
        "/api/sessions/s-1/commit",
        json={"seq": 5, "trigger": "share", "summary": "share point"},
    )
    response = client.post(
        "/api/sessions/s-1/share",
        json={"receiver": "u-2", "receiver_role": "editor", "ttl_seconds": 600},
    )
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["active"] is True
    assert view["handover"] is True  # editor role grants handover
    assert view["expires_at"]

    shares = collections.get(SHARE_COLLECTION, _FakeColl([]))
    assert len(shares._docs) == 1


def test_session_redeem_invalid_token_is_empty_state(client) -> None:
    response = client.post(
        "/api/sessions/s-1/share/redeem",
        json={"token": "nonexistent"},
    )
    assert response.status_code == 200
    assert response.json()["active"] is False
    assert response.json()["reason"] == "share_expired_or_invalid"


def test_session_co_presence_heartbeat(client, fake_db) -> None:
    db_obj, collections = fake_db
    response = client.post(
        "/api/sessions/s-1/co-presence",
        json={"user_id": "u-1", "message_seqs": [1, 2, 3]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["userId"] == "u-1"
    assert "u-1" in body["onlineUsers"]

    presence = collections.get("presence_heartbeats", _FakeColl([]))
    assert len(presence._docs) >= 1
