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
        def _match(doc: dict, cond: dict) -> bool:
            for key, value in cond.items():
                if key == "$and":
                    if not all(_match(doc, sub) for sub in value):
                        return False
                    continue
                if key == "$or":
                    if not any(_match(doc, sub) for sub in value):
                        return False
                    continue
                actual = doc.get(key)
                if isinstance(value, dict) and any(k.startswith("$") for k in value):
                    for op, operand in value.items():
                        if op == "$in" and actual not in operand:
                            return False
                        elif op == "$ne" and actual == operand:
                            return False
                        elif op == "$gt" and not (actual is not None and actual > operand):
                            return False
                        elif op == "$regex" and not (actual is not None and str(operand).split("^")[-1] and str(actual).startswith(str(operand).lstrip("^"))):
                            return False
                    continue
                if actual != value:
                    return False
            return True

        matched = [doc for doc in self._docs if _match(doc, query)]
        return _Cursor(matched)

    async def find_one(self, query: dict, *args, **kwargs) -> Any:
        def _match(doc: dict, cond: dict) -> bool:
            for key, value in cond.items():
                if key == "$or":
                    if not any(_match(doc, sub) for sub in value):
                        return False
                    continue
                if key == "$and":
                    if not all(_match(doc, sub) for sub in value):
                        return False
                    continue
                if doc.get(key) != value:
                    return False
            return True

        matched = [doc for doc in self._docs if _match(doc, query)]
        if not matched:
            return None
        # Honour `sort=[("seq", -1), ...]`: the real driver returns the
        # highest-seq document first, and _next_seq depends on that ordering.
        sort = kwargs.get("sort")
        if sort:
            for key, direction in reversed(list(sort)):

                def _sort_key(doc, key=key):
                    value = doc.get(key)
                    # Missing fields sort as "smallest" in MongoDB.
                    return (value is not None, value)

                matched.sort(key=_sort_key, reverse=bool(direction == -1))
        return matched[0]

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

    async def insert_many(self, docs, ordered: bool = True, **kwargs) -> Any:
        for doc in docs:
            await self.insert_one(doc)
        return None


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

        # 001 audit sink uses attribute access (db.position_role_audit_logs),
        # not only [] indexing — expose the same fake collections on both.
        def __getattr__(self, name: str) -> _FakeColl:
            if name.startswith("_") or name in ("_collections",):
                raise AttributeError(name)
            return self[name]

    return _DB(), collections


@pytest.fixture()
def seed_seq(fake_db):
    """Backfill chat history so the server-side seq check accepts a given seq.

    The commit endpoint validates the client-reported ``seq`` against the real
    next sequence (002 server-side seq validation), so a test that posts
    ``seq: N`` must first have ``N - 1`` messages stored for that session.
    """

    def _seed(session_id: str, next_seq: int, tenant_id: str = "default") -> None:
        db_obj, _collections = fake_db
        messages = db_obj["chat_messages"]
        for index in range(1, next_seq):
            messages._docs.append(
                {
                    "session_id": session_id,
                    "user_id": "u-1",
                    "tenant_id": tenant_id,
                    "seq": index,
                    "role": "user",
                    "content": f"history {index}",
                }
            )

    return _seed


@pytest.fixture()
def client(fake_db, monkeypatch):
    from app.api.endpoints import dsh_session_versioning as endpoint
    from app.core import db as db_module

    db_obj, _collections = fake_db
    monkeypatch.setattr(db_module, "get_db", lambda: db_obj)
    monkeypatch.setattr(endpoint, "get_db", lambda: db_obj)
    # 001 audit sink (FR-11): audit.py binds get_db at import time, so patch its
    # module-level name too — otherwise session events fall through to real Mongo.
    from app.governance import audit as audit_module

    monkeypatch.setattr(audit_module, "get_db", lambda: db_obj)

    def _fake_presence(db=None):
        return CoPresence(db_obj)

    monkeypatch.setattr(endpoint, "CoPresence", _fake_presence)

    async def _fake_user(authorization: str | None):
        return {"user": {"_id": "u-1"}, "tenant_id": "default"}

    monkeypatch.setattr(endpoint, "_resolve_session_user", _fake_user)

    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


def test_session_commit_and_versions(client, fake_db, seed_seq) -> None:
    db_obj, collections = fake_db
    # seq 3 implies two pre-existing messages for this session.
    seed_seq("s-1", 3)

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
    # 002 audit fix: preview is generated from the DB document, not hardcoded None.
    preview = versions.json()[0]["preview"]
    assert preview is not None
    assert preview["snapshotId"] == versions.json()[0]["snapshotId"]
    assert preview["seq"] == 3
    assert preview["summary"] == "first commit"
    assert preview["attachmentCount"] == 0

    assert len(collections.get(SNAPSHOT_COLLECTION, _FakeColl([]))._docs) == 1


def test_session_commit_unknown_session_still_persists(client) -> None:
    # commit is a snapshot write; it does not require the session to pre-exist.
    response = client.post(
        "/api/sessions/does-not-exist/commit",
        json={"seq": 1, "trigger": "idle_timeout"},
    )
    assert response.status_code == 200
    assert response.json()["trigger"] == "idle_timeout"


def test_get_session_version_includes_preview(client, fake_db) -> None:
    """002 audit fix: get_session_version returns a populated preview dict."""
    commit = client.post(
        "/api/sessions/s-1/commit",
        json={"seq": 1, "trigger": "manual", "summary": "preview test", "changed_refs": ["x"]},
    )
    assert commit.status_code == 200
    snapshot_id = commit.json()["snapshotId"]
    version = client.get(f"/api/sessions/s-1/versions/{snapshot_id}")
    assert version.status_code == 200
    preview = version.json().get("preview")
    assert preview is not None
    assert preview["seq"] == 1
    assert preview["summary"] == "preview test"
    assert preview["changedRefs"] == ["x"]
    assert preview["attachmentCount"] == 0


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


def test_session_co_presence_resolves_member_display_names(client, fake_db, monkeypatch) -> None:
    """Online members carry display names so the UI shows names, not raw ids."""
    from app.api.endpoints import dsh_session_versioning as endpoint

    db_obj, _collections = fake_db
    db_obj["end_users"]._docs.extend([
        {"_id": "u-1", "name": "张三", "login_name": "zhangsan", "email": "z@example.com", "status": "active"},
        {"_id": "u-2", "name": "Bob", "login_name": "bob", "email": "b@example.com", "status": "active"},
    ])
    # The heartbeat records the *authorized* user, so drive each beat with its own principal.
    for uid in ("u-1", "u-2"):
        async def _as_user(authorization, _uid=uid):
            return {"user": {"_id": _uid}, "tenant_id": "default"}

        monkeypatch.setattr(endpoint, "_resolve_session_user", _as_user)
        response = client.post(
            "/api/sessions/s-1/co-presence",
            json={"user_id": uid, "message_seqs": []},
        )
        assert response.status_code == 200, response.text

    body = client.get("/api/sessions/s-1/co-presence").json()
    members = body["onlineMembers"]
    by_id = {m["userId"]: m for m in members}
    assert set(by_id) == {"u-1", "u-2"}
    assert by_id["u-1"]["displayName"] == "张三"
    assert by_id["u-2"]["displayName"] == "Bob"
    # Legacy field kept alongside the rich view.
    assert sorted(body["onlineUsers"]) == ["u-1", "u-2"]


def test_session_co_presence_unknown_member_falls_back_to_id(client, fake_db, monkeypatch) -> None:
    """An unresolved member still renders: displayName stays empty (UI shows the id)."""
    from app.api.endpoints import dsh_session_versioning as endpoint

    async def _as_ghost(authorization):
        return {"user": {"_id": "ghost"}, "tenant_id": "default"}

    monkeypatch.setattr(endpoint, "_resolve_session_user", _as_ghost)
    response = client.post(
        "/api/sessions/s-1/co-presence",
        json={"user_id": "ghost", "message_seqs": []},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    member = [m for m in body["onlineMembers"] if m["userId"] == "ghost"][0]
    assert member["displayName"] == ""


# --- 2026-10-03 001-audit fixes: FR-7 secret redaction, FR-8 dereference,
#     FR-11 audit, share redemption by token ---------------------------------

HIGH_ENTROPY = "aB3xK9pQzLmV7nR2wT5sU8"  # 24 chars, high entropy, no prefix


def test_commit_redacts_secrets_and_stores_originals(client, fake_db, seed_seq) -> None:
    """FR-7: suspected secrets never land in the snapshot in plaintext."""
    from app.services.session_versioning.snapshot import SECRET_REF_COLLECTION
    from app.services.session_versioning.placeholder import PLACEHOLDER_OPEN

    db_obj, collections = fake_db
    seed_seq("s-sec", 7)
    response = client.post(
        "/api/sessions/s-sec/commit",
        json={
            "seq": 7,
            "trigger": "manual",
            "summary": f"key is {HIGH_ENTROPY}",
            "content": f"use sk-abcdefgh12345678 for auth",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert HIGH_ENTROPY not in body["summary"]
    assert PLACEHOLDER_OPEN in body["summary"]
    assert "sk-abcdefgh12345678" not in (body.get("content") or "")
    assert PLACEHOLDER_OPEN in (body.get("content") or "")
    assert body["secretRefs"], "placeholder ids must be exposed"

    # Originals live only in session_secret_refs, owner-scoped.
    refs = collections.get(SECRET_REF_COLLECTION, _FakeColl([]))._docs
    assert len(refs) == 2
    assert {row["original"] for row in refs} == {HIGH_ENTROPY, "sk-abcdefgh12345678"}
    assert all(row["session_id"] == "s-sec" for row in refs)


def test_dereference_denied_for_stranger(client, fake_db) -> None:
    """FR-8: only the session owner or a full-access admin may dereference."""
    client.post(
        "/api/sessions/s-sec/commit",
        json={"seq": 1, "trigger": "manual", "summary": f"key is {HIGH_ENTROPY}"},
    )
    from app.services.session_versioning.snapshot import SECRET_REF_COLLECTION

    ref_id = collections_secret_id(fake_db)
    # The fixture's user is u-1 (the committer = owner); a stranger cannot.
    with client_with_user(fake_db, "u-9") as stranger:
        response = stranger.get(f"/api/sessions/s-sec/secrets/{ref_id}")
    assert response.status_code == 403


def test_dereference_allowed_for_owner_and_audited(client, fake_db) -> None:
    """FR-8 + FR-11: owner dereference succeeds and lands on the 001 audit stream."""
    client.post(
        "/api/sessions/s-sec/commit",
        json={"seq": 1, "trigger": "manual", "summary": f"key is {HIGH_ENTROPY}"},
    )
    ref_id = collections_secret_id(fake_db)
    response = client.get(f"/api/sessions/s-sec/secrets/{ref_id}")
    assert response.status_code == 200, response.text
    assert response.json()["value"] == HIGH_ENTROPY

    from app.services.session_versioning.snapshot import SECRET_REF_COLLECTION

    # FR-11: commit + dereference events are on the 001 audit stream.
    audit = fake_db[0]["position_role_audit_logs"]._docs
    actions = [row["action"] for row in audit]
    assert "session.commit" in actions
    assert "session.dereference" in actions


def test_share_redemption_by_token_works(client, fake_db) -> None:
    """Share redemption was '必然失败': the endpoint passed the token but the
    store looked it up by share_id. Now the token resolves (001 audit fix)."""
    client.post(
        "/api/sessions/s-1/commit", json={"seq": 5, "trigger": "manual"}
    )
    created = client.post(
        "/api/sessions/s-1/share", json={"receiver": "u-2"}
    )
    assert created.status_code == 200, created.text
    token = created.json()["token"]
    assert token, "share view must carry the redemption token"

    response = client.post(
        "/api/sessions/s-1/share/redeem", json={"token": token}
    )
    assert response.status_code == 200, response.text
    assert response.json().get("share_id"), created.text


def test_commit_falls_back_to_chat_messages_for_redaction(client, fake_db, seed_seq, monkeypatch) -> None:
    """002 residual fix: when the client omits content, the server reads
    chat_messages as the redaction source so secrets in the real history
    are redacted before entering the snapshot (FR-7 server-side fallback)."""
    from app.api.endpoints import dsh_session_versioning as endpoint
    from app.services.session_versioning.snapshot import SECRET_REF_COLLECTION
    from app.services.session_versioning.placeholder import PLACEHOLDER_OPEN

    db_obj, collections = fake_db
    # Backfill turns 1-5 so the server-side seq check accepts seq 7 (the
    # secret-bearing message below is turn 6).
    seed_seq("s-fb", 6, tenant_id="m-1")
    # A real server-side message carrying a suspected secret.
    db_obj["chat_messages"]._docs.append({
        "session_id": "s-fb",
        "tenant_id": "m-1",
        "user_id": "u-1",
        "seq": 6,
        "role": "user",
        "content": "deploy with secret sk-abcdefgh12345678",
    })
    # Point the auth fixture at a non-default main so the tenant scope filter
    # stays a plain dict (no nested $or) in the fake DB.
    async def _user(authorization: str | None):
        return {"user": {"_id": "u-1"}, "tenant_id": "m-1"}

    monkeypatch.setattr(endpoint, "_resolve_session_user", _user)

    # No content supplied → the server must fall back to chat_messages.
    response = client.post(
        "/api/sessions/s-fb/commit",
        json={"seq": 7, "trigger": "manual", "summary": "checkpoint"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # The plaintext secret must NOT survive in the snapshot.
    assert "sk-abcdefgh12345678" not in str(body.get("content") or "")
    assert PLACEHOLDER_OPEN in str(body.get("content") or "")
    # The server-side fallback content is what was persisted.
    assert "deploy" in str(body.get("content") or "")
    # The secret original is stored in the secret-ref collection (FR-8).
    refs = collections.get(SECRET_REF_COLLECTION, _FakeColl([]))._docs
    assert any("sk-abcdefgh12345678" in str(row.get("original") or "") for row in refs)


def test_resume_returns_target_snapshot_metadata(client, fake_db, seed_seq) -> None:
    """002 audit fix: resume returns the target snapshot's metadata, not just a seq number."""
    seed_seq("s-1", 3)
    client.post(
        "/api/sessions/s-1/commit",
        json={"seq": 3, "trigger": "manual", "summary": "before resume"},
    )
    response = client.post("/api/sessions/s-1/resume", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resumeAfterSeq"] == 4
    assert body["resumedFromSnapshot"] is None  # empty snapshot_id = latest
    resumed = body.get("resumedFrom")
    assert resumed is not None, "resumedFrom must carry the target snapshot"
    assert resumed["seq"] == 3
    assert resumed["summary"] == "before resume"
    assert resumed["trigger"] == "manual"


def test_resume_with_specific_snapshot_returns_it(client, fake_db, seed_seq) -> None:
    """Resume returns the target snapshot's metadata (resumedFrom)."""
    seed_seq("s-1", 2)
    client.post(
        "/api/sessions/s-1/commit",
        json={"seq": 2, "trigger": "manual", "summary": "snap-2"},
    )
    # Resume from the latest snapshot (empty snapshot_id = latest)
    response = client.post("/api/sessions/s-1/resume", params={"snapshot_id": ""})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resumeAfterSeq"] == 3
    resumed = body.get("resumedFrom")
    assert resumed is not None
    assert resumed["seq"] == 2
    assert resumed["summary"] == "snap-2"
    assert resumed["trigger"] == "manual"


def collections_secret_id(fake_db) -> str:
    from app.services.session_versioning.snapshot import SECRET_REF_COLLECTION

    docs = fake_db[0][SECRET_REF_COLLECTION]._docs
    assert docs, "expected at least one secret ref"
    return docs[0]["token_id"]


def client_with_user(fake_db, user_id: str):
    """A TestClient acting as a different end user (for the 403 case)."""
    from contextlib import contextmanager

    from fastapi.testclient import TestClient

    from app.api.endpoints import dsh_session_versioning as endpoint
    from app.core import db as db_module
    from app.governance import audit as audit_module
    from app.main import app

    db_obj, _collections = fake_db
    original_db = db_module.get_db
    original_endpoint_db = endpoint.get_db
    original_user = endpoint._resolve_session_user
    original_audit_db = audit_module.get_db

    db_module.get_db = lambda: db_obj
    endpoint.get_db = lambda: db_obj
    audit_module.get_db = lambda: db_obj

    async def _user(authorization):
        return {"user": {"_id": user_id}, "tenant_id": "default"}

    endpoint._resolve_session_user = _user

    @contextmanager
    def _restore():
        try:
            yield TestClient(app)
        finally:
            db_module.get_db = original_db
            endpoint.get_db = original_endpoint_db
            endpoint._resolve_session_user = original_user
            audit_module.get_db = original_audit_db

    return _restore()
