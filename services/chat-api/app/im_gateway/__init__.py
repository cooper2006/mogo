"""Multi-IM entry gateway (feature 013).

IM channels are just an entry point: they map IM conversations onto MOVO sessions
and route responses back, reusing the existing Workspace/Sandbox capability surface
— no new capability is introduced.

This package holds the dependency-light core (adapter base / IM-session binding /
webhook security), so it is unit-testable without a live IM channel.
"""

from __future__ import annotations

from .adapter_base import (
    ChannelAdapter,
    ChannelMessage,
    ChannelReply,
    OutboundChunk,
    chunk_text,
)
from .bindings import BindingError, ImSessionBinding, SessionBindingRegistry
from .router import ChannelRouter, RoutingError
from .webhook import (
    REPLAY_WINDOW_SECONDS,
    NonceCache,
    WebhookSignatureError,
    sign_payload,
    verify_signature,
)

__all__ = [
    "ChannelAdapter",
    "ChannelMessage",
    "ChannelReply",
    "OutboundChunk",
    "chunk_text",
    "ImSessionBinding",
    "SessionBindingRegistry",
    "BindingError",
    "NonceCache",
    "sign_payload",
    "verify_signature",
    "WebhookSignatureError",
    "REPLAY_WINDOW_SECONDS",
    "ChannelRouter",
    "RoutingError",
]
