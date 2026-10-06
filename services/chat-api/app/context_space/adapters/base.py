"""Per-tenant tier adapter interface (021).

A ``TierAdapter`` knows how to resolve a typed ``mogo://`` address into its
tiered content for a given viewer. Each backend (memory / resource / skill /
session) supplies one. The 021 router is agnostic to the backend — it only
speaks this interface, which is what keeps the address space storage-free.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ResolvedTier:
    """The payload returned when an address is resolved (021)."""

    uri: str
    tier_used: str
    content: str
    meta: dict[str, Any] = None  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "tier_used": self.tier_used,
            "content": self.content,
            "meta": self.meta or {},
        }


class TierAdapter(ABC):
    """Interface every tenant adapter implements (021)."""

    root: str = ""

    @abstractmethod
    async def resolve(
        self,
        *,
        uri: str,
        tier: Optional[str],
        tenant_id: str,
        viewer: "ViewerContext",
    ) -> ResolvedTier:
        """Resolve ``uri`` for ``viewer``; raise on invisible / missing."""
        raise NotImplementedError


__all__ = ["ResolvedTier", "TierAdapter"]
