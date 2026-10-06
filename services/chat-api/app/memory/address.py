"""Memory address space (017 FR-18).

Exposes every memory as a browsable, resolvable URI following the unified
context-address convention defined in spec 021::

    mogo://memory/<scope>/<owner>/<id>/[L0|L1|L2]

Only the ``memory`` root lives here; ``resource`` / ``skill`` / ``session``
roots are owned by their respective specs and resolved by the 021 router.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple
from urllib.parse import quote, unquote

SCHEME = "mogo"
ROOT = "memory"
VALID_TIERS: Tuple[str, ...] = ("L0", "L1", "L2")
VALID_SCOPES: Tuple[str, ...] = ("personal", "workspace", "org")


@dataclass
class MemoryAddress:
    """A parsed ``mogo://memory/...`` address (FR-18)."""

    scope: str
    owner_id: str
    memory_id: str
    tier: str = "L0"

    def uri(self) -> str:
        # safe="" so slashes inside owner_id / memory_id are percent-encoded and
        # the path cannot be split at the wrong boundary.
        return (
            f"{SCHEME}://{ROOT}/"
            f"{quote(self.scope, safe='')}/{quote(self.owner_id, safe='')}/"
            f"{quote(self.memory_id, safe='')}/{self.tier}"
        )

    def with_tier(self, tier: str) -> "MemoryAddress":
        if tier not in VALID_TIERS:
            raise ValueError(f"invalid tier: {tier!r}")
        return MemoryAddress(self.scope, self.owner_id, self.memory_id, tier)


def parse_memory_uri(uri: str) -> MemoryAddress:
    """Parse a ``mogo://memory/...`` URI.

    Raises ``ValueError`` on a malformed scheme, missing segments, or an
    out-of-range scope / tier.
    """
    prefix = f"{SCHEME}://{ROOT}/"
    if not uri.startswith(prefix):
        raise ValueError(f"not a memory uri: {uri!r}")
    parts = uri[len(prefix):].split("/")
    if len(parts) < 3:
        raise ValueError(f"malformed memory uri (need scope/owner/id): {uri!r}")
    scope = unquote(parts[0])
    owner_id = unquote(parts[1])
    memory_id = unquote(parts[2])
    tier = unquote(parts[3]) if len(parts) >= 4 and parts[3] else "L0"
    if scope not in VALID_SCOPES:
        raise ValueError(f"invalid scope {scope!r} in {uri!r}")
    if tier not in VALID_TIERS:
        raise ValueError(f"invalid tier {tier!r} in {uri!r}")
    return MemoryAddress(scope=scope, owner_id=owner_id, memory_id=memory_id, tier=tier)


__all__ = ["MemoryAddress", "VALID_SCOPES", "VALID_TIERS", "parse_memory_uri"]
