"""Admin egress allowlist CRUD store (038) — admin-api side.

Mirrors the chat-api ``egress_guard`` allowlist collection layout
(``egress_allowlist``) so the admin console and the runtime outbound guard share
one Mongo collection. This copy is intentionally dependency-free (no chat-api
imports) and only validates the entry's *shape*; the runtime guard's own
``normalize_match_domain`` / matching logic remains the authoritative
fail-closed check.
"""

from __future__ import annotations

import ipaddress
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

EGRESS_ALLOWLIST_COLLECTION = "egress_allowlist"

# Entry scope, most-specific-first matching order (tool > tenant > platform).
VALID_SCOPES = ("tool", "tenant", "platform")

# Platform default entries seeded on first use (T014). Model provider official
# domains plus commonly probed deployment targets; intentionally small and
# documented as a starting point — tenants extend it per-tenant.
PLATFORM_DEFAULT_DOMAINS: tuple[str, ...] = (
    "openai.com",
    "anthropic.com",
    "api.deepseek.com",
    "dashscope.aliyuncs.com",
    "api.moonshot.cn",
    "api.z.ai",
    "huggingface.co",
)


def _entry_id() -> str:
    return f"eg-{uuid.uuid4()}"


def normalize_match_domain(value: str) -> str:
    """Canonical form of a match domain suffix.

    ``example.com`` matches the exact host and every subdomain. IDNA/punycode
    is applied so Unicode internationalized domains compare correctly.
    """
    raw = (value or "").strip().lower()
    if raw.startswith("*."):
        raw = raw[2:].strip()
    raw = raw.rstrip(".")
    try:
        return raw.encode("idna").decode("ascii").rstrip(".")
    except UnicodeError:
        raise RuleValidationError(f"invalid match_domain (IDNA encode failed): {value!r}")


def normalize_path_prefix(value: str) -> str:
    """Canonical form of an optional path prefix (``/v1`` -> ``v1``)."""
    raw = (value or "").strip().lower().strip("/")
    return raw.rstrip("/")


def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


@dataclass
class EgressAllowlistDocument:
    entry_id: str
    scope: str
    match_domain: str
    tenant_id: str = ""
    tool_id: str = ""
    path_prefix: str = ""
    enabled: bool = True
    note: str = ""
    updated_at: str = ""

    def as_document(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "scope": self.scope,
            "match_domain": self.match_domain,
            "tenant_id": self.tenant_id,
            "tool_id": self.tool_id,
            "path_prefix": self.path_prefix,
            "enabled": self.enabled,
            "note": self.note,
            "updated_at": self.updated_at,
        }


class RuleValidationError(ValueError):
    """Fail-closed rejection of an invalid egress allowlist entry shape."""


class EgressAllowlistStore:
    """In-memory / Mongo-backed egress allowlist CRUD (038)."""

    def __init__(self, db: Optional[Any] = None) -> None:
        self._db = db
        self._entries: dict[str, EgressAllowlistDocument] = {}

    # --- shape validation (fail-closed) --------------------------------------

    @staticmethod
    def _validate(
        *,
        scope: str,
        match_domain: str,
        tenant_id: str = "",
        tool_id: str = "",
        path_prefix: str = "",
    ) -> str:
        """Validate and return the canonical (match_domain, path_prefix)."""
        if scope not in VALID_SCOPES:
            raise RuleValidationError(
                f"invalid egress scope: {scope!r} (must be one of {VALID_SCOPES})"
            )
        raw = (match_domain or "").strip()
        if not raw:
            raise RuleValidationError("match_domain must not be empty")
        if any(ch in raw for ch in ("/", ":", "@", " ", "\t", "\n")):
            raise RuleValidationError(
                "match_domain must be a bare host suffix (no scheme, path, port or userinfo)"
            )
        if is_ip_literal(raw.split(":")[0]):
            raise RuleValidationError(
                "match_domain must not be an IP literal — allow domains only"
            )
        domain = normalize_match_domain(raw)
        if "." not in domain:
            raise RuleValidationError(
                "match_domain must be a domain suffix containing at least one dot"
            )
        if scope == "tool" and not tool_id:
            raise RuleValidationError("tool scope requires tool_id")
        if scope == "tenant" and not tenant_id:
            raise RuleValidationError("tenant scope requires tenant_id")
        prefix = normalize_path_prefix(path_prefix or "")
        if prefix and ("://" in prefix or prefix.startswith("http")):
            raise RuleValidationError(
                "path_prefix must be a bare path prefix (no scheme), e.g. /v1"
            )
        return domain, prefix

    # --- CRUD ----------------------------------------------------------------

    async def create(
        self,
        *,
        scope: str,
        match_domain: str,
        tenant_id: str = "",
        tool_id: str = "",
        path_prefix: str = "",
        enabled: bool = True,
        note: str = "",
    ) -> EgressAllowlistDocument:
        domain, prefix = self._validate(
            scope=scope, match_domain=match_domain, tenant_id=tenant_id, tool_id=tool_id, path_prefix=path_prefix
        )
        document = EgressAllowlistDocument(
            entry_id=_entry_id(),
            scope=scope,
            match_domain=domain,
            tenant_id=tenant_id,
            tool_id=tool_id,
            path_prefix=prefix,
            enabled=enabled,
            note=note or "",
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        await self._insert(document)
        return document

    async def _insert(self, document: EgressAllowlistDocument) -> None:
        if self._db is not None:
            await self._db[EGRESS_ALLOWLIST_COLLECTION].insert_one(document.as_document())
        else:
            self._entries[document.entry_id] = document

    async def get(self, entry_id: str) -> Optional[EgressAllowlistDocument]:
        if self._db is not None:
            row = await self._db[EGRESS_ALLOWLIST_COLLECTION].find_one({"entry_id": entry_id})
            return self._from_row(row) if row else None
        return self._entries.get(entry_id)

    async def update(
        self,
        entry_id: str,
        *,
        match_domain: Optional[str] = None,
        path_prefix: Optional[str] = None,
        enabled: Optional[bool] = None,
        note: Optional[str] = None,
        tool_id: Optional[str] = None,
    ) -> Optional[EgressAllowlistDocument]:
        document = await self.get(entry_id)
        if document is None:
            return None
        if match_domain is not None:
            document.match_domain = match_domain
        if path_prefix is not None:
            document.path_prefix = path_prefix
        if tool_id is not None:
            document.tool_id = tool_id
        if enabled is not None:
            document.enabled = enabled
        if note is not None:
            document.note = note
        domain, prefix = self._validate(
            scope=document.scope,
            match_domain=document.match_domain,
            tenant_id=document.tenant_id,
            tool_id=document.tool_id,
            path_prefix=document.path_prefix,
        )
        document.match_domain = domain
        document.path_prefix = prefix
        document.updated_at = datetime.now(timezone.utc).isoformat()
        if self._db is not None:
            await self._db[EGRESS_ALLOWLIST_COLLECTION].update_one(
                {"entry_id": entry_id}, {"$set": document.as_document()}
            )
        return document

    async def delete(self, entry_id: str) -> bool:
        if self._db is not None:
            result = await self._db[EGRESS_ALLOWLIST_COLLECTION].delete_one({"entry_id": entry_id})
            return bool(getattr(result, "deleted_count", 0))
        return self._entries.pop(entry_id, None) is not None

    async def list(self) -> list[EgressAllowlistDocument]:
        if self._db is not None:
            rows = await self._db[EGRESS_ALLOWLIST_COLLECTION].find({}).to_list(length=10000)
            return [self._from_row(row) for row in rows if row]
        return list(self._entries.values())

    async def list_visible(self, tenant_id: str) -> list[EgressAllowlistDocument]:
        """Tenant-scoped view: platform entries + the tenant's own entries."""
        return [
            e for e in await self.list() if not e.tenant_id or e.tenant_id == tenant_id
        ]

    # --- platform defaults (T014) --------------------------------------------

    async def seed_platform_defaults(self) -> list[EgressAllowlistDocument]:
        """Idempotently seed platform-scope defaults when none exist yet."""
        existing_platform = [e for e in await self.list() if e.scope == "platform"]
        if existing_platform:
            return existing_platform
        created: list[EgressAllowlistDocument] = []
        for domain in PLATFORM_DEFAULT_DOMAINS:
            created.append(
                await self.create(
                    scope="platform",
                    match_domain=domain,
                    tenant_id="",
                    enabled=True,
                    note="platform default (038)",
                )
            )
        return created

    @staticmethod
    def _from_row(row: dict[str, Any]) -> EgressAllowlistDocument:
        return EgressAllowlistDocument(
            entry_id=str(row.get("entry_id") or ""),
            scope=str(row.get("scope") or ""),
            match_domain=str(row.get("match_domain") or ""),
            tenant_id=str(row.get("tenant_id") or ""),
            tool_id=str(row.get("tool_id") or ""),
            path_prefix=str(row.get("path_prefix") or ""),
            enabled=bool(row.get("enabled", True)),
            note=str(row.get("note") or ""),
            updated_at=str(row.get("updated_at") or ""),
        )


__all__ = [
    "EGRESS_ALLOWLIST_COLLECTION",
    "EgressAllowlistDocument",
    "EgressAllowlistStore",
    "PLATFORM_DEFAULT_DOMAINS",
    "RuleValidationError",
    "VALID_SCOPES",
    "normalize_match_domain",
    "normalize_path_prefix",
]
