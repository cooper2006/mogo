"""Session → layered memory sedimentation (017 FR-5 upgrade + 002 binding).

When a session ends (feature 002, bridged by the 009 ``SessionEnd`` hook), it can
sediment into a **tiered** 017 memory instead of a flat one:

* **L0** — one-line session summary (reuse the 002 snapshot context summary)
* **L1** — key decisions / participants / agenda
* **L2** — snapshot or transcript reference (the original ``content``)

Provenance is recorded via ``source_session_id`` / ``source_type="session"``
(017 FR-19) so the memory can be traced back to its originating session and
exposed under ``mogo://session/...`` by the 021 address space.

Integration seam
----------------
``on_session_end`` is the function the 009 ``SessionEnd`` consumer should call.
It is intentionally decoupled from the hook engine so the wire-up can land in a
follow-up change without blocking the 017 layer itself.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional, Protocol, Tuple

from app.infrastructure.observability.config import log_print
from app.memory.scope import resolve_default_scope

if TYPE_CHECKING:  # avoid import-time cycle with store / scope dataclass
    from app.memory.scope import Memory
    from app.memory.store import MemoryStore

SUMMARY_REFRESH_DAYS_DEFAULT = 30


class SessionSummarizer(Protocol):
    """Turns a session snapshot into ``(l0_summary, l1_overview)``."""

    def session_tiers(self, snapshot: dict) -> Tuple[str, str]:  # pragma: no cover
        ...


class NoopSessionSummarizer:
    """Default summarizer: lift the title/summary, leave L1 empty."""

    def session_tiers(self, snapshot: dict) -> Tuple[str, str]:
        title = str(snapshot.get("title") or snapshot.get("summary") or "")
        return (title, "")


def _snapshot_raw_content(snapshot: dict) -> str:
    """Best-effort raw content for L2 from a session snapshot."""
    for key in ("transcript", "content", "summary", "title"):
        value = snapshot.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def build_session_memory(
    *,
    session_id: str,
    content: str,
    scope: str,
    owner_id: str,
    tenant_id: str,
    workspace_id: str = "",
    l0_summary: str = "",
    l1_overview: str = "",
    summarizer: Optional[SessionSummarizer] = None,
    summary_refresh_days: int = SUMMARY_REFRESH_DAYS_DEFAULT,
) -> dict:
    """Build the persisted field set of a session-sedimented memory (FR-5/FR-19).

    Returns a kwargs dict ready for :meth:`MemoryStore.save`.
    """
    if not l0_summary and summarizer is not None:
        l0_summary, l1_overview = summarizer.session_tiers(
            {"content": content, "title": "", "summary": l0_summary or content}
        )
    return {
        "content": content,
        "scope": scope,
        "owner_id": owner_id,
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "l0_summary": l0_summary,
        "l1_overview": l1_overview,
        "tierable": True,
        "summary_generated_at": time.time(),
        "summary_refresh_days": summary_refresh_days,
        "source_session_id": session_id,
        "source_type": "session",
    }


async def on_session_end(
    *,
    session_id: str,
    snapshot: dict,
    store: "MemoryStore",
    summarizer: Optional[SessionSummarizer] = None,
    multi_user_session: bool = False,
    owner_id: str = "",
    tenant_id: str = "",
    workspace_id: str = "",
) -> Optional["Memory"]:
    """Sediment a 002 session into a 017 tiered memory on ``SessionEnd``.

    Returns the saved :class:`Memory`, or ``None`` when sedimentation is skipped
    (empty snapshot with no usable title/content). This is the seam the 009
    ``SessionEnd`` consumer invokes.

    Async because :meth:`MemoryStore.save` is async (motor write must be awaited).
    """
    content = _snapshot_raw_content(snapshot)
    if not content:
        return None
    scope = str(snapshot.get("scope") or resolve_default_scope(multi_user_session=multi_user_session))
    fields = build_session_memory(
        session_id=session_id,
        content=content,
        scope=scope,
        owner_id=owner_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        summarizer=summarizer,
    )
    return await store.save(**fields)


__all__ = [
    "NoopSessionSummarizer",
    "SessionSummarizer",
    "build_session_memory",
    "ensure_registered",
    "mark_sedimented",
    "on_session_end",
    "register_sedimentation_subscriber",
    "reset_sedimentation_ledger",
    "sediment_session_end",
]


async def sediment_session_end(
    *,
    session_id: str,
    session_doc: dict,
    store: "MemoryStore",
    owner_id: str,
    tenant_id: str,
    workspace_id: str = "",
    summarizer: Optional[SessionSummarizer] = None,
    emit_hook: bool = False,
) -> Optional["Memory"]:
    """Wire 009 ``SessionEnd`` → 017 tiered memory (FR-5/FR-20 + 002 binding).

    ``session_doc`` is a ``chat_sessions`` document; we derive the snapshot and
    call :func:`on_session_end` to sediment a layered memory.

    ``emit_hook`` is now **off by default**: this function *is* the ``SessionEnd``
    consumer, so emitting the event here would re-enter the sedimentation loop.
    It stays available for callers that legitimately want to notify other 009
    subscribers, but the 002 end-of-session path should call this directly (or
    rely on :func:`app.dsh_runtime.hooks.dispatcher.dispatch_session_end`, which
    reaches this function through the subscriber registry).
    """
    snapshot = {
        "title": str(session_doc.get("title") or ""),
        "summary": str(session_doc.get("summary") or ""),
        "content": (
            str(session_doc.get("content") or "")
            or str(session_doc.get("last_message") or "")
            or str(session_doc.get("title") or "")
        ),
    }
    multi_user = bool(
        session_doc.get("multi_user")
        or session_doc.get("co_presence")
        or session_doc.get("is_group")
    )
    result = await on_session_end(
        session_id=session_id,
        snapshot=snapshot,
        store=store,
        summarizer=summarizer,
        multi_user_session=multi_user,
        owner_id=owner_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if emit_hook and result is not None:
        # Notify other 009 subscribers (this function is *not* one of them).
        try:
            from app.dsh_runtime.hooks.dispatcher import dispatch_session_end

            await dispatch_session_end(
                session_id,
                actor=owner_id,
                payload={
                    "tenant_id": tenant_id,
                    "memory_id": result.memory_id,
                    "origin": "sediment",
                },
            )
        except Exception as exc:
            # Notification is best-effort; sedimentation already succeeded. Log it
            # anyway — a swallowed trace here is indistinguishable from "no
            # subscriber was registered", which is exactly the failure mode that
            # made the 009 seam look wired while doing nothing.
            log_print(
                f"[memory.sediment] SessionEnd notification failed "
                f"(session_id={session_id}, memory_id={result.memory_id}): {exc}",
                flush=True,
            )
    return result


# --- 009 subscriber registration ------------------------------------------
#
# Registering here (module import side effect) is what makes the 009 → 017
# seam real: ``dispatch_session_end(...)`` now reaches this sedimentation, where
# before the emitted payload had no consumer at all. The handler rehydrates the
# session snapshot from the payload, so subscribers only need to send ids.

#: Sessions already sedimented, so a repeated SessionEnd (e.g. delete after end)
#: does not create a duplicate memory.
#:
#: Accepted risk (2026-10-06 R2 遗留建议 #3): this ledger is in-process memory.
#: In a multi-replica deployment, replicas cannot see each other's claims, so a
#: SessionEnd delivered to two replicas could each create a memory.  The risk is
#: mitigated by the second line of defence — ``end_session`` itself is idempotent
#: (it checks ``ended_at`` before acting) — so the duplicate memory is a
#: cosmetic duplication, not a data-loss or corruption.  If the hook consumer
#: ever scales to multiple replicas, migrate this ledger to Redis/DB.
_SEDIMENTED: set[str] = set()


def mark_sedimented(session_id: str) -> bool:
    """Claim ``session_id`` for sedimentation. Returns False if already claimed."""
    if not session_id or session_id in _SEDIMENTED:
        return False
    _SEDIMENTED.add(session_id)
    return True


def reset_sedimentation_ledger() -> None:
    """Forget all sedimentation claims (test isolation)."""
    _SEDIMENTED.clear()


async def _on_session_end_event(payload) -> None:
    """009 ``SessionEnd`` subscriber → sediment the session (FR-5/FR-20).

    Expected payload keys: ``session_id`` (required), ``session_doc``,
    ``store``, ``owner_id``, ``tenant_id``, ``workspace_id``, ``summarizer``.
    Missing ``store`` means the emitter wanted notification only, so we skip.
    """
    data = getattr(payload, "payload", None) or {}
    session_id = str(data.get("session_id") or "").strip()
    store = data.get("store")
    if not session_id or store is None:
        return
    if not mark_sedimented(session_id):
        return
    await sediment_session_end(
        session_id=session_id,
        session_doc=dict(data.get("session_doc") or {}),
        store=store,
        owner_id=str(data.get("owner_id") or getattr(payload, "actor", "") or ""),
        tenant_id=str(data.get("tenant_id") or ""),
        workspace_id=str(data.get("workspace_id") or ""),
        summarizer=data.get("summarizer"),
    )


def register_sedimentation_subscriber() -> bool:
    """Subscribe the 017 sedimentation to 009 ``SessionEnd``.

    Idempotent — returns False when already registered. Call this at app
    startup (or rely on :func:`ensure_registered`).
    """
    from app.dsh_runtime.hooks.dispatcher import subscribe, subscriber_count
    from app.dsh_runtime.hooks.registry import SESSION_END

    if subscriber_count(SESSION_END) > 0:
        return False
    subscribe(SESSION_END, _on_session_end_event)
    return True


def ensure_registered() -> None:
    """Idempotent registration used by the 002 end-of-session path.

    Imported lazily so ``app.memory.sediment`` stays usable without the 009
    runtime present (e.g. isolated unit tests).
    """
    try:
        register_sedimentation_subscriber()
    except Exception as exc:
        # 009 runtime absent — sedimentation stays callable directly. Logged so a
        # missing dispatch loop is diagnosable rather than silent.
        log_print(
            f"[memory.sediment] 009 subscriber registration skipped "
            f"(runtime unavailable): {exc}",
            flush=True,
        )
