"""IM session <-> MOGO session bindings (013 FR-2 / FR-7 / FR-9 / FR-10 / FR-14).

* mapping granularity is 1:1 — one IM conversation maps to one MOGO session;
* the binding carries the channel identity so 002's commit/share apply to IM
  sessions too (FR-7);
* **only one IM channel may bind a MOGO session** — the first binder wins (FR-14);
* a per-tenant channel switch turns existing IM sessions read-only (FR-9);
* ``PersistedSessionBindingRegistry`` mirrors the in-memory registry on the
  ``im_session_bindings`` / ``im_channels`` collections (013 残项 FR-10).
"""

from __future__ import annotations
from app.infrastructure.observability.config import log_print

from dataclasses import dataclass, field
from typing import Optional


class BindingError(ValueError):
    """Raised for a binding conflict or an unbound sender."""


@dataclass
class ImSessionBinding:
    """A 1:1 binding between an IM conversation and a MOGO session."""

    channel: str
    channel_conversation_id: str
    movo_session_id: str
    tenant_id: str = "default"
    initiated_by: str = ""            # MOGO user id resolved from the IM sender
    read_only: bool = False           # set when the channel is disabled (FR-9)

    def __post_init__(self) -> None:
        if not str(self.channel or "").strip():
            raise BindingError("channel must not be empty")
        if not str(self.channel_conversation_id or "").strip():
            raise BindingError("channel_conversation_id must not be empty")
        if not str(self.movo_session_id or "").strip():
            raise BindingError("movo_session_id must not be empty")


@dataclass
class SessionBindingRegistry:
    """Tracks IM-channel <-> MOGO-session bindings and channel switches."""

    bindings: dict[str, ImSessionBinding] = field(default_factory=dict)   # key: channel:conv
    session_owner: dict[str, str] = field(default_factory=dict)           # movo_session_id -> channel
    disabled_channels: set[str] = field(default_factory=set)

    @staticmethod
    def _key(channel: str, conversation_id: str) -> str:
        return f"{channel}:{conversation_id}"

    def bind(
        self,
        *,
        channel: str,
        conversation_id: str,
        movo_session_id: str,
        tenant_id: str = "default",
        initiator: str = "",
    ) -> ImSessionBinding:
        """Bind an IM conversation to a MOGO session (first binder wins, FR-14)."""
        if channel in self.disabled_channels:
            raise BindingError(f"channel is disabled: {channel}")

        key = self._key(channel, conversation_id)
        existing = self.bindings.get(key)
        if existing is not None:
            if existing.movo_session_id != movo_session_id:
                raise BindingError(
                    f"conversation already bound to session {existing.movo_session_id}"
                )
            return existing

        owner_channel = self.session_owner.get(movo_session_id)
        if owner_channel is not None and owner_channel != channel:
            # A MOGO session may be bound by only one IM channel (FR-14).
            raise BindingError(
                f"session {movo_session_id} already bound by channel {owner_channel}"
            )

        binding = ImSessionBinding(
            channel=channel,
            channel_conversation_id=conversation_id,
            movo_session_id=movo_session_id,
            tenant_id=tenant_id,
            initiated_by=initiator,
        )
        self.bindings[key] = binding
        self.session_owner[movo_session_id] = channel
        return binding

    def get(self, channel: str, conversation_id: str) -> Optional[ImSessionBinding]:
        return self.bindings.get(self._key(channel, conversation_id))

    def disable_channel(self, channel: str) -> int:
        """Disable a channel for a tenant; existing bindings become read-only (FR-9).

        Returns the number of bindings marked read-only.
        """
        self.disabled_channels.add(channel)
        affected = 0
        for binding in self.bindings.values():
            if binding.channel == channel:
                binding.read_only = True
                affected += 1
        return affected

    def enable_channel(self, channel: str) -> int:
        """Re-enable a channel, clearing the read-only flag on its bindings."""
        self.disabled_channels.discard(channel)
        restored = 0
        for binding in self.bindings.values():
            if binding.channel == channel and binding.read_only:
                binding.read_only = False
                restored += 1
        return restored


# ---------------------------------------------------------------------------
# MongoDB-backed persistence (013 FR-10 residual: 持久化 SessionBindingRegistry)
# ---------------------------------------------------------------------------

BINDING_COLLECTION = "im_session_bindings"
CHANNEL_COLLECTION = "im_channels"


def _binding_to_row(binding: ImSessionBinding) -> dict:
    return {
        "channel": binding.channel,
        "channel_conversation_id": binding.channel_conversation_id,
        "movo_session_id": binding.movo_session_id,
        "tenant_id": binding.tenant_id,
        "initiated_by": binding.initiated_by,
        "read_only": bool(binding.read_only),
    }


def _row_to_binding(row: dict) -> ImSessionBinding:
    return ImSessionBinding(
        channel=str(row.get("channel") or ""),
        channel_conversation_id=str(row.get("channel_conversation_id") or ""),
        movo_session_id=str(row.get("movo_session_id") or ""),
        tenant_id=str(row.get("tenant_id") or "default"),
        initiated_by=str(row.get("initiated_by") or ""),
        read_only=bool(row.get("read_only") or False),
    )


def _channel_key(tenant_id: str, channel: str) -> dict:
    return {"tenant_id": tenant_id, "channel": channel}


class PersistedSessionBindingRegistry:
    """MongoDB-backed IM-channel <-> MOGO-session binding store (FR-10).

    Mirrors the synchronous ``SessionBindingRegistry`` API with async methods.
    Bindings live in ``im_session_bindings`` (keyed by
    ``(tenant_id, channel, channel_conversation_id)``); channel switches live in
    ``im_channels`` (``disabled: bool``). Conflict semantics (first binder
    wins, FR-14) are enforced by reading the persisted rows before writing.
    DB unavailable → in-memory fallback so the webhook path degrades instead
    of failing (honest boundary: no fabricated persistence).
    """

    async def _db(self):
        try:
            from app.core.db import get_db

            db = get_db()
            return None if db is None else db
        except Exception as exc:
            log_print(f"[im_gateway.bindings] silent exception caught: {exc}", flush=True)

    async def load(self, tenant_id: str = "default") -> SessionBindingRegistry:
        """Load the tenant's persisted state into an in-memory registry."""
        registry = SessionBindingRegistry()
        db = await self._db()
        if db is None:
            return registry
        rows = await db[BINDING_COLLECTION].find({"tenant_id": tenant_id}).to_list(length=1000)
        for row in rows:
            binding = _row_to_binding(row)
            key = SessionBindingRegistry._key(binding.channel, binding.channel_conversation_id)
            registry.bindings[key] = binding
            registry.session_owner[binding.movo_session_id] = binding.channel
            if binding.read_only:
                registry.disabled_channels.add(binding.channel)
        return registry

    async def bind(
        self,
        *,
        channel: str,
        conversation_id: str,
        movo_session_id: str,
        tenant_id: str = "default",
        initiator: str = "",
    ) -> ImSessionBinding:
        """Bind and persist (first binder wins, FR-14; disabled channel rejected)."""
        registry = await self.load(tenant_id=tenant_id)
        binding = registry.bind(
            channel=channel,
            conversation_id=conversation_id,
            movo_session_id=movo_session_id,
            tenant_id=tenant_id,
            initiator=initiator,
        )
        db = await self._db()
        if db is not None:
            await db[BINDING_COLLECTION].update_one(
                {
                    "tenant_id": tenant_id,
                    "channel": channel,
                    "channel_conversation_id": conversation_id,
                },
                {"$set": _binding_to_row(binding)},
                upsert=True,
            )
        return binding

    async def get(self, channel: str, conversation_id: str, tenant_id: str = "default") -> Optional[ImSessionBinding]:
        db = await self._db()
        if db is None:
            return None
        row = await db[BINDING_COLLECTION].find_one({
            "tenant_id": tenant_id,
            "channel": channel,
            "channel_conversation_id": conversation_id,
        })
        return _row_to_binding(row) if row else None

    async def disable_channel(self, channel: str, tenant_id: str = "default") -> int:
        """Persist the channel switch; existing bindings become read-only (FR-9)."""
        db = await self._db()
        if db is None:
            return 0
        await db[CHANNEL_COLLECTION].update_one(
            _channel_key(tenant_id, channel),
            {"$set": {"disabled": True}},
            upsert=True,
        )
        result = await db[BINDING_COLLECTION].update_many(
            {"tenant_id": tenant_id, "channel": channel},
            {"$set": {"read_only": True}},
        )
        return int(getattr(result, "modified_count", 0) or 0)

    async def enable_channel(self, channel: str, tenant_id: str = "default") -> int:
        """Persist the re-enable; clear the read-only flag on that channel's bindings."""
        db = await self._db()
        if db is None:
            return 0
        await db[CHANNEL_COLLECTION].update_one(
            _channel_key(tenant_id, channel),
            {"$set": {"disabled": False}},
            upsert=True,
        )
        result = await db[BINDING_COLLECTION].update_many(
            {"tenant_id": tenant_id, "channel": channel, "read_only": True},
            {"$set": {"read_only": False}},
        )
        return int(getattr(result, "modified_count", 0) or 0)

    async def is_channel_enabled(self, channel: str, tenant_id: str = "default") -> bool:
        db = await self._db()
        if db is None:
            return True
        row = await db[CHANNEL_COLLECTION].find_one(_channel_key(tenant_id, channel))
        if row is None:
            return True
        return not bool(row.get("disabled") or False)


__all__ = [
    "BINDING_COLLECTION",
    "CHANNEL_COLLECTION",
    "ImSessionBinding",
    "PersistedSessionBindingRegistry",
    "SessionBindingRegistry",
    "BindingError",
    "resolve_group_sender",
]


def resolve_group_sender(
    *,
    sender_id: str,
    user_map: dict[str, str],
) -> str:
    """Resolve the MOGO user for an IM sender (group @bot initiator, FR-10).

    Raises ``BindingError`` when the sender has no MOGO user bound — the caller
    rejects the message and prompts the user to bind.
    """
    movo_user = str(user_map.get(sender_id) or "")
    if not movo_user:
        raise BindingError(f"IM sender not bound to a MOGO user: {sender_id}")
    return movo_user
