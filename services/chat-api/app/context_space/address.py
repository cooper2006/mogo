"""Unified context-address parsing for every 021 root.

The 021 address space spans four roots, each owned by a different spec but
resolved through one router::

    mogo://memory/<scope>/<owner>/<id>/[L0|L1|L2]     ← 017 (already in app/memory/address)
    mogo://resource/doc/<tenantId>/<documentId>/<chunkId>
    mogo://resource/biz/<system>/<entityType>/<recordId>
    mogo://resource/kg/<nodeId>
    mogo://skill/<orgId>/<skillId>[/<version>]
    mogo://skill/asset/<assetKey>
    mogo://session/<tenant>/<sessionId>/[L0|L1|L2]

This module owns the non-memory roots and a single ``parse_context_uri`` that
dispatches by root. ``memory`` is re-parsed by the existing
:func:`app.memory.address.parse_memory_uri` so the two never drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Union
from urllib.parse import quote, unquote

from app.memory.address import MemoryAddress, parse_memory_uri

SCHEME = "mogo"
VALID_TIERS: Tuple[str, ...] = ("L0", "L1", "L2")

# resource subtypes
DOC = "doc"
BIZ = "biz"
KG = "kg"
# skill subtypes
SKILL = "skill"
ASSET = "asset"


@dataclass
class ResourceAddress:
    """A ``mogo://resource/<subtype>/...`` address (021 / 005 / 014 / 015)."""

    subtype: str
    identifiers: Tuple[str, ...]
    tier: str = "L0"
    root: str = "resource"

    @property
    def tenant_id(self) -> str:
        """The owning tenant is always the first identifier (021 tenant scoping)."""
        return self.identifiers[0] if self.identifiers else ""

    def uri(self) -> str:
        segs = [quote(str(s), safe="") for s in self.identifiers]
        return f"{SCHEME}://{self.root}/{self.subtype}/" + "/".join(segs) + f"/{self.tier}"

    @classmethod
    def parse(cls, path: str) -> "ResourceAddress":
        parts = [unquote(p) for p in path.split("/") if p != ""]
        if not parts:
            raise ValueError("empty resource path")
        subtype = parts[0]
        id_parts, tier = _split_tier(parts[1:])
        if subtype not in (DOC, BIZ, KG):
            raise ValueError(f"unknown resource subtype: {subtype!r}")
        # Every resource address leads with the owning tenant (021 tenant scoping).
        if subtype == DOC and len(id_parts) != 3:
            raise ValueError("resource/doc needs <tenantId>/<documentId>/<chunkId>")
        if subtype == BIZ and len(id_parts) != 4:
            raise ValueError("resource/biz needs <tenantId>/<system>/<entityType>/<recordId>")
        if subtype == KG and len(id_parts) != 2:
            raise ValueError("resource/kg needs <tenantId>/<nodeId>")
        return cls(subtype=subtype, identifiers=tuple(id_parts), tier=tier)


@dataclass
class SkillAddress:
    """A ``mogo://skill/...`` address (021 / 004 / 018).

    Two forms share the ``skill`` root:

    * ``skill/<orgId>/<skillId>[/<version>]`` — a 004 Skill (subtype ``skill``)
    * ``skill/asset/<assetKey>``            — a 018 capability asset (subtype ``asset``)
    """

    subtype: str
    identifiers: Tuple[str, ...]
    tier: str = "L0"
    root: str = "skill"

    def uri(self) -> str:
        segs = [quote(str(s), safe="") for s in self.identifiers]
        if self.subtype == ASSET:
            return f"{SCHEME}://{self.root}/asset/" + "/".join(segs) + f"/{self.tier}"
        return f"{SCHEME}://{self.root}/" + "/".join(segs) + f"/{self.tier}"

    @classmethod
    def parse(cls, path: str) -> "SkillAddress":
        parts = [unquote(p) for p in path.split("/") if p != ""]
        if not parts:
            raise ValueError("empty skill path")
        if parts[0] == ASSET:
            id_parts, tier = _split_tier(parts[1:])
            if len(id_parts) != 1:
                raise ValueError("skill/asset needs <assetKey>")
            return cls(subtype=ASSET, identifiers=tuple(id_parts), tier=tier)
        # 004 Skill form: <orgId>/<skillId>[/<version>]
        id_parts, tier = _split_tier(parts)
        if not (2 <= len(id_parts) <= 3):
            raise ValueError("skill needs <orgId>/<skillId>[/<version>]")
        return cls(subtype=SKILL, identifiers=tuple(id_parts), tier=tier)


@dataclass
class SessionAddress:
    """A ``mogo://session/<tenant>/<sessionId>/[L0|L1|L2]`` address (021 / 002)."""

    tenant_id: str
    session_id: str
    tier: str = "L0"
    root: str = "session"

    def uri(self) -> str:
        return (
            f"{SCHEME}://{self.root}/"
            f"{quote(self.tenant_id, safe='')}/{quote(self.session_id, safe='')}/{self.tier}"
        )

    @classmethod
    def parse(cls, path: str) -> "SessionAddress":
        parts = [unquote(p) for p in path.split("/") if p != ""]
        id_parts, tier = _split_tier(parts)
        if len(id_parts) < 2:
            raise ValueError("session needs <tenant>/<sessionId>")
        return cls(tenant_id=id_parts[0], session_id=id_parts[1], tier=tier)


def _split_tier(parts: list[str]) -> Tuple[list[str], str]:
    """Pop a trailing tier segment if present, else default to ``L0``."""
    if parts and parts[-1] in VALID_TIERS:
        return parts[:-1], parts[-1]
    return parts, "L0"


def parse_context_uri(uri: str) -> Union[MemoryAddress, ResourceAddress, SkillAddress, SessionAddress]:
    """Dispatch a ``mogo://`` URI to its root-specific address object.

    Raises ``ValueError`` for a non-``mogo://`` scheme or an unknown root.
    """
    prefix = f"{SCHEME}://"
    if not uri.startswith(prefix):
        raise ValueError(f"not a {SCHEME}:// uri: {uri!r}")
    rest = uri[len(prefix):]
    root, _, path = rest.partition("/")
    if root == "memory":
        return parse_memory_uri(uri)
    if root == "resource":
        return ResourceAddress.parse(path)
    if root == "skill":
        return SkillAddress.parse(path)
    if root == "session":
        return SessionAddress.parse(path)
    raise ValueError(f"unknown context root: {root!r}")


__all__ = [
    "ASSET",
    "BIZ",
    "DOC",
    "KG",
    "SKILL",
    "MemoryAddress",
    "ResourceAddress",
    "SessionAddress",
    "SkillAddress",
    "parse_context_uri",
]
