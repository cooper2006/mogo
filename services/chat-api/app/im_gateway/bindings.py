"""IM session <-> MOVO session bindings (013 FR-2 / FR-7 / FR-9 / FR-10 / FR-14).

* mapping granularity is 1:1 — one IM conversation maps to one MOVO session;
* the binding carries the channel identity so 002's commit/share apply to IM
  sessions too (FR-7);
* **only one IM channel may bind a MOVO session** — the first binder wins (FR-14);
* a per-tenant channel switch turns existing IM sessions read-only (FR-9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class BindingError(ValueError):
    """Raised for a binding conflict or an unbound sender."""


@dataclass
class ImSessionBinding:
    """A 1:1 binding between an IM conversation and a MOVO session."""

    channel: str
    channel_conversation_id: str
    movo_session_id: str
    tenant_id: str = "default"
    initiated_by: str = ""            # MOVO user id resolved from the IM sender
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
    """Tracks IM-channel <-> MOVO-session bindings and channel switches."""

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
        """Bind an IM conversation to a MOVO session (first binder wins, FR-14)."""
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
            # A MOVO session may be bound by only one IM channel (FR-14).
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


def resolve_group_sender(
    *,
    sender_id: str,
    user_map: dict[str, str],
) -> str:
    """Resolve the MOVO user for an IM sender (group @bot initiator, FR-10).

    Raises ``BindingError`` when the sender has no MOVO user bound — the caller
    rejects the message and prompts the user to bind.
    """
    movo_user = str(user_map.get(sender_id) or "")
    if not movo_user:
        raise BindingError(f"IM sender not bound to a MOVO user: {sender_id}")
    return movo_user
