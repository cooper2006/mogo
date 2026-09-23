"""Tests for session snapshots (feature 002): commit triggers / store / resume."""

from __future__ import annotations

import pytest

from app.services.session_versioning.snapshot import (
    AttachmentRef,
    CommitPolicy,
    CommitTrigger,
    SessionSnapshot,
    SnapshotError,
    build_snapshot,
)
from app.services.session_versioning.store import SnapshotStore


# --- snapshot model ----------------------------------------------------------

def test_snapshot_requires_session_and_non_negative_seq() -> None:
    with pytest.raises(SnapshotError):
        SessionSnapshot(session_id="", seq=1)
    with pytest.raises(SnapshotError):
        SessionSnapshot(session_id="s", seq=-1)


def test_build_snapshot_derives_summary() -> None:
    snapshot = build_snapshot(
        session_id="s", seq=3, trigger=CommitTrigger.MANUAL.value, changed_refs=["a", "b"]
    )
    assert "2 项" in snapshot.summary


def test_build_snapshot_default_summary_when_no_changes() -> None:
    snapshot = build_snapshot(session_id="s", seq=1, trigger=CommitTrigger.MANUAL.value)
    assert snapshot.summary == "会话进度快照"


def test_snapshot_document_holds_attachment_pointers_only() -> None:
    snapshot = build_snapshot(
        session_id="s",
        seq=1,
        trigger=CommitTrigger.MANUAL.value,
        attachments=[AttachmentRef(name="a.pdf", storage_ref="oss://bucket/a.pdf", size_bytes=123)],
    )
    document = snapshot.as_document()
    assert document["attachment_refs"][0]["storage_ref"] == "oss://bucket/a.pdf"


# --- commit policy -----------------------------------------------------------

def test_idle_commit_triggers_past_threshold() -> None:
    policy = CommitPolicy(idle_seconds=900)
    assert policy.should_commit_on_idle(idle_for_seconds=1000) is True
    assert policy.should_commit_on_idle(idle_for_seconds=100) is False


def test_idle_commit_can_be_disabled() -> None:
    policy = CommitPolicy(commit_on_idle=False, idle_seconds=1)
    assert policy.should_commit_on_idle(idle_for_seconds=999) is False


def test_key_tool_commit_matches_configured_tools() -> None:
    policy = CommitPolicy(key_tools=frozenset({"deploy"}))
    assert policy.should_commit_on_tool("deploy") is True
    assert policy.should_commit_on_tool("read") is False


def test_key_tool_commit_all_tools_when_unset() -> None:
    policy = CommitPolicy()
    assert policy.should_commit_on_tool("anything") is True


# --- store: commit / log -----------------------------------------------------

def test_commit_assigns_snapshot_id() -> None:
    store = SnapshotStore()
    snapshot = store.commit(build_snapshot(session_id="s", seq=1, trigger="manual"))
    assert snapshot.snapshot_id
    assert len(store) == 1


def test_log_is_ordered_by_seq() -> None:
    store = SnapshotStore()
    store.commit(build_snapshot(session_id="s", seq=3, trigger="manual"))
    store.commit(build_snapshot(session_id="s", seq=1, trigger="manual"))
    store.commit(build_snapshot(session_id="s", seq=2, trigger="manual"))
    assert [item.seq for item in store.log("s")] == [1, 2, 3]


def test_latest_returns_highest_seq() -> None:
    store = SnapshotStore()
    store.commit(build_snapshot(session_id="s", seq=1, trigger="manual"))
    store.commit(build_snapshot(session_id="s", seq=5, trigger="manual"))
    assert store.latest("s").seq == 5


def test_log_is_scoped_per_session() -> None:
    store = SnapshotStore()
    store.commit(build_snapshot(session_id="s1", seq=1, trigger="manual"))
    store.commit(build_snapshot(session_id="s2", seq=1, trigger="manual"))
    assert len(store.log("s1")) == 1
    assert len(store.log("s2")) == 1


# --- store: preview ----------------------------------------------------------

def test_preview_latest_snapshot() -> None:
    store = SnapshotStore()
    store.commit(
        build_snapshot(session_id="s", seq=2, trigger="manual", actor="u1", changed_refs=["x"])
    )
    preview = store.preview("s")
    assert preview["seq"] == 2
    assert preview["actor"] == "u1"
    assert preview["changedRefs"] == ["x"]


def test_preview_unknown_session_is_empty() -> None:
    assert SnapshotStore().preview("nope") == {}


# --- store: resume -----------------------------------------------------------

def test_resume_continues_after_target_snapshot() -> None:
    store = SnapshotStore()
    store.commit(build_snapshot(session_id="s", seq=1, trigger="manual"))
    store.commit(build_snapshot(session_id="s", seq=4, trigger="manual"))
    snapshot_id = store.log("s")[0].snapshot_id
    # resuming from seq=1 continues at 2, never resets to 1
    assert store.resume_point("s", snapshot_id=snapshot_id) == 2


def test_resume_defaults_to_latest() -> None:
    store = SnapshotStore()
    store.commit(build_snapshot(session_id="s", seq=1, trigger="manual"))
    store.commit(build_snapshot(session_id="s", seq=7, trigger="manual"))
    assert store.resume_point("s") == 8


def test_resume_empty_session_starts_at_one() -> None:
    assert SnapshotStore().resume_point("empty") == 1


def test_resume_unknown_snapshot_id_raises() -> None:
    store = SnapshotStore()
    store.commit(build_snapshot(session_id="s", seq=1, trigger="manual"))
    with pytest.raises(KeyError):
        store.resume_point("s", snapshot_id="missing")
