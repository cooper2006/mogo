# Session Versioning Quickstart (002)

## What this module does

`app/services/session_versioning/` implements feature **002-session-versioning**:
a hard-linear session timeline plus commit/snapshot, resume, share, and
co-presence for the chat runtime.

| Concern | Module | Key API |
| --- | --- | --- |
| Commit / snapshot model | `snapshot.py` | `build_snapshot`, `SessionSnapshot`, `CommitTrigger`, `CommitPolicy` |
| Linear timeline + optimistic lock | `timeline.py` | `Timeline`, `check_and_advance`, `merge_linear`, `ConflictResult` |
| Share / handover + TTL + revocation | `share.py` | `build_share`, `ShareStore`, `ROLE_EDITOR`, `ROLE_VIEWER` |
| Co-presence (Mongo short-poll) | `co_presence.py` | `CoPresence.heartbeat`, `CoPresence.online`, `CoPresence.merge_messages` |
| Session event audit (001 sink) | `audit.py` | `record_session_event`, `SESSION_AUDIT_FIELDS` |

## 1. Create a commit snapshot (US1)

```python
from app.services.session_versioning.snapshot import build_snapshot, AttachmentRef

snap = build_snapshot(
    session_id="sess-1",
    seq=42,
    trigger="manual",
    actor="alice",
    changed_refs=["msg-17", "msg-18"],
    attachments=[AttachmentRef(name="a.png", storage_ref="oss://a.png", size_bytes=1234)],
)
# snap.summary -> "变更 2 项：msg-17、msg-18"
```

## 2. Reserve / advance seq under optimistic lock (US2)

```python
from app.services.session_versioning.timeline import check_and_advance, ConflictResult

result: ConflictResult = check_and_advance(current_seq=42, expected_seq=42)
assert result.ok is True            # 42 == 42 -> write proceeds
# 42 != 43 -> re-read + retry; after max_retries fail closed (US2 acceptance 2)
```

## 3. Linear resume (US2 acceptance 1)

```python
from app.services.session_versioning.timeline import Timeline

tl = Timeline(seqs=[1, 2, 3])
tl.append(4)             # 4 > max(3) -> ok
# tl.append(3)           # would fork -> LinearTimelineError
start = tl.resume_from(snapshot_seq=3)   # continue from seq 4, never reset to 1
```

## 4. Share / handover with TTL + revocation (US4)

```python
from app.services.session_versioning.share import build_share, ShareStore, ROLE_EDITOR

share = build_share(
    session_id="sess-1",
    snapshot_id=snap.snapshot_id,
    actor="alice",
    receiver="bob",
    visibility="user",
    receiver_role=ROLE_EDITOR,   # bob can edit after redemption
    ttl_seconds=300,
)
store = ShareStore(db=None)
# An expired / revoked / already-redeemed share renders an empty view (US4 acceptance 2):
view = share.to_view(snapshot=snap)
assert view["active"] is True and view["handover"] is True
```

## 5. Co-presence (US5) — MongoDB short-poll, no Redis

```python
from app.services.session_versioning.co_presence import CoPresence

presence = CoPresence(db=mongo_db, heartbeat_ttl=30.0)
presence.heartbeat("sess-1", "alice")
presence.heartbeat("sess-1", "bob")
# Poll every ~5s; only heartbeat-fresh editors count as online:
online = presence.online("sess-1")
# Offline editors' contributions were already merged into the linear timeline (FR-5)
merged = presence.merge_messages("sess-1", [1, 2, 3])
```

## 6. Session event audit → 001 sink (FR-9)

```python
from app.services.session_versioning.audit import record_session_event, validate_audit_document

def my_audit_sink(**kwargs):
    # Persist to the 001 gate_events collection.
    return dict(kwargs)

doc = record_session_event(
    my_audit_sink,
    "sess-1",
    event_type="commit",
    actor="alice",
    target_ref=snap.snapshot_id,
)
validate_audit_document(doc)   # actor / ts / session_id / event_type / target_ref
```

## 7. Empty state (FR-7)

No snapshot yet -> empty log; no active share -> empty view. Both are honest
empty states (no fabricated data).
