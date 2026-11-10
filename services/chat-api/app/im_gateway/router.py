"""Unified channel router (013 FR-4 / FR-9 / T010).

Routes an inbound IM message to the right channel adapter and rejects channels
that are switched off (existing bindings for a disabled channel become read-only —
see ``bindings``). The router is adapter-agnostic and DB-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .adapter_base import ChannelAdapter, ChannelError, ChannelMessage, build_adapter
from .bindings import SessionBindingRegistry
from .routing import (
    ChannelEmployeeBinding,
    RoutingRuleError,
    resolve_employee,
    validate_bindings,
)


class RoutingError(ValueError):
    """Raised when a message cannot be routed."""


@dataclass
class ChannelRouter:
    """Dispatches inbound IM messages to per-channel adapters."""

    registry: SessionBindingRegistry = field(default_factory=SessionBindingRegistry)
    _adapters: dict[str, ChannelAdapter] = field(default_factory=dict)
    _disabled: set[str] = field(default_factory=set)

    def register(self, channel: str, adapter: ChannelAdapter | None = None) -> ChannelAdapter:
        """Register (or lazily build) the adapter for a channel."""
        resolved = adapter or build_adapter(channel)
        self._adapters[channel] = resolved
        return resolved

    def available_channels(self) -> list[str]:
        return sorted(self._adapters)

    def enable(self, channel: str) -> None:
        self._disabled.discard(channel)
        self.registry.enable_channel(channel)

    def disable(self, channel: str) -> None:
        """Disable a channel: new messages are rejected and bindings go read-only."""
        self._disabled.add(channel)
        self.registry.disable_channel(channel)

    def is_enabled(self, channel: str) -> bool:
        return channel not in self._disabled

    def route(self, channel: str, payload: dict[str, Any]) -> ChannelMessage:
        """Parse and validate an inbound payload.

        Raises ``RoutingError`` when the channel is unknown, not yet implemented,
        or switched off (FR-9).
        """
        if not self.is_enabled(channel):
            raise RoutingError(f"channel is disabled: {channel}")
        adapter = self._adapters.get(channel)
        if adapter is None:
            try:
                adapter = self.register(channel)
            except ChannelError as error:
                raise RoutingError(str(error)) from error
        return adapter.parse_inbound(payload)

    def bind_conversation(
        self,
        *,
        channel: str,
        conversation_id: str,
        mogo_session_id: str,
        tenant_id: str = "default",
        initiator: str = "",
    ):
        """Bind an IM conversation, respecting the channel switch (FR-9/FR-14)."""
        if not self.is_enabled(channel):
            raise RoutingError(f"channel is disabled: {channel}")
        return self.registry.bind(
            channel=channel,
            conversation_id=conversation_id,
            mogo_session_id=mogo_session_id,
            tenant_id=tenant_id,
            initiator=initiator,
        )

    # -- 051 B2：渠道-员工意图路由（T008 / FR-007，OQ-4 确定性） --------------

    def resolve_employee(
        self,
        bindings: list[ChannelEmployeeBinding],
        text: str,
    ) -> tuple[str | None, str]:
        """对给定绑定集合做确定性路由（DB-free，纯求值）。

        Returns ``(employee_id, route_kind)``；无默认员工时 ``(None, fallback)``，
        调用方回落既有无员工会话行为（FR-007 不拒绝消息）。
        """
        return resolve_employee(bindings, text)

    @staticmethod
    def validate_bindings(bindings: list[ChannelEmployeeBinding]) -> None:
        """规则集合校验（同渠道至多一条默认绑定，fail-closed）。"""
        validate_bindings(bindings)
