"""Session tenant adapter (021 / 002).

Resolves a ``mogo://session/<tenant>/<sessionId>/[L0|L1|L2]`` address into tiered
content by delegating to the **existing** session stores:

* L0 — session title / summary (one line)
* L1 — participants + message count + active document (structural)
* L2 — the recent transcript (chat_messages), on demand

Visibility is delegated to 002 (tenant match here; the backend further restricts
personal sessions to their owner and co-presence sessions to participants).
"""

from __future__ import annotations

from typing import Optional

from app.context_space.adapters.base import ResolvedTier, TierAdapter
from app.context_space.address import SessionAddress
from app.context_space.visibility import (
    ContextNotFoundError,
    ContextVisibilityError,
    ViewerContext,
    check_visibility,
)
from app.core.db import get_db
from app.core.tenant import add_main_scope, resolve_main_id


class SessionTierAdapter(TierAdapter):
    """Resolves session addresses (021 / 002)."""

    root = "session"

    async def resolve(
        self,
        *,
        uri: str,
        tier: Optional[str],
        tenant_id: str,
        viewer: ViewerContext,
    ) -> ResolvedTier:
        addr = _parse(uri)
        if tier:
            addr = SessionAddress(addr.tenant_id, addr.session_id, tier)
        if not check_visibility(addr=addr, ctx=viewer):
            raise ContextVisibilityError(f"viewer may not resolve {uri}")

        content, meta = await _load(addr, tenant_id)
        if content is None:
            raise ContextNotFoundError(f"session not found: {uri}")

        return ResolvedTier(
            uri=addr.uri(),
            tier_used=addr.tier,
            content=content,
            meta=meta or {},
        )


def _parse(uri: str) -> SessionAddress:
    from app.context_space.address import parse_context_uri

    addr = parse_context_uri(uri)
    if not isinstance(addr, SessionAddress):
        raise ContextNotFoundError(f"not a session uri: {uri}")
    return addr


async def _load(addr: SessionAddress, tenant_id: str) -> tuple[Optional[str], dict]:
    db = get_db()
    if db is None:
        return None, {}
    from bson import ObjectId

    try:
        oid = ObjectId(addr.session_id)
    except Exception:
        return None, {}
    main_id = resolve_main_id(tenant_id)
    doc = await db["chat_sessions"].find_one(add_main_scope({"_id": oid}, main_id))
    if doc is None:
        return None, {}

    title = str(doc.get("title") or "")
    summary = str(doc.get("summary") or "")
    message_count = int(doc.get("message_count") or 0)
    active_document = str(doc.get("active_document") or "")
    is_group = bool(doc.get("multi_user") or doc.get("co_presence") or doc.get("is_group"))

    l0 = (title + (" — " + summary if summary else "")).strip() or addr.session_id
    l1 = (
        f"participants={'group' if is_group else 'single'} "
        f"messages={message_count} active_document={active_document}"
    )

    transcript = ""
    if addr.tier == "L2":
        messages = (
            await db["chat_messages"]
            .find(add_main_scope({"session_id": oid}, main_id))
            .sort("created_at", 1)
            .to_list(length=50)
        )
        parts = []
        for m in messages:
            role = str(m.get("role") or m.get("sender") or "")
            text = str(m.get("content") or m.get("text") or "")
            if text:
                parts.append(f"{role}: {text}")
        transcript = "\n".join(parts)

    l2 = transcript or l1
    content = {"L0": l0, "L1": l1, "L2": l2}.get(addr.tier, l2)
    return content, {
        "subtype": "session",
        "session_id": addr.session_id,
        "title": title,
        "message_count": message_count,
        "is_group": is_group,
        "active_document": active_document,
    }


__all__ = ["SessionTierAdapter"]
