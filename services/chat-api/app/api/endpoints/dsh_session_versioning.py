"""Session versioning HTTP endpoints (002 US1/US4/US5 — production wiring).

Wires the `session_versioning` library (snapshots / share / co-presence) to
the HTTP layer so commit / log / share / co-presence are reachable from the
UI. Snapshots and shares persist in their own Mongo collections
(``session_snapshots`` / ``session_shares``); co-presence uses the
Mongo-backed heartbeat + linear message merge (no Redis).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.endpoints.auth import _resolve_session_user
from app.core.db import get_db
from app.core.tenant import resolve_main_id
from app.services.session_versioning.co_presence import CoPresence
from app.services.session_versioning.share import SHARE_TTL_SECONDS, ShareError, ShareStore
from app.services.session_versioning.snapshot import (
    SNAPSHOT_COLLECTION,
    AttachmentRef,
    CommitTrigger,
    build_snapshot,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# payload models
# ---------------------------------------------------------------------------


class CommitIn(BaseModel):
    seq: int = Field(..., description="Session message seq at commit time")
    trigger: str = Field(CommitTrigger.MANUAL.value, description="manual / idle_timeout / key_tool / share")
    summary: str = Field("", description="Optional snapshot summary; derived when empty")
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
    snapshot = build_snapshot(
        session_id=session_id,
        seq=payload.seq,
        trigger=payload.trigger,
        actor=user_id,
        summary=payload.summary,
        changed_refs=payload.changed_refs,
        attachments=attachment_refs,
    )
    document = snapshot.as_document()
    document["main_id"] = main_id
    result = await db[SNAPSHOT_COLLECTION].insert_one(document)
    document["_id"] = getattr(result, "inserted_id", result)
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
            "preview": None,
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
    return _snapshot_out(document)


@router.post("/sessions/{session_id}/resume")
async def resume_session(
    session_id: str,
    snapshot_id: str = Query("", description="Resume after this snapshot; empty = latest"),
    authorization: str | None = Header(default=None),
):
    main_id, _ = await _authorize(authorization)
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
    return {"sessionId": session_id, "resumeAfterSeq": resume_after_seq, "resumedFromSnapshot": snapshot_id or None}


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
    main_id, _ = await _authorize(authorization)
    db = get_db()
    store = ShareStore(db)
    try:
        share = await store.revoke_share(share_id)
    except ShareError:
        raise HTTPException(status_code=404, detail="Share not found")
    return share.to_view()


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
    return {
        "sessionId": session_id,
        "userId": user_id,
        "onlineUsers": online,
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
    return {"sessionId": session_id, "onlineUsers": online}
