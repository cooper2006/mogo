"""038 egress sandbox — outbound allowlist guard (chat-api runtime).

The runtime half of 038: every external HTTP / MCP tool call and every browser
Agent navigation is checked against a three-layer allowlist (tool > tenant >
platform) and rejected when nothing matches (fail-closed). Non-http(s) schemes
and IP literals are rejected up front, which also hardens against SSRF.

Security posture
----------------
* ``check`` never raises for a *policy* outcome — a denied / unknown / timed-out
  URL always yields ``EgressDecision(allowed=False, ...)``. Only a programmer
  error propagates.
* Matching is a bare host-suffix match (``example.com`` covers the exact host
  and every subdomain) plus an optional lower-cased path prefix. No regex, no
  single-URL exact matching.
* Defaults are deny. There is deliberately no "disable the allowlist" switch.

Remote sandbox
--------------
The spec (038) reserves ``execution_location == "remote_sandbox"`` as the
high-risk execution tier and leaves the sandbox itself out of scope for this
iteration; the runtime records the reservation explicitly (see
``_evaluate``) without shipping a sandbox transport.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Sequence
from urllib.parse import urlparse

from app.core.db import get_db

from .contracts import utc_now
from .persistence_codec import store_json_field

EGRESS_ALLOWLIST_COLLECTION = "egress_allowlist"
EGRESS_AUDIT_COLLECTION = "enterprise_tool_audit"

EGRESS_ALLOWED_EVENT = "egress.allowed"
EGRESS_DENIED_EVENT = "egress.denied"
EGRESS_MISSING_TARGET_EVENT = "egress.target_url_missing"

# Most-specific-first matching order.
VALID_SCOPES = ("tool", "tenant", "platform")

SCHEMES = ("http", "https")

# How long an allowlist snapshot stays warm (seconds). Short on purpose so a
# tenant edit is honoured on the next call while still batching bursts.
DEFAULT_SNAPSHOT_TTL_SECONDS = 2.0
# Budget for a single check, including the (rare) allowlist load.
DEFAULT_EGRESS_TIMEOUT_MS = 5000

_TEMPLATE_RE = re.compile(r"\{[^{}]*\}")


# ---------------------------------------------------------------------------
# Pure normalization / matching helpers
# ---------------------------------------------------------------------------


def normalize_match_domain(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw.startswith("*."):
        raw = raw[2:].strip()
    raw = raw.rstrip(".")
    try:
        return raw.encode("idna").decode("ascii").rstrip(".")
    except UnicodeError as error:
        raise ValueError(f"invalid match_domain (IDNA encode failed): {value!r}") from error


def normalize_path_prefix(value: str) -> str:
    return (value or "").strip().lower().strip("/").rstrip("/")


def is_ip_literal(host: str) -> bool:
    """True for any dotted/IP literal (covers loopback / RFC1918 / link-local)."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def normalize_url(url: str) -> tuple[str, str, int, str]:
    """Return ``(scheme, hostname, port, path)`` or raise ``ValueError``.

    Host is lower-cased, trailing-dot stripped and IDNA-encoded; default ports
    (``:80``/``:443``) are normalised away; a missing path becomes ``/``.
    """
    raw = (url or "").strip()
    if not raw or "://" not in raw:
        raise ValueError(f"egress: not an absolute http(s) URL: {url!r}")
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in SCHEMES:
        raise ValueError(f"egress: unsupported scheme {parsed.scheme!r} (http/https only)")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"egress: URL has no host: {url!r}")
    host = hostname.rstrip(".").lower()
    try:
        host = host.encode("idna").decode("ascii").rstrip(".")
    except UnicodeError as error:
        raise ValueError(f"egress: invalid host IDNA: {host!r}") from error
    port = parsed.port
    if port is None or (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        port = 443 if scheme == "https" else 80
    path = parsed.path or "/"
    return scheme, host, port, path


def matches_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def matches_path(path: str, prefix: str) -> bool:
    if not prefix:
        return True
    path_lower = path.lower()
    return path_lower == "/" + prefix or path_lower.startswith("/" + prefix + "/")


def strip_url_secrets(url: str) -> str:
    """URL without query/fragment/userinfo — the only form we may audit/log."""
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc.split('@')[-1]}{parsed.path}"
    except Exception:  # noqa: BLE001
        return "<unparsable-url>"


@dataclass(frozen=True)
class EgressEntry:
    entry_id: str
    scope: str
    match_domain: str
    tenant_id: str = ""
    tool_id: str = ""
    path_prefix: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class EgressDecision:
    allowed: bool
    domain: str
    reason: str
    matched_scope: str = ""
    matched_entry_id: str = ""
    matched_path_prefix: str = ""
    scheme: str = ""
    url_safe: str = ""


def _entry_from_row(row: dict[str, Any]) -> EgressEntry:
    return EgressEntry(
        entry_id=str(row.get("entry_id") or ""),
        scope=str(row.get("scope") or ""),
        match_domain=str(row.get("match_domain") or ""),
        tenant_id=str(row.get("tenant_id") or ""),
        tool_id=str(row.get("tool_id") or ""),
        path_prefix=str(row.get("path_prefix") or ""),
        enabled=bool(row.get("enabled", True)),
    )


SnapshotLoader = Callable[[str], Awaitable[Sequence[EgressEntry]]]
AuditSink = Callable[[dict[str, Any]], Awaitable[None]]


async def _default_snapshot_loader(tenant_id: str) -> list[EgressEntry]:
    db = get_db()
    if db is None:
        return []
    rows = await db[EGRESS_ALLOWLIST_COLLECTION].find({"enabled": True}).to_list(length=10000)
    entries = [_entry_from_row(row) for row in rows if row]
    if tenant_id:
        entries = [e for e in entries if not e.tenant_id or e.tenant_id == tenant_id]
    return entries


async def _default_audit_sink(document: dict[str, Any]) -> None:
    db = get_db()
    if db is None:
        return
    await db[EGRESS_AUDIT_COLLECTION].insert_one(document)


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


class EgressGuard:
    """In-process allowlist guard with a short-lived snapshot cache."""

    def __init__(
        self,
        snapshot_loader: Optional[SnapshotLoader] = None,
        audit_sink: Optional[AuditSink] = None,
        *,
        timeout_ms: int = DEFAULT_EGRESS_TIMEOUT_MS,
        ttl: float = DEFAULT_SNAPSHOT_TTL_SECONDS,
    ) -> None:
        self._loader = snapshot_loader or _default_snapshot_loader
        self._audit_sink = audit_sink or _default_audit_sink
        self._timeout = timeout_ms / 1000.0
        self._ttl = ttl
        # tenant_id -> (expires_at_monotonic, entries)
        self._cache: dict[str, tuple[float, list[EgressEntry]]] = {}
        self._lock = asyncio.Lock()

    # -- snapshot ------------------------------------------------------------

    async def _snapshot(self, tenant_id: str) -> list[EgressEntry]:
        now = time.monotonic()
        cached = self._cache.get(tenant_id)
        if cached and cached[0] > now:
            return cached[1]
        async with self._lock:
            now = time.monotonic()
            cached = self._cache.get(tenant_id)
            if cached and cached[0] > now:
                return cached[1]
            try:
                entries = list(await self._loader(tenant_id))
            except Exception:  # noqa: BLE001 — an unavailable allowlist is a deny
                entries = []
            self._cache[tenant_id] = (now + self._ttl, entries)
            return entries

    def invalidate(self, tenant_id: Optional[str] = None) -> None:
        """Drop the cached snapshot so the next call reloads config."""
        if tenant_id is None:
            self._cache.clear()
        else:
            self._cache.pop(tenant_id, None)

    # -- decision ------------------------------------------------------------

    def _match(self, entries: Sequence[EgressEntry], host: str, path: str) -> Optional[EgressEntry]:
        rank = {"tool": 0, "tenant": 1, "platform": 2}
        for entry in sorted(entries, key=lambda e: rank.get(e.scope, 3)):
            if not matches_domain(host, entry.match_domain):
                continue
            if not matches_path(path, entry.path_prefix):
                continue
            return entry
        return None

    async def _evaluate(self, url: str, tenant_id: str, tool_id: str, execution_location: str) -> EgressDecision:
        try:
            scheme, host, _port, path = normalize_url(url)
        except ValueError as error:
            return EgressDecision(allowed=False, domain="", reason=str(error), url_safe=strip_url_secrets(url))

        safe_url = strip_url_secrets(url)

        if is_ip_literal(host):
            return EgressDecision(
                allowed=False,
                domain=host,
                reason="ip-literal-not-allowed (SSRF guard)",
                scheme=scheme,
                url_safe=safe_url,
            )

        if execution_location == "remote_sandbox":
            # 038 spec: reserved high-risk execution tier. The sandbox transport
            # is out of scope for this iteration, so remote sandbox execution is
            # recorded as unsupported and treated as denied (fail-closed).
            return EgressDecision(
                allowed=False,
                domain=host,
                reason="remote_sandbox-not-implemented (038)",
                scheme=scheme,
                url_safe=safe_url,
            )

        entries = await self._snapshot(tenant_id)
        tool_entries = [e for e in entries if e.scope != "tool" or (tool_id and e.tool_id == tool_id)]
        matched = self._match(tool_entries, host, path)
        if matched is None:
            return EgressDecision(
                allowed=False,
                domain=host,
                reason="no-allowlist-match",
                scheme=scheme,
                url_safe=safe_url,
            )
        return EgressDecision(
            allowed=True,
            domain=host,
            reason="allowlist-match",
            matched_scope=matched.scope,
            matched_entry_id=matched.entry_id,
            matched_path_prefix=matched.path_prefix,
            scheme=scheme,
            url_safe=safe_url,
        )

    async def check(
        self,
        *,
        url: str,
        tenant_id: str = "",
        tool_id: str = "",
        execution_location: str = "server",
    ) -> EgressDecision:
        """Decide one outbound URL. Never raises for a policy outcome."""
        if not (url or "").strip():
            return EgressDecision(allowed=False, domain="", reason="empty-url")
        try:
            return await asyncio.wait_for(
                self._evaluate(url=url, tenant_id=tenant_id, tool_id=tool_id, execution_location=execution_location),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            return EgressDecision(allowed=False, domain="", reason="egress-check-timeout")
        except Exception as error:  # noqa: BLE001 — unexpected failure is a deny
            return EgressDecision(allowed=False, domain="", reason=f"egress-check-error: {type(error).__name__}")

    async def decide_urls(
        self,
        urls: Sequence[str],
        *,
        tenant_id: str = "",
        tool_id: str = "",
        execution_location: str = "server",
    ) -> EgressDecision:
        """Aggregate many candidate URLs (e.g. a tool's url + endpoint).

        All must be allowed; any denied candidate denies the call, and the first
        denial is returned so the caller reports the offending domain.
        """
        candidates = [u for u in (urls or []) if u and str(u).strip()]
        if not candidates:
            return EgressDecision(allowed=False, domain="", reason="no-outbound-url")
        worst: Optional[EgressDecision] = None
        for url in candidates:
            decision = await self.check(
                url=url, tenant_id=tenant_id, tool_id=tool_id, execution_location=execution_location
            )
            if not decision.allowed and worst is None:
                worst = decision
        if worst is not None:
            return worst
        # Every candidate allowed — report the first one's decision.
        return await self.check(
            url=candidates[0], tenant_id=tenant_id, tool_id=tool_id, execution_location=execution_location
        )

    async def audit(
        self,
        decision: EgressDecision,
        *,
        tenant_id: str,
        user_id: str,
        action_id: str,
        tool_or_capability: str,
        event_allowed: str = EGRESS_ALLOWED_EVENT,
        event_denied: str = EGRESS_DENIED_EVENT,
    ) -> None:
        """Best-effort audit into the existing tool audit channel."""
        event = event_allowed if decision.allowed else event_denied
        details = {
            "egress": "egress-sandbox",
            "capability": tool_or_capability,
            "domain": decision.domain,
            "url_safe": decision.url_safe,
            "allowed": decision.allowed,
            "reason": decision.reason,
            "matched_scope": decision.matched_scope,
            "matched_entry_id": decision.matched_entry_id,
            "matched_path_prefix": decision.matched_path_prefix,
            "scheme": decision.scheme,
        }
        document = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action_id": action_id,
            "event": event,
            "occurred_at": utc_now(),
        }
        document.update(store_json_field({"details": details}, "details"))
        try:
            await self._audit_sink(document)
        except Exception:  # noqa: BLE001 — auditing must never break the call
            return

    async def missing_target(
        self,
        *,
        tenant_id: str,
        user_id: str,
        action_id: str,
        tool_or_capability: str,
    ) -> None:
        """Record an outbound attempt with no resolvable target URL."""
        decision = EgressDecision(allowed=False, domain="", reason="target_url_missing")
        try:
            await self.audit(
                decision,
                tenant_id=tenant_id,
                user_id=user_id,
                action_id=action_id,
                tool_or_capability=tool_or_capability,
                event_allowed=EGRESS_MISSING_TARGET_EVENT,
                event_denied=EGRESS_MISSING_TARGET_EVENT,
            )
        except Exception:  # noqa: BLE001
            return


# Process-wide singleton shared by the tool and browser call points so the
# snapshot cache is shared.
egress_guard = EgressGuard()


# ---------------------------------------------------------------------------
# Tool outbound URL resolution
# ---------------------------------------------------------------------------


def _sanitize_template_url(url: str) -> str:
    """Strip ``{placeholder}`` segments so a template host/path still resolves.

    A placeholder inside the host leaves an invalid host, which then fails
    normalization and therefore denies the call (fail-closed).
    """
    return _TEMPLATE_RE.sub("", url)


def resolve_tool_outbound_urls(tool_doc: dict[str, Any], arguments: Optional[dict[str, Any]] = None) -> list[str]:
    """Candidate outbound URLs for a tool document (http / mcp / plugin_gateway).

    ``mcp`` exposes ``endpoint``; ``http`` exposes ``url`` plus an optional
    ``gatewayUrl`` for the plugin-gateway execution mode. Candidates containing
    ``{placeholder}`` path segments are sanitized so their host is still judged.
    """
    config = tool_doc.get("config") or {}
    # external_tools 文档的规范字段是 ``type``（"http"/"mcp"）；保留 ``source_type``
    # 兼容旧形态。
    source_type = str(tool_doc.get("type") or tool_doc.get("source_type") or "")
    if source_type == "mcp":
        raw = [config.get("endpoint"), config.get("url")]
    else:
        raw = [config.get("url"), config.get("endpoint"), config.get("gatewayUrl")]
    results: list[str] = []
    for value in raw:
        if not value:
            continue
        text = str(value).strip()
        if not text:
            continue
        results.append(_sanitize_template_url(text) if "{" in text else text)
    return results


__all__ = [
    "DEFAULT_EGRESS_TIMEOUT_MS",
    "DEFAULT_SNAPSHOT_TTL_SECONDS",
    "EGRESS_ALLOWLIST_COLLECTION",
    "EGRESS_ALLOWED_EVENT",
    "EGRESS_AUDIT_COLLECTION",
    "EGRESS_DENIED_EVENT",
    "EGRESS_MISSING_TARGET_EVENT",
    "EgressDecision",
    "EgressEntry",
    "EgressGuard",
    "SCHEMES",
    "VALID_SCOPES",
    "egress_guard",
    "is_ip_literal",
    "matches_domain",
    "matches_path",
    "normalize_match_domain",
    "normalize_path_prefix",
    "normalize_url",
    "resolve_tool_outbound_urls",
    "strip_url_secrets",
]
