"""Channel adapter base (013 FR-1 / FR-4 / FR-5).

Each IM channel implements a small adapter: parse an inbound message, render a
reply. The first delivery targets **Feishu** (clarify OQ-1) with plain text +
basic markdown cards (clarify OQ-2); long responses are chunked as plain text, not
streamed as segments (FR-2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Default chunk size for long IM responses.
DEFAULT_CHUNK_SIZE = 2000

# Supported channels; the first delivery enables Feishu only.
SUPPORTED_CHANNELS: tuple[str, ...] = ("feishu", "dingtalk", "wecom", "slack", "teams")
FIRST_DELIVERY_CHANNEL = "feishu"


class ChannelError(ValueError):
    """Raised for an unknown or misconfigured channel."""


@dataclass
class ChannelMessage:
    """An inbound IM message."""

    channel: str
    channel_conversation_id: str
    sender_id: str
    text: str = ""
    is_group: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundChunk:
    """One chunk of an outbound reply."""

    text: str
    index: int = 0
    is_final: bool = False


@dataclass
class ChannelReply:
    """A reply to be delivered back to the IM channel."""

    conversation_id: str
    chunks: list[OutboundChunk] = field(default_factory=list)
    markdown: bool = True

    def as_text(self) -> str:
        return "".join(chunk.text for chunk in self.chunks)


def chunk_text(text: str, *, size: int = DEFAULT_CHUNK_SIZE) -> list[OutboundChunk]:
    """Split a long response into plain-text chunks (FR-2).

    Chunking is plain text — no streaming segments — so an IM client that lacks
    incremental rendering still receives the whole answer.
    """
    if size <= 0:
        raise ValueError("chunk size must be positive")
    body = text or ""
    if not body:
        return []
    chunks: list[OutboundChunk] = []
    total = len(body)
    index = 0
    for start in range(0, total, size):
        piece = body[start : start + size]
        index += 1
        chunks.append(
            OutboundChunk(text=piece, index=index, is_final=(start + size >= total))
        )
    return chunks


class ChannelAdapter:
    """Base class for a channel adapter."""

    channel: str = ""

    def __init__(self, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> None:
        if not self.channel:
            raise ChannelError("adapter must declare a channel name")
        self._chunk_size = chunk_size

    def parse_inbound(self, payload: dict[str, Any]) -> ChannelMessage:
        """Parse a raw webhook payload into a ``ChannelMessage``."""
        raise NotImplementedError

    def render_reply(self, *, conversation_id: str, text: str, markdown: bool = True) -> ChannelReply:
        """Render a MOGO response back into channel chunks."""
        return ChannelReply(
            conversation_id=conversation_id,
            chunks=chunk_text(text, size=self._chunk_size),
            markdown=markdown,
        )


class FeishuAdapter(ChannelAdapter):
    """Feishu (Lark) adapter — the first-delivery channel (clarify OQ-1)."""

    channel = "feishu"

    def parse_inbound(self, payload: dict[str, Any]) -> ChannelMessage:
        event = payload.get("event") or {}
        message = event.get("message") or {}
        sender = event.get("sender") or {}
        chat_type = str(message.get("chat_type") or "p2p")
        text = _extract_feishu_text(message.get("content"))
        return ChannelMessage(
            channel=self.channel,
            channel_conversation_id=str(message.get("chat_id") or ""),
            sender_id=str(sender.get("sender_id", {}).get("open_id") or sender.get("open_id") or ""),
            text=text,
            is_group=(chat_type == "group"),
            raw=payload,
        )


def _extract_feishu_text(content: Any) -> str:
    """Pull plain text out of Feishu's JSON-encoded ``content`` field."""
    import json

    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (ValueError, TypeError):
            return content
        if isinstance(parsed, dict):
            return str(parsed.get("text") or "")
        return str(parsed)
    if isinstance(content, dict):
        return str(content.get("text") or "")
    return ""


class DingtalkAdapter(ChannelAdapter):
    """DingTalk (钉钉) adapter (013 P1 残项续五十五)."""

    channel = "dingtalk"

    def parse_inbound(self, payload: dict[str, Any]) -> ChannelMessage:
        """Parse a DingTalk robot webhook payload.

        Supports both the ``text`` plain-message envelope and the ``markdown``
        card envelope. ``conversationId`` / ``senderStaffId`` are the
        DingTalk field names.
        """
        msg_type = str(payload.get("msgtype") or payload.get("msg_type") or "text")
        text = str(payload.get("text", {}).get("content") if isinstance(payload.get("text"), dict) else (payload.get("content") or payload.get("msg") or ""))
        conversation_id = str(payload.get("conversationId") or payload.get("openConversationId") or "")
        sender_id = str(payload.get("senderStaffId") or payload.get("senderId") or payload.get("senderNick") or "")
        return ChannelMessage(
            channel=self.channel,
            channel_conversation_id=conversation_id,
            sender_id=sender_id,
            text=text.strip(),
            is_group=str(payload.get("conversationType") or payload.get("conversation_type") or "") in {"2", "group"},
            raw=payload,
        )


class WecomAdapter(ChannelAdapter):
    """WeCom (企业微信) adapter (013 P1 残项续五十五)."""

    channel = "wecom"

    def parse_inbound(self, payload: dict[str, Any]) -> ChannelMessage:
        """Parse a WeCom bot webhook payload (msgtype=text/card)."""
        text = str(payload.get("content") or payload.get("text") or "")
        conversation_id = str(payload.get("chatid") or payload.get("chat_id") or "")
        sender_id = str(payload.get("from") or payload.get("userid") or "")
        return ChannelMessage(
            channel=self.channel,
            channel_conversation_id=conversation_id,
            sender_id=sender_id,
            text=text.strip(),
            is_group=bool(conversation_id),
            raw=payload,
        )


class SlackAdapter(ChannelAdapter):
    """Slack Events API adapter (013 P1 残项续五十五)."""

    channel = "slack"

    def parse_inbound(self, payload: dict[str, Any]) -> ChannelMessage:
        """Parse a Slack ``message_events`` payload.

        Slack Events API delivers ``{"event": {"type": "message", "channel": "C123",
        "user": "U456", "text": "..."}}``.
        """
        event = payload.get("event") or payload
        text = str(event.get("text") or "")
        conversation_id = str(event.get("channel") or event.get("thread_ts") or "")
        sender_id = str(event.get("user") or event.get("user_id") or "")
        is_group = str(event.get("channel_type") or "") in {"group", "mpim"}
        return ChannelMessage(
            channel=self.channel,
            channel_conversation_id=conversation_id,
            sender_id=sender_id,
            text=text.strip(),
            is_group=is_group,
            raw=payload,
        )


class TeamsAdapter(ChannelAdapter):
    """Microsoft Teams (Graph Bot Framework) adapter (013 P1 残项续五十五)."""

    channel = "teams"

    def parse_inbound(self, payload: dict[str, Any]) -> ChannelMessage:
        """Parse a Teams Bot Framework activity.

        Teams delivers ``{"type": "message", "conversation": {"id": "..."},
        "from": {"id": "..."}, "text": "..."}``.
        """
        text = str(payload.get("text") or payload.get("message", {}).get("body") or "")
        conversation_id = str(payload.get("conversation", {}).get("id") if isinstance(payload.get("conversation"), dict) else (payload.get("conversationId") or ""))
        sender_id = str(payload.get("from", {}).get("id") if isinstance(payload.get("from"), dict) else (payload.get("from") or ""))
        return ChannelMessage(
            channel=self.channel,
            channel_conversation_id=conversation_id,
            sender_id=sender_id,
            text=text.strip(),
            is_group=str(payload.get("conversation", {}).get("conversationType") if isinstance(payload.get("conversation"), dict) else "") in {"GroupChat", "Channel"},
            raw=payload,
        )


def build_adapter(channel: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> ChannelAdapter:
    """Construct an adapter for ``channel``."""
    channel = channel.lower().strip()
    if channel == "feishu":
        return FeishuAdapter(chunk_size=chunk_size)
    if channel == "dingtalk":
        return DingtalkAdapter(chunk_size=chunk_size)
    if channel == "wecom":
        return WecomAdapter(chunk_size=chunk_size)
    if channel == "slack":
        return SlackAdapter(chunk_size=chunk_size)
    if channel == "teams":
        return TeamsAdapter(chunk_size=chunk_size)
    raise ChannelError(f"unknown channel: {channel}")
