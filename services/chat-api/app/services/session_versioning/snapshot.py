"""Session snapshot model + commit triggers (002 FR-1 / FR-2 / clarify OQ-1).

A snapshot captures a session's progress: the seq it was taken at, who triggered
it, a context summary, changed refs, and **attachment pointers** (attachments are
stored elsewhere; the snapshot only holds references — clarify OQ-1).

Snapshots are stored in their own collection (``session_snapshots``), never inlined
into the session document.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SNAPSHOT_COLLECTION = "session_snapshots"


class CommitTrigger(str, Enum):
    MANUAL = "manual"                 # explicit user "save"/commit
    IDLE_TIMEOUT = "idle_timeout"     # session idle past the threshold
    KEY_TOOL = "key_tool"             # auto-commit after a key tool call
    SHARE = "share"                   # auto-commit on share


class SnapshotError(ValueError):
    """Raised for an invalid snapshot."""


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


@dataclass
class AttachmentRef:
    """A pointer to an attachment stored elsewhere (never the bytes)."""

    name: str
    storage_ref: str
    size_bytes: int = 0


@dataclass
class SessionSnapshot:
    """One commit of a session's state."""

    session_id: str
    seq: int
    trigger: str = CommitTrigger.MANUAL.value
    actor: str = ""
    summary: str = ""
    changed_refs: list[str] = field(default_factory=list)
    attachment_refs: list[AttachmentRef] = field(default_factory=list)
    created_at: datetime.datetime = field(default_factory=_utcnow)
    snapshot_id: str = ""

    def __post_init__(self) -> None:
        if not str(self.session_id or "").strip():
            raise SnapshotError("session_id must not be empty")
        if int(self.seq) < 0:
            raise SnapshotError("seq must be >= 0")
        # Auto-generate a default snapshot id when the caller leaves it empty.
        if not str(self.snapshot_id or "").strip():
            self.snapshot_id = f"snap-{uuid.uuid4()}"

    def as_document(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "session_id": self.session_id,
            "seq": self.seq,
            "trigger": self.trigger,
            "actor": self.actor,
            "summary": self.summary,
            "changed_refs": list(self.changed_refs),
            "attachment_refs": [
                {"name": item.name, "storage_ref": item.storage_ref, "size_bytes": item.size_bytes}
                for item in self.attachment_refs
            ],
            "created_at": self.created_at,
        }


@dataclass
class CommitPolicy:
    """When commits happen automatically (clarify OQ-1, configurable)."""

    commit_on_idle: bool = True
    idle_seconds: int = 900            # 15 minutes
    commit_on_key_tool: bool = True
    commit_on_share: bool = True
    key_tools: frozenset[str] = field(default_factory=frozenset)

    def should_commit_on_idle(self, *, idle_for_seconds: float) -> bool:
        return self.commit_on_idle and idle_for_seconds >= self.idle_seconds

    def should_commit_on_tool(self, tool: str) -> bool:
        return self.commit_on_key_tool and (not self.key_tools or tool in self.key_tools)


def build_snapshot(
    *,
    session_id: str,
    seq: int,
    trigger: str,
    actor: str = "",
    summary: str = "",
    changed_refs: list[str] | None = None,
    attachments: list[AttachmentRef] | None = None,
    snapshot_id: str = "",
) -> SessionSnapshot:
    """Build a snapshot, deriving a default summary when none is supplied."""
    derived = summary or _derive_summary(changed_refs or [])
    return SessionSnapshot(
        session_id=session_id,
        seq=seq,
        trigger=trigger,
        actor=actor,
        summary=derived,
        changed_refs=list(changed_refs or []),
        attachment_refs=list(attachments or []),
        snapshot_id=snapshot_id,
    )


def _derive_summary(changed_refs: list[str]) -> str:
    if not changed_refs:
        return "会话进度快照"
    preview = "、".join(changed_refs[:3])
    suffix = "…" if len(changed_refs) > 3 else ""
    return f"变更 {len(changed_refs)} 项：{preview}{suffix}"
