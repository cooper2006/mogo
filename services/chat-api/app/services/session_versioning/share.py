"""Share (handover / view) model + store (002 US4 / FR-8).

A *share* grants read (or edit-on-receive) access to a session's **latest
linear snapshot** to another user or role. The handover is a permission
transfer: the previous holder becomes read-only, the receiver can edit
(``receiver_role``) — a one-way handover, not a fork (FR-3 / FR-8).

- ``token``: a short-lived, single-use share credential (001 gatekeeper
  approval linkage; TTL ~ 5 min, one redemption).
- ``visibility``: who may redeem it — ``user`` / ``org`` / ``role`` (006 RBAC
  linkage: the receiver's effective permissions decide edit vs read).
- Expiry / revocation: a share that is not redeemed before ``expires_at`` (or
  that is revoked) degrades to an **empty state** (US4 acceptance 2).

Shares live in their own collection (``session_shares``); a share *view* is
assembled from the snapshot at redemption time — it never re-reads a forked
branch.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from .snapshot import SessionSnapshot

SHARE_COLLECTION = "session_shares"
# Default share token TTL (one use within this window, else empty state).
SHARE_TTL_SECONDS = 300

# Handover roles (FR-8 permission transfer semantics).
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"


class ShareError(ValueError):
    """Raised for an invalid share or redemption."""


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


@dataclass
class ShareRecord:
    """A single handover / view grant for a session snapshot."""

    share_id: str
    session_id: str
    snapshot_id: str
    actor: str
    visibility: str = "user"
    receiver: str = ""
    receiver_role: str = ROLE_VIEWER
    token: str = ""
    created_at: datetime.datetime = field(default_factory=_utcnow)
    expires_at: datetime.datetime = field(default_factory=lambda: _utcnow())
    redeemed: bool = False
    revoked: bool = False

    def __post_init__(self) -> None:
        if not self.share_id:
            self.share_id = f"share-{uuid.uuid4()}"
        if not self.token:
            self.token = uuid.uuid4().hex
        if self.expires_at <= self.created_at:
            raise ShareError("expires_at must be after created_at")

    # --- redemption ----------------------------------------------------------

    def is_active(self, now: Optional[datetime.datetime] = None) -> bool:
        """A share is redeemable when not redeemed, not revoked, and unexpired."""
        if self.redeemed or self.revoked:
            return False
        return (now or _utcnow()) < self.expires_at

    def mark_redeemed(self, now: Optional[datetime.datetime] = None) -> None:
        if not self.is_active(now):
            raise ShareError(
                f"share {self.share_id} cannot be redeemed (revoked, already redeemed, or expired -> empty state)"
            )
        self.redeemed = True

    def revoke(self) -> None:
        self.revoked = True

    # --- view (US4) ----------------------------------------------------------

    def to_view(self, snapshot: Optional[SessionSnapshot] = None) -> dict[str, Any]:
        """Assemble the share view.

        An **expired / revoked / already-redeemed** share renders an empty view
        (US4 acceptance 2) — honest ``active=False`` rather than a fabricated
        success. When a snapshot is supplied and the share is active, the view
        carries its refs; when ``receiver_role == editor`` the view notes the
        handover granted edit (FR-8).
        """
        active = self.is_active()
        view: dict[str, Any] = {
            "share_id": self.share_id,
            "session_id": self.session_id,
            "snapshot_id": self.snapshot_id,
            "visibility": self.visibility,
            "receiver_role": self.receiver_role,
            "handover": active and self.receiver_role == ROLE_EDITOR,
            "active": active,
            "revoked": self.revoked,
            "redeemed": self.redeemed,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
        if active and snapshot is not None:
            view["changed_refs"] = list(snapshot.changed_refs)
            view["summary"] = snapshot.summary
        else:
            view["changed_refs"] = []
            view["summary"] = ""
        return view


def build_share(
    *,
    session_id: str,
    snapshot_id: str,
    actor: str,
    receiver: str = "",
    visibility: str = "user",
    receiver_role: str = ROLE_VIEWER,
    ttl_seconds: int = SHARE_TTL_SECONDS,
    share_id: str = "",
    token: str = "",
    expires_at: Optional[datetime.datetime] = None,
) -> ShareRecord:
    """Create a share grant for a session's current snapshot."""
    created = _utcnow()
    share = ShareRecord(
        share_id=share_id,
        session_id=session_id,
        snapshot_id=snapshot_id,
        actor=actor,
        visibility=visibility,
        receiver=receiver,
        receiver_role=receiver_role,
        token=token,
        expires_at=expires_at or (created + datetime.timedelta(seconds=ttl_seconds)),
    )
    return share


class ShareStore:
    """Mongo-backed (or in-memory) share store with TTL + single-use semantics."""

    def __init__(self, db: Optional[Any] = None) -> None:
        self._db = db
        self._shares: dict[str, ShareRecord] = {}

    async def create_share(
        self,
        *,
        session_id: str,
        actor: str,
        snapshot_id: str = "",
        receiver: str = "",
        visibility: str = "user",
        receiver_role: str = ROLE_VIEWER,
        ttl_seconds: int = SHARE_TTL_SECONDS,
    ) -> ShareRecord:
        share = build_share(
            session_id=session_id,
            snapshot_id=snapshot_id,
            actor=actor,
            receiver=receiver,
            visibility=visibility,
            receiver_role=receiver_role,
            ttl_seconds=ttl_seconds,
        )
        if self._db is not None:
            await self._db[SHARE_COLLECTION].insert_one(self.to_document(share))
        else:
            self._shares[share.share_id] = share
        return share

    async def redeem(self, share_id: str, *, now: Optional[datetime.datetime] = None) -> ShareRecord:
        """Redeem a share token (single-use). Raises ``ShareError`` -> empty state."""
        share = await self._load(share_id)
        share.mark_redeemed(now)
        if self._db is not None:
            await self._db[SHARE_COLLECTION].update_one({"share_id": share_id}, {"$set": {"redeemed": True}})
        return share

    async def revoke_share(self, share_id: str) -> ShareRecord:
        share = await self._load(share_id)
        share.revoke()
        if self._db is not None:
            await self._db[SHARE_COLLECTION].update_one({"share_id": share_id}, {"$set": {"revoked": True}})
        return share

    async def _load(self, share_id: str) -> ShareRecord:
        if self._db is not None:
            row = await self._db[SHARE_COLLECTION].find_one({"share_id": share_id})
            if row is None:
                raise ShareError(f"unknown share {share_id}")
            return ShareStore.from_document(row)
        share = self._shares.get(share_id)
        if share is None:
            raise ShareError(f"unknown share {share_id}")
        return share

    @staticmethod
    def from_document(document: dict[str, Any]) -> "ShareRecord":
        created = document.get("created_at") or _utcnow()
        expires = document.get("expires_at") or (created + datetime.timedelta(seconds=SHARE_TTL_SECONDS))
        share = ShareRecord(
            share_id=str(document.get("share_id") or ""),
            session_id=str(document.get("session_id") or ""),
            snapshot_id=str(document.get("snapshot_id") or ""),
            actor=str(document.get("actor") or ""),
            visibility=str(document.get("visibility") or "user"),
            receiver=str(document.get("receiver") or ""),
            receiver_role=str(document.get("receiver_role") or ROLE_VIEWER),
            token=str(document.get("token") or ""),
            created_at=created,
            expires_at=expires,
        )
        share.redeemed = bool(document.get("redeemed"))
        share.revoked = bool(document.get("revoked"))
        return share

    def to_document(self, share: ShareRecord) -> dict[str, Any]:
        return {
            "share_id": share.share_id,
            "session_id": share.session_id,
            "snapshot_id": share.snapshot_id,
            "actor": share.actor,
            "visibility": share.visibility,
            "receiver": share.receiver,
            "receiver_role": share.receiver_role,
            "token": share.token,
            "created_at": share.created_at,
            "expires_at": share.expires_at,
            "redeemed": share.redeemed,
            "revoked": share.revoked,
        }
