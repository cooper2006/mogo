"""038 egress sandbox — outbound allowlist guard unit tests (chat-api).

Pure unit tests: a fake snapshot loader and a fake audit sink are injected, so
nothing here touches Mongo. These lock the fail-closed semantics of the runtime
half of 038 (deny by default, three-layer union allowlist, SSRF pre-rejects,
redirect-landing verdict).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.enterprise_capabilities.tools.egress_guard import (
    EgressEntry,
    EgressGuard,
    is_ip_literal,
    matches_domain,
    matches_path,
    normalize_match_domain,
    normalize_url,
    resolve_tool_outbound_urls,
    strip_url_secrets,
)


# ---------------------------------------------------------------------------
# Pure normalization / matching helpers
# ---------------------------------------------------------------------------


def test_normalize_url_lowercases_and_strips_trailing_dot_and_default_port() -> None:
    assert normalize_url("https://api.Example.COM:443/v1/data") == ("https", "api.example.com", 443, "/v1/data")
    assert normalize_url("http://EXAMPLE.COM/") == ("http", "example.com", 80, "/")
    assert normalize_url("https://example.com.") == ("https", "example.com", 443, "/")


def test_normalize_url_idna_encodes_unicode_host() -> None:
    scheme, host, _port, _path = normalize_url("https://例え.テスト/x")
    assert host == "xn--r8jz45g.xn--zckzah"


def test_normalize_url_rejects_non_http_and_non_absolute() -> None:
    with pytest.raises(ValueError):
        normalize_url("ftp://example.com/a")
    with pytest.raises(ValueError):
        normalize_url("javascript:alert(1)")
    with pytest.raises(ValueError):
        normalize_url("example.com/x")  # no scheme


def test_is_ip_literal_covers_loopback_and_private() -> None:
    assert is_ip_literal("127.0.0.1")
    assert is_ip_literal("10.0.0.5")
    assert is_ip_literal("192.168.1.1")
    assert is_ip_literal("169.254.1.1")
    assert is_ip_literal("::1")
    assert not is_ip_literal("example.com")


def test_matches_domain_suffix_semantics() -> None:
    assert matches_domain("example.com", "example.com")
    assert matches_domain("api.example.com", "example.com")
    assert matches_domain("a.b.example.com", "example.com")
    assert not matches_domain("badexample.com", "example.com")
    assert not matches_domain("notexample.com", "example.com")


def test_matches_path_prefix_semantics() -> None:
    assert matches_path("/v1/data", "v1")  # prefix + subpath
    assert matches_path("/v1", "v1")  # exact prefix
    assert not matches_path("/v12/data", "v1")  # not a segment boundary
    assert not matches_path("/api/v1", "v1")
    assert matches_path("/anything", "")  # no prefix = any path


def test_strip_url_secrets_removes_query_and_userinfo() -> None:
    safe = strip_url_secrets("https://user:pw@api.example.com/v1?key=secret#frag")
    assert safe == "https://api.example.com/v1"
    assert "secret" not in safe


# ---------------------------------------------------------------------------
# Decision engine — fail-closed semantics
# ---------------------------------------------------------------------------


def _loader(entries):
    async def load(_tenant_id: str):
        return entries

    return load


class _Sink:
    def __init__(self) -> None:
        self.documents: list[dict] = []

    async def __call__(self, document: dict) -> None:
        self.documents.append(document)


def _guard(entries, sink=None, **kwargs):
    return EgressGuard(_loader(entries), sink or _Sink(), timeout_ms=500, **kwargs)


def test_allows_exact_and_subdomain_match() -> None:
    entries = [EgressEntry(entry_id="e1", scope="tenant", match_domain="example.com")]
    guard = _guard(entries)
    assert asyncio.run(guard.check(url="https://api.example.com/v1", tenant_id="t1")).allowed
    assert asyncio.run(guard.check(url="https://example.com/", tenant_id="t1")).allowed


def test_denies_by_default_when_no_match() -> None:
    guard = _guard([EgressEntry(entry_id="e1", scope="tenant", match_domain="other.com")])
    decision = asyncio.run(guard.check(url="https://api.example.com/v1", tenant_id="t1"))
    assert not decision.allowed
    assert decision.reason == "no-allowlist-match"


def test_denies_with_empty_allowlist() -> None:
    guard = _guard([])
    decision = asyncio.run(guard.check(url="https://example.com/", tenant_id="t1"))
    assert not decision.allowed
    assert decision.reason == "no-allowlist-match"


def test_platform_entry_applies_to_any_tenant() -> None:
    entries = [EgressEntry(entry_id="p1", scope="platform", match_domain="openai.com", tenant_id="")]
    guard = _guard(entries)
    assert asyncio.run(guard.check(url="https://api.openai.com/v1", tenant_id="t9")).allowed


def test_tool_scope_is_scoped_to_its_tool() -> None:
    entries = [EgressEntry(entry_id="e1", scope="tool", match_domain="example.com", tenant_id="t1", tool_id="tw-1")]
    guard = _guard(entries)
    # 其他工具的请求不受该 tool 条目放行。
    decision = asyncio.run(guard.check(url="https://example.com/", tenant_id="t1", tool_id="tw-2"))
    assert not decision.allowed


def test_path_prefix_limits_match() -> None:
    entries = [EgressEntry(entry_id="e1", scope="tenant", match_domain="example.com", path_prefix="v1")]
    guard = _guard(entries)
    assert asyncio.run(guard.check(url="https://example.com/v1/data", tenant_id="t1")).allowed
    assert not asyncio.run(guard.check(url="https://example.com/v2/data", tenant_id="t1")).allowed


def test_ip_literal_and_bad_scheme_denied_up_front() -> None:
    # 即使 allowlist 里有该域名，IP 字面量与非 http(s) scheme 也先拒绝（SSRF 防护）。
    entries = [EgressEntry(entry_id="e1", scope="tenant", match_domain="127.0.0.1")]
    guard = _guard(entries)
    decision = asyncio.run(guard.check(url="http://127.0.0.1:8080/", tenant_id="t1"))
    assert not decision.allowed
    assert decision.reason == "ip-literal-not-allowed (SSRF guard)"


def test_loader_failure_denies() -> None:
    async def boom(_tenant_id: str):
        raise RuntimeError("db down")

    guard = EgressGuard(boom, _Sink(), timeout_ms=500)
    decision = asyncio.run(guard.check(url="https://example.com/", tenant_id="t1"))
    assert not decision.allowed


def test_timeout_denies() -> None:
    async def hang(_tenant_id: str):
        await asyncio.sleep(5)

    guard = EgressGuard(hang, _Sink(), timeout_ms=50)
    decision = asyncio.run(guard.check(url="https://example.com/", tenant_id="t1"))
    assert not decision.allowed
    assert decision.reason == "egress-check-timeout"


def test_remote_sandbox_is_reserved_and_denied() -> None:
    guard = _guard([EgressEntry(entry_id="e1", scope="tenant", match_domain="example.com")])
    decision = asyncio.run(
        guard.check(url="https://example.com/", tenant_id="t1", execution_location="remote_sandbox")
    )
    assert not decision.allowed
    assert decision.reason == "remote_sandbox-not-implemented (038)"


def test_decide_urls_denies_when_any_candidate_denied() -> None:
    entries = [EgressEntry(entry_id="e1", scope="tenant", match_domain="example.com")]
    guard = _guard(entries)
    decision = asyncio.run(
        guard.decide_urls(["https://example.com/a", "https://evil.com/b"], tenant_id="t1")
    )
    assert not decision.allowed
    assert decision.domain == "evil.com"


def test_decide_urls_allows_when_all_allowed() -> None:
    entries = [EgressEntry(entry_id="e1", scope="tenant", match_domain="example.com")]
    guard = _guard(entries)
    decision = asyncio.run(guard.decide_urls(["https://example.com/a", "https://sub.example.com/b"], tenant_id="t1"))
    assert decision.allowed


def test_decide_urls_no_candidates_denies() -> None:
    guard = _guard([])
    decision = asyncio.run(guard.decide_urls([], tenant_id="t1"))
    assert not decision.allowed
    assert decision.reason == "no-outbound-url"


def test_snapshot_cache_respects_ttl_and_invalidate() -> None:
    calls = {"n": 0}

    def loader(entries):
        async def load(_tenant_id: str):
            calls["n"] += 1
            return entries

        return load

    guard = EgressGuard(loader([]), _Sink(), timeout_ms=500, ttl=60.0)
    assert not asyncio.run(guard.check(url="https://example.com/", tenant_id="t1")).allowed
    assert not asyncio.run(guard.check(url="https://example.com/", tenant_id="t1")).allowed
    assert calls["n"] == 1  # 第二次命中缓存，未再加载
    guard.invalidate(tenant_id="t1")
    assert not asyncio.run(guard.check(url="https://example.com/", tenant_id="t1")).allowed
    assert calls["n"] == 2  # invalidate 后重新加载


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def test_audit_writes_allowed_and_denied_events() -> None:
    sink = _Sink()
    guard = _guard([EgressEntry(entry_id="e1", scope="tenant", match_domain="example.com")], sink)
    allowed = asyncio.run(guard.check(url="https://example.com/v1", tenant_id="t1", tool_id="tw-1"))
    asyncio.run(
        guard.audit(
            allowed, tenant_id="t1", user_id="u1", action_id="egress-allowed", tool_or_capability="tool.http"
        )
    )
    denied = asyncio.run(guard.check(url="https://evil.com/", tenant_id="t1"))
    asyncio.run(
        guard.audit(
            denied, tenant_id="t1", user_id="u1", action_id="egress-denied", tool_or_capability="tool.http"
        )
    )
    events = [doc["event"] for doc in sink.documents]
    assert "egress.allowed" in events
    assert "egress.denied" in events
    details = json.loads(sink.documents[0]["details_json"])
    assert details["matched_scope"] == "tenant"
    assert details["url_safe"] == "https://example.com/v1"
    # 审计记录里不允许出现查询串。
    assert "?" not in details["url_safe"]


def test_audit_never_raises_on_sink_failure() -> None:
    async def broken_sink(_document: dict) -> None:
        raise RuntimeError("audit db down")

    guard = EgressGuard(_loader([]), broken_sink, timeout_ms=500)
    decision = asyncio.run(guard.check(url="https://example.com/", tenant_id="t1"))
    # 审计失败不得打断调用。
    asyncio.run(
        guard.audit(decision, tenant_id="t1", user_id="u1", action_id="a1", tool_or_capability="tool.http")
    )


def test_missing_target_records_dedicated_event() -> None:
    sink = _Sink()
    guard = _guard([], sink)
    asyncio.run(guard.missing_target(tenant_id="t1", user_id="u1", action_id="a1", tool_or_capability="browser.read"))
    assert sink.documents[0]["event"] == "egress.target_url_missing"


# ---------------------------------------------------------------------------
# Tool outbound URL resolution
# ---------------------------------------------------------------------------


def test_resolve_http_tool_urls() -> None:
    doc = {"source_type": "http", "config": {"url": "https://api.example.com/v1/data"}}
    assert resolve_tool_outbound_urls(doc) == ["https://api.example.com/v1/data"]


def test_resolve_mcp_endpoint() -> None:
    doc = {"source_type": "mcp", "config": {"endpoint": "https://mcp.example.com/sse"}}
    assert resolve_tool_outbound_urls(doc) == ["https://mcp.example.com/sse"]


def test_resolve_plugin_gateway_url_and_strip_template() -> None:
    doc = {"source_type": "http", "config": {"url": "https://api.example.com/{resource}/get", "gatewayUrl": "https://gw.example.com/v1"}}
    urls = resolve_tool_outbound_urls(doc)
    assert "https://gw.example.com/v1" in urls
    assert any("{" not in u for u in urls)


def test_resolve_tool_with_no_url_yields_empty() -> None:
    doc = {"source_type": "http", "config": {}}
    assert resolve_tool_outbound_urls(doc) == []
