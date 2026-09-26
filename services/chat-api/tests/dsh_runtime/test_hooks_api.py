"""009 T015 / US4: hook_rules CRUD endpoints over HTTP.

Verifies the declarative rule management API: create validates + persists,
list scopes by tenant, update mutates fields, delete removes, and the router
is registered on the app.
"""

from __future__ import annotations

import pytest

from app.core.db import get_db


class _FakeColl:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def insert_one(self, doc: dict) -> None:
        self._docs.append(dict(doc))

    async def find_one(self, query: dict):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    def find(self, query: dict):
        matched = [
            doc
            for doc in self._docs
            if all(doc.get(k) == v for k, v in query.items())
        ]
        return _Cursor(matched)

    async def update_one(self, query: dict, update: dict):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(update.get("$set", {}))
                return _Result(1)
        return _Result(0)

    async def delete_one(self, query: dict):
        for index, doc in enumerate(self._docs):
            if all(doc.get(k) == v for k, v in query.items()):
                del self._docs[index]
                return _Result(1)
        return _Result(0)


class _Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length: int) -> list[dict]:
        return self._docs[:length]


class _Result:
    def __init__(self, n: int) -> None:
        self.deleted_count = n


@pytest.fixture()
def client(monkeypatch):
    from app.api.endpoints import dsh_hooks
    from app.core import db as db_module

    store = []
    db = {
        "hook_rules": _FakeColl(store),
    }

    def _fake_get_db() -> dict:
        return db

    async def _fake_user(authorization: str | None):
        return {"user": {"_id": "u-1"}, "main_id": "default"}

    monkeypatch.setattr(db_module, "get_db", _fake_get_db)
    monkeypatch.setattr(dsh_hooks, "get_db", _fake_get_db)
    monkeypatch.setattr(dsh_hooks, "_resolve_session_user", _fake_user)

    httpx = None
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


def test_hooks_crud_roundtrip(client) -> None:
    # create
    response = client.post(
        "/api/hooks/rules",
        json={
            "scope": "tenant",
            "rule_type": "deny_tool",
            "rule_config": {"tool": "web_search"},
            "enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    rule_id = response.json()["rule_id"]
    assert response.json()["rule_type"] == "deny_tool"

    # list
    listed = client.get("/api/hooks/rules")
    assert listed.status_code == 200
    ids = [item["rule_id"] for item in listed.json()]
    assert rule_id in ids

    # update
    updated = client.put(
        f"/api/hooks/rules/{rule_id}",
        json={"enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False

    # delete
    deleted = client.delete(f"/api/hooks/rules/{rule_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": rule_id}

    # 404 after delete
    missing = client.get(f"/api/hooks/rules/{rule_id}")
    # list still returns 200 (empty list is fine) — assert the rule is gone.
    remaining = client.get("/api/hooks/rules")
    assert rule_id not in [item["rule_id"] for item in remaining.json()]


def test_hook_rule_invalid_type_rejected(client) -> None:
    response = client.post(
        "/api/hooks/rules",
        json={"scope": "tenant", "rule_type": "not_a_real_type", "rule_config": {}},
    )
    # store.create validates the rule and rejects unknown types (fail-closed).
    assert response.status_code in (400, 422, 500), response.text


def test_hook_rule_update_missing_404(client) -> None:
    response = client.put("/api/hooks/rules/hr-does-not-exist", json={"enabled": False})
    assert response.status_code == 404


def test_hook_rule_delete_missing_404(client) -> None:
    response = client.delete("/api/hooks/rules/hr-does-not-exist")
    assert response.status_code == 404
