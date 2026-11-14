"""Attribute successful session tool calls to the installed plugin that supplied them."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from .repository import PluginInstallationRepository

logger = logging.getLogger(__name__)


def plugin_for_tool(plugins: Iterable[dict[str, Any]], tool_name: str) -> dict[str, Any] | None:
    """A duplicate tool name has no trustworthy single plugin owner."""
    matches = [plugin for plugin in plugins if tool_name in (plugin.get("tool_names") or [])]
    return matches[0] if len(matches) == 1 else None


class PluginInvocationRecorder:
    def __init__(self, repository: PluginInstallationRepository | None = None) -> None:
        self._repository = repository or PluginInstallationRepository()

    async def record(
        self, *, tenant_id: str, user_id: str,
        plugins: Iterable[dict[str, Any]], tool_names: Iterable[str],
    ) -> None:
        for tool_name in set(tool_names):
            plugin = plugin_for_tool(plugins, tool_name)
            if plugin is None:
                continue
            owner = user_id if plugin.get("source_scope") == "personal" else ""
            try:
                await self._repository.mark_invoked(
                    tenant_id=tenant_id, user_id=owner,
                    name=str(plugin.get("name") or ""),
                    version=str(plugin.get("version") or ""),
                    spec=str(plugin.get("spec") or ""),
                    tool_name=tool_name,
                )
            except Exception:
                # Diagnosis is observational and must never fail a chat turn.
                logger.exception("failed to record DSH plugin invocation", extra={"tool_name": tool_name})
