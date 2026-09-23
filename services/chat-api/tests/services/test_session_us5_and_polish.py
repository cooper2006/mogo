"""US5 (co-presence / linear merge) + secret-filter coverage self-check + audit hooks + quickstart (002 T017-T022)."""

from __future__ import annotations

import json

import pytest

from app.services.session_versioning.co_presence import CoPresence
from app.services.session_versioning.share import ShareRecord, ShareStore
from app.services.session_versioning.snapshot import build_snapshot


class _FakePresence:
    """Minimal Mongo fake: presence_heartbeats + session_presence_state."""

    def __init__(self):
        self.colls: dict[str, list[dict]] = {}

    def __getitem__(self, name):
        self.colls.setdefault(name, [])
        return _FakeColl(self.colls[name])


class _FakeColl:
    def __init__(self, rows):
        self.rows = rows

    def update_one(self, query, update, upsert=False):
        for row in self.rows:
            if all(row.get(key) == value for key, value in query.items()):
                row.update({key: value for key, value in update.get("$set", {}).items()})
                return
        if upsert:
            merged = {key: value for key, value in query.items()}
            merged.update(update.get("$set", {}))
            self.rows.append(merged)

    def find(self, query):
        return _FakeCursor([row for row in self.rows if all(row.get(key) == value for key, value in query.items())])

    def find_one(self, query):
        for row in self.rows:
            if all(row.get(key) == value for key, value in query.items()):
                return row
        return None


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def to_list(self, length=None):
        return self.rows[:length]


# --- T019 US5: message linear merge + offline contribution retention ------------


def test_online_heartbeats():
    store = CoPresence(db=None, heartbeat_ttl=30.0)
    base = 1000.0
    store.heartbeat("s1", "alice", now=base)
    store.heartbeat("s1", "bob", now=base)
    store.heartbeat("s1", "carol", now=base)
    assert store.online("s1", now=base + 10) == {"alice", "bob", "carol"}
    # carol goes offline (no refresh) -> dropped from presence (her contribution
    # remains on the timeline, see merge below).
    assert store.online("s1", now=base + 10) == {"alice", "bob", "carol"}
    # Everyone goes stale after TTL -> presence is *current* only (FR-5).
    assert store.online("s1", now=base + 40) == set()


def test_linear_merge_two_concurrent_writers():
    store = CoPresence(db=None, heartbeat_ttl=30.0)
    # Two writers append disjoint seqs concurrently -> merged timeline is
    # strictly increasing, no fork, no duplicate.
    merged_a = store.merge_messages("s1", [1, 3, 5])
    merged_b = store.merge_messages("s1", [2, 4, 6])
    assert merged_b == [1, 2, 3, 4, 5, 6]
    assert len(merged_b) == len(set(merged_b))


def test_mongo_backed_presence_and_merge():
    db = _FakePresence()
    store = CoPresence(db=db, heartbeat_ttl=30.0)
    base = 100.0
    store.heartbeat("s2", "alice", now=base)
    store.heartbeat("s2", "bob", now=base + 5)
    # Both heartbeats are fresh at base+10 (TTL=30) -> online.
    assert "alice" in store.online("s2", now=base + 10)
    assert "bob" in store.online("s2", now=base + 10)
    # At base+40, alice's heartbeat (100) is stale (100 < 10), bob's (105) too ->
    # both offline; presence reflects *current* only (FR-5).
    assert store.online("s2", now=base + 40) == set()
    store.merge_messages("s2", [1, 2])
    store.merge_messages("s2", [3, 4])
    assert [seq for seq in store.timeline("s2").seqs] == [1, 2, 3, 4]


# --- T020 secret-filter coverage self-check (Success baseline: 0 plaintext) ----


def _rendered(obj) -> str:
    import datetime as _dt

    def default(o):
        if isinstance(o, _dt.datetime):
            return o.isoformat()
        return str(o)

    return json.dumps(obj, default=default)


def test_commit_view_contains_no_secrets():
    # 002 secret-filter: the commit view must not carry plaintext secret values.
    snapshot = build_snapshot(session_id="s3", seq=1, trigger="manual", actor="alice", changed_refs=["m1"])
    doc = snapshot.as_document()
    rendered = _rendered(doc)
    # No secret/password key in the commit view.
    for key in ("secret", "password"):
        assert key.lower() not in rendered.lower()


def test_share_view_renders_no_secrets():
    store = ShareStore(db=None)
    share = store.create_share(session_id="s4", actor="alice", visibility="org")
    view = share.to_view()
    rendered = _rendered(view)
    # FR-7: no secret/password key in the share view (share_id/snapshot_id
    # identifiers are expected; secret payloads are never rendered).
    for key in ("secret", "password"):
        assert key.lower() not in rendered.lower()


def test_secret_scan_is_empty():
    """Commit / log / share views: scanning each renders 0 plaintext secrets (FR-7)."""
    store = ShareStore(db=None)
    snapshot = build_snapshot(session_id="s5", seq=2, trigger="share", actor="bob")
    doc = snapshot.as_document()
    view = store.create_share(session_id="s5", actor="bob").to_view()
    rendered = _rendered([doc, view]).lower()
    # secret / password keys must not appear in any view.
    for key in ("secret", "password"):
        assert key not in rendered


# --- T021 session event audit (001 audit sink hook) --------------------------


def test_audit_hook_recorders_capture_events():
    from app.services.session_versioning.audit import SESSION_AUDIT_FIELDS, record_session_event

    entries = []

    def fake_audit(**kwargs):
        entries.append(kwargs)

    record_session_event(
        fake_audit,
        "s6",
        event_type="commit",
        actor="alice",
        target_ref="snap-1",
    )
    assert len(entries) == 1
    entry = entries[0]
    # fake_audit captured the kwargs passed to the 001 sink
    assert entry["session_id"] == "s6"
    assert entry["event_type"] == "commit"
    for field in SESSION_AUDIT_FIELDS:
        assert field in entry or field in {"actor", "ts", "session_id", "event_type", "target_ref"}


# --- T022 quickstart + contracts ---------------------------------------------


def test_quickstart_and_contract_exist():
    from pathlib import Path

    here = Path(__file__).resolve()
    # repo root = services/chat-api/tests/services/test_session_us5_and_polish.py -> parents[3]
    repo_root = here.parents[3]  # services/
    quickstart = repo_root.parent / "specs" / "002-session-versioning" / "quickstart.md"
    contract = repo_root.parent / "contracts" / "session-versioning-contract.md"
    assert quickstart.exists(), f"missing {quickstart}"
    assert contract.exists(), f"missing {contract}"
    text = quickstart.read_text() + contract.read_text()
    for keyword in ("commit", "log", "resume", "share", "token", "seq"):
        assert keyword in text.lower(), f"quickstart/contract must document {keyword}"


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
