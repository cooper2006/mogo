"""Session versioning HTTP endpoints (002 US1/US4/US5 — production wiring).

Wires the `session_versioning` library (snapshots / share / co-presence) to
the HTTP layer so commit / log / share / co-presence are reachable from the
UI. Snapshots and shares persist in their own Mongo collections
(``session_snapshots`` / ``session_shares``); co-presence uses the
Mongo-backed heartbeat + linear message merge (no Redis).
"""

from __future__ import annotations
from app.infrastructure.observability.config import log_print

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.endpoints.auth import _resolve_session_user
from app.core.db import get_db
from app.core.tenant import resolve_main_id
from app.services.session_versioning.co_presence import CoPresence
from app.services.session_versioning.share import SHARE_TTL_SECONDS, ShareError, ShareStore
from app.services.skill_sharing.member_directory import (
    SkillShareMemberDirectory,
    member_id_candidates,
)
from app.services.session_versioning.snapshot import (
    SNAPSHOT_COLLECTION,
    AttachmentRef,
    CommitTrigger,
    build_snapshot,
    redact_text,
    secret_ref_document,
    SECRET_REF_COLLECTION,
)
from app.services.session_versioning.audit import record_session_event
from app.services.session_persistence_service import _next_seq

router = APIRouter()


# ---------------------------------------------------------------------------
# payload models
# ---------------------------------------------------------------------------


class CommitIn(BaseModel):
    seq: int = Field(..., description="Session message seq at commit time")
    trigger: str = Field(CommitTrigger.MANUAL.value, description="manual / idle_timeout / key_tool / share")
    summary: str = Field("", description="Optional snapshot summary; derived when empty")
    content: str = Field("", description="Conversation text to redact (FR-7); secrets become reversible placeholders")
    changed_refs: list[str] = Field(default_factory=list, description="Refs changed since last commit")
    attachments: list[dict[str, Any]] = Field(default_factory=list, description="Attachment pointers (name/storage_ref/size_bytes)")


class ShareIn(BaseModel):
    snapshot_id: str = Field("", description="Snapshot to share; empty = latest")
    receiver: str = Field("", description="Receiver user id (empty = self / org-visible)")
    visibility: str = Field("user", description="user / org / role")
    receiver_role: str = Field("viewer", description="viewer / editor (edit grants handover)")
    ttl_seconds: int = Field(SHARE_TTL_SECONDS, description="Share token TTL")


class RedeemIn(BaseModel):
    token: str = Field(..., description="Share token to redeem")


class CoPresenceIn(BaseModel):
    user_id: str = Field(..., description="User establishing presence")
    message_seqs: list[int] = Field(default_factory=list, description="Locally known message seqs to merge")


def _snapshot_out(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "snapshotId": document.get("snapshot_id"),
        "sessionId": document.get("session_id"),
        "seq": document.get("seq"),
        "trigger": document.get("trigger"),
        "actor": document.get("actor"),
        "summary": document.get("summary"),
        "content": document.get("content"),
        "secretRefs": list(document.get("secret_refs") or []),
        "changedRefs": list(document.get("changed_refs") or []),
        "attachmentRefs": [
            {
                "name": item.get("name"),
                "storageRef": item.get("storage_ref"),
                "sizeBytes": item.get("size_bytes"),
            }
            for item in (document.get("attachment_refs") or [])
        ],
        "createdAt": document.get("created_at").isoformat() if document.get("created_at") else None,
    }


def _preview_out(document: dict[str, Any]) -> dict[str, Any]:
    """Generate a snapshot preview from a DB document (FR-2).

    002 audit (2026-10-03): SnapshotStore.preview() existed but had zero callers
    in the production endpoint — list_session_versions hardcoded "preview": None.
    This wires the preview back to the DB-backed path, mirroring
    SnapshotStore.preview()'s shape.
    """
    return {
        "snapshotId": document.get("snapshot_id"),
        "seq": document.get("seq"),
        "trigger": document.get("trigger"),
        "actor": document.get("actor"),
        "summary": document.get("summary"),
        "changedRefs": list(document.get("changed_refs") or []),
        "attachmentCount": len(document.get("attachment_refs") or []),
        "createdAt": document.get("created_at").isoformat() if document.get("created_at") else None,
    }


def _collect_originals(*texts: str, ids: list[str]) -> dict[str, str]:
    """Map each placeholder id back to the original secret value it replaced.

    Re-derives the redaction deterministically (ids are sha256 prefixes of the
    value), so the original can be recovered without a second store read.
    """
    from app.services.session_versioning.placeholder import PLACEHOLDER_CLOSE, PLACEHOLDER_OPEN
    from app.services.session_versioning.secrets import detect_secrets

    wanted = {tid for tid in ids if tid}
    found: dict[str, str] = {}
    for text in texts:
        for match in detect_secrets(text or ""):
            if match.value and _token_id_for(match.value) in wanted:
                found[_token_id_for(match.value)] = match.value
    return found


def _token_id_for(secret: str) -> str:
    import hashlib

    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


async def _record_session_audit(
    *, main_id: str, user_id: str, session_id: str, event_type: str, target_ref: str = ""
) -> None:
    """Record a 002 session event on the 001 audit stream (FR-11)."""
    from app.governance.audit import record_position_policy_event

    await record_position_policy_event(
        tenant_id=main_id,
        user_id=user_id,
        action=f"session.{event_type}",
        target=target_ref,
        details={"session_id": session_id, "event_type": event_type, "target_ref": target_ref, "main_id": main_id},
    )


async def _authorize(authorization: str | None) -> tuple[str, str]:
    resolved = await _resolve_session_user(authorization if isinstance(authorization, str) else None)
    main_id = resolve_main_id(resolved["main_id"])
    user_id = str(resolved["user"].get("_id") or "")
    return main_id, user_id


# ---------------------------------------------------------------------------
# US1 commit / log / resume
# ---------------------------------------------------------------------------


@router.post("/sessions/{session_id}/commit")
async def commit_session(
    session_id: str,
    payload: CommitIn,
    authorization: str | None = Header(default=None),
):
    main_id, user_id = await _authorize(authorization)
    db = get_db()
    attachment_refs = [
        AttachmentRef(
            name=str(item.get("name") or ""),
            storage_ref=str(item.get("storage_ref") or item.get("storageRef") or ""),
            size_bytes=int(item.get("size_bytes") or item.get("sizeBytes") or 0),
        )
        for item in payload.attachments
    ]
    # 002 residual fix: server-side fallback redaction. The commit metadata is
    # client-reported; when the caller did not supply conversation content,
    # read the real session messages from chat_messages so secrets in the
    # server-side history are still redacted before they enter the snapshot
    # (never stored in plaintext, FR-7).
    content_source = payload.content
    if not content_source:
        try:
            from app.core.tenant import add_main_scope, resolve_main_id

            rows = await db.chat_messages.find(
                add_main_scope({"session_id": session_id}, resolve_main_id(main_id))
            ).sort("seq", 1).to_list(length=200)
            content_source = "\n".join(
                f"{row.get('role') or ''}: {row.get('content') or ''}"
                for row in rows
                if row.get("content")
            )
        except Exception as exc:  # noqa: BLE001 - degradation must not block the commit
            log_print(f"[api.endpoints.dsh_session_versioning.commit_session] suppressed {type(exc).__name__}: {exc}", flush=True)
            content_source = ""
    # FR-7: never store suspected secrets in plaintext. Redact the summary and
    # the conversation content (caller-supplied or server-side fallback); keep
    # the originals only in session_secret_refs (owner/admin dereference, FR-8,
    # audited).
    summary_redacted, summary_ids = redact_text(payload.summary)
    content_redacted, content_ids = redact_text(content_source)
    secret_ids = list(dict.fromkeys(summary_ids + content_ids))

    # 002: validate client-reported seq matches actual next sequence
    expected_seq = await _next_seq(
        db, session_id, user_id, main_id
    )
    if payload.seq != expected_seq:
        raise HTTPException(
            status_code=400,
            detail=f"commit seq {payload.seq} does not match expected seq {expected_seq}",
        )

    snapshot = build_snapshot(
        session_id=session_id,
        seq=payload.seq,
        trigger=payload.trigger,
        actor=user_id,
        summary=summary_redacted,
        changed_refs=payload.changed_refs,
        attachments=attachment_refs,
    )
    document = snapshot.as_document()
    document["main_id"] = main_id
    document["content"] = content_redacted
    document["secret_refs"] = secret_ids
    # Persist the original secret values, scoped to the session + main (FR-8).
    if secret_ids:
        originals = _collect_originals(payload.summary, content_source, ids=secret_ids)
        refs = [
            secret_ref_document(
                session_id=session_id, main_id=main_id, token_id=tid, original=originals.get(tid, ""), actor=user_id
            )
            for tid in secret_ids
        ]
        await db[SECRET_REF_COLLECTION].insert_many(refs, ordered=False)
    result = await db[SNAPSHOT_COLLECTION].insert_one(document)
    document["_id"] = getattr(result, "inserted_id", result)
    # FR-11: commit is a session-level audited event on the 001 audit stream.
    await _record_session_audit(
        main_id=main_id, user_id=user_id, session_id=session_id,
        event_type="commit", target_ref=str(document.get("snapshot_id") or ""),
    )
    return _snapshot_out(document)


@router.get("/sessions/{session_id}/versions")
async def list_session_versions(
    session_id: str,
    authorization: str | None = Header(default=None),
):
    main_id, _ = await _authorize(authorization)
    db = get_db()
    cursor = db[SNAPSHOT_COLLECTION].find(
        {"session_id": session_id, "main_id": main_id}
    ).sort("created_at", 1)
    documents = await cursor.to_list(length=500)
    return [
        {
            **_snapshot_out(document),
            "preview": _preview_out(document),
        }
        for document in documents
    ]


@router.get("/sessions/{session_id}/versions/{snapshot_id}")
async def get_session_version(
    session_id: str,
    snapshot_id: str,
    authorization: str | None = Header(default=None),
):
    main_id, _ = await _authorize(authorization)
    db = get_db()
    document = await db[SNAPSHOT_COLLECTION].find_one(
        {"snapshot_id": snapshot_id, "session_id": session_id, "main_id": main_id}
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {**_snapshot_out(document), "preview": _preview_out(document)}


@router.post("/sessions/{session_id}/resume")
async def resume_session(
    session_id: str,
    snapshot_id: str = Query("", description="Resume after this snapshot; empty = latest"),
    authorization: str | None = Header(default=None),
):
    main_id, user_id = await _authorize(authorization)
    db = get_db()
    target = None
    if snapshot_id:
        target = await db[SNAPSHOT_COLLECTION].find_one(
            {"snapshot_id": snapshot_id, "session_id": session_id, "main_id": main_id}
        )
        if target is None:
            raise HTTPException(status_code=404, detail="Snapshot not found")
    else:
        cursor = db[SNAPSHOT_COLLECTION].find(
            {"session_id": session_id, "main_id": main_id}
        ).sort("created_at", -1)
        target = await cursor.to_list(length=1)
        target = target[0] if target else None
    resume_after_seq = int(target.get("seq") or 0) + 1 if target else 1
    # FR-11: resume is a session-level audited event on the 001 audit stream.
    await _record_session_audit(
        main_id=main_id, user_id=user_id, session_id=session_id,
        event_type="resume", target_ref=snapshot_id or "",
    )
    # 002 audit fix: return the target snapshot's metadata so the consumer
    # knows what they are resuming from (not just a bare seq number).
    resumed_from = _snapshot_out(target) if target else None
    return {
        "sessionId": session_id,
        "resumeAfterSeq": resume_after_seq,
        "resumedFromSnapshot": snapshot_id or None,
        "resumedFrom": resumed_from,
    }


# ---------------------------------------------------------------------------
# US4 share / redeem / revoke
# ---------------------------------------------------------------------------


@router.post("/sessions/{session_id}/share")
async def share_session(
    session_id: str,
    payload: ShareIn,
    authorization: str | None = Header(default=None),
):
    main_id, user_id = await _authorize(authorization)
    db = get_db()
    store = ShareStore(db)
    share = await store.create_share(
        session_id=session_id,
        actor=user_id,
        snapshot_id=payload.snapshot_id,
        receiver=payload.receiver,
        visibility=payload.visibility,
        receiver_role=payload.receiver_role,
        ttl_seconds=payload.ttl_seconds,
    )
    # FR-11: share grant is a session-level audited event on the 001 audit stream.
    await _record_session_audit(
        main_id=main_id, user_id=user_id, session_id=session_id,
        event_type="share", target_ref=share.share_id,
    )
    return {**share.to_view(), "main_id": main_id}


@router.post("/sessions/{session_id}/share/redeem")
async def redeem_share(
    session_id: str,
    payload: RedeemIn,
    authorization: str | None = Header(default=None),
):
    main_id, _ = await _authorize(authorization)
    db = get_db()
    store = ShareStore(db)
    try:
        share = await store.redeem(payload.token)
    except ShareError as error:
        # Expiry / revocation / single-use → honest empty state (US4 acceptance 2).
        return {"active": False, "reason": "share_expired_or_invalid"}
    return share.to_view()


@router.post("/sessions/{session_id}/share/{share_id}/revoke")
async def revoke_share(
    session_id: str,
    share_id: str,
    authorization: str | None = Header(default=None),
):
    # ``_authorize`` returns ``(main_id, user_id)``; the audit call below needs
    # both. Discarding user_id made this endpoint raise NameError on every call.
    main_id, user_id = await _authorize(authorization)
    db = get_db()
    store = ShareStore(db)
    try:
        share = await store.revoke_share(share_id)
    except ShareError:
        raise HTTPException(status_code=404, detail="Share not found")
    # FR-11: revocation is a session-level audited event on the 001 audit stream.
    await _record_session_audit(
        main_id=main_id, user_id=user_id, session_id=session_id,
        event_type="share", target_ref=f"{share_id}:revoked",
    )
    return share.to_view()


# ---------------------------------------------------------------------------
# US4 / FR-8: dereference a reversible secret placeholder
# ---------------------------------------------------------------------------


@router.get("/sessions/{session_id}/secrets/{token_id}")
async def dereference_secret(
    session_id: str,
    token_id: str,
    authorization: str | None = Header(default=None),
):
    """FR-8: restore a secret from a reversible placeholder.

    Only the session owner or a full-access administrator may dereference; each
    dereference is recorded on the 001 audit stream (FR-11). The original value
    lives in ``session_secret_refs`` (never inlined into the snapshot).
    """
    main_id, user_id = await _authorize(authorization)
    db = get_db()
    row = await db[SECRET_REF_COLLECTION].find_one(
        {"token_id": token_id, "session_id": session_id, "main_id": main_id}
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Secret placeholder not found")

    # FR-8 role check: owner (creator of the ref) or full-access admin.
    from app.core.tenant import resolve_main_id

    owner = str(row.get("created_by") or "")
    is_owner = bool(owner) and owner == user_id
    is_full_access = await _user_has_full_access(db, main_id, user_id)
    if not (is_owner or is_full_access):
        # Denied dereference is itself audited (FR-8 / FR-11).
        await _record_session_audit(
            main_id=main_id, user_id=user_id, session_id=session_id,
            event_type="dereference", target_ref=f"{token_id}:denied",
        )
        raise HTTPException(status_code=403, detail="Only the session owner or a full-access admin may dereference")

    await _record_session_audit(
        main_id=main_id, user_id=user_id, session_id=session_id,
        event_type="dereference", target_ref=token_id,
    )
    return {"token_id": token_id, "session_id": session_id, "value": row.get("original")}


async def _user_has_full_access(db, main_id: str, user_id: str) -> bool:
    """Whether the user holds the tenant's full-access preset role (006)."""
    if not main_id or not user_id:
        return False
    from app.core.tenant import add_main_scope

    cursor = db["end_user_position_roles"].find(
        add_main_scope({"user_id": user_id, "role_id": f"system:{main_id}:full_access_admin"}, main_id)
    )
    row = await cursor.to_list(length=1)
    return bool(row)


# ---------------------------------------------------------------------------
# US5 co-presence
# ---------------------------------------------------------------------------


@router.post("/sessions/{session_id}/co-presence")
async def upsert_co_presence(
    session_id: str,
    payload: CoPresenceIn,
    authorization: str | None = Header(default=None),
):
    main_id, user_id = await _authorize(authorization)
    db = get_db()
    presence = CoPresence(db)
    await presence.heartbeat(session_id=session_id, user_id=user_id)
    merged = await presence.merge_messages(session_id, payload.message_seqs)
    online = sorted(await presence.online(session_id))
    online_members = await _resolve_online_members(db, main_id, online)
    return {
        "sessionId": session_id,
        "userId": user_id,
        "onlineUsers": online,
        "onlineMembers": online_members,
        "mergedSeqs": merged,
    }


@router.get("/sessions/{session_id}/co-presence")
async def get_co_presence(
    session_id: str,
    authorization: str | None = Header(default=None),
):
    main_id, _ = await _authorize(authorization)
    db = get_db()
    presence = CoPresence(db)
    online = sorted(await presence.online(session_id))
    online_members = await _resolve_online_members(db, main_id, online)
    return {
        "sessionId": session_id,
        "onlineUsers": online,
        "onlineMembers": online_members,
    }


async def _resolve_online_members(
    db: Any,
    main_id: str,
    online_user_ids: list[str],
) -> list[dict[str, str]]:
    """Resolve online user IDs to display-friendly member views.

    Falls back to ``{"userId": <id>, "displayName": "", ...}`` (which the
    frontend renders as the raw id) when the end-user row cannot be found,
    so the API stays decoupled from the directory implementation.
    """
    if not online_user_ids:
        return []
    from app.core.tenant import add_main_scope

    cursor = db["end_users"].find(
        add_main_scope(
            {"_id": {"$in": member_id_candidates(online_user_ids)},
             "status": "active"},
            main_id,
        ),
        {"name": 1, "login_name": 1, "email": 1},
    )
    rows = await cursor.to_list(length=len(online_user_ids) + 1)
    return SkillShareMemberDirectory.member_view_batch(rows, online_user_ids)
