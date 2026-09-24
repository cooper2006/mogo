"""Contract tests for multi Runtime Host sticky routing (P1/P2).

The Node Runtime Host keeps kernel session state in process memory, so every
request for one ``kernel_session_id`` must reach the same host. These tests pin
that contract without needing a real Node runtime: a stub HTTP transport records
which host received which request.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.dsh_runtime.transport import (
    SESSION_HEADER,
    HttpKernelHostTransport,
    configured_runtime_hosts,
    normalize_base_urls,
    session_id_from_path,
    sticky_index,
)

class _RecordingTransport(httpx.AsyncBaseTransport):
    """Records every request and replies with a minimal JSON object."""

    def __init__(self, host: str) -> None:
        self.host = host
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        # Yield so concurrent callers actually interleave.
        await asyncio.sleep(0)
        return httpx.Response(200, json={"ok": True, "host": self.host})


def _build(hosts: tuple[str, ...]) -> tuple[HttpKernelHostTransport, dict[str, _RecordingTransport]]:
    transport = HttpKernelHostTransport(base_url=hosts[0], base_urls=hosts)
    recorders: dict[str, _RecordingTransport] = {}
    for client, url in zip(transport._clients, hosts):
        recorder = _RecordingTransport(url)
        recorders[url] = recorder
        # Swap the real transport for the recording stub, keeping base_url.
        client._transport = recorder
    return transport, recorders


# --------------------------------------------------------------------------
# Sticky hashing
# --------------------------------------------------------------------------


def test_sticky_index_is_stable_across_calls() -> None:
    """The same key must always map to the same host index."""
    first = sticky_index("sess-stable", 3)
    assert all(sticky_index("sess-stable", 3) == first for _ in range(50))


def test_sticky_index_does_not_depend_on_process_hash_seed() -> None:
    """Routing must not rely on the randomised builtin ``hash``."""
    # A literal expectation: sha256("sess-stable") % 3, computed independently.
    import hashlib

    expected = int.from_bytes(hashlib.sha256(b"sess-stable").digest()[:8], "big") % 3
    assert sticky_index("sess-stable", 3) == expected


def test_sticky_index_distributes_keys_across_hosts() -> None:
    """Distribution must not collapse onto a single host."""
    buckets = {sticky_index(f"sess-{i}", 3) for i in range(200)}
    assert buckets == {0, 1, 2}


def test_sticky_index_single_host_is_always_zero() -> None:
    assert sticky_index("anything", 1) == 0


# --------------------------------------------------------------------------
# Backwards compatibility with the single-URL configuration
# --------------------------------------------------------------------------



@pytest.mark.asyncio
async def test_single_url_behaves_like_single_host_client() -> None:
    """With one configured host every request lands there, even session calls."""
    transport, recorders = _build(("http://host-a:8101",))
    await transport.request("GET", "/v1/runtimes/r1/sessions/s1")
    await transport.request("GET", "/health")
    assert transport.base_urls == ("http://host-a:8101",)
    assert len(recorders["http://host-a:8101"].requests) == 2


def test_normalize_base_urls_prefers_list_and_dedupes() -> None:
    assert normalize_base_urls(
        "http://legacy:1",
        ("http://a:1", "http://b:2", "http://a:1"),
    ) == ("http://a:1", "http://b:2")


def test_normalize_base_urls_falls_back_to_single_url() -> None:
    assert normalize_base_urls("http://legacy:1", ()) == ("http://legacy:1",)


def test_configured_runtime_hosts_parses_comma_separated_value() -> None:
    assert configured_runtime_hosts("http://a:1, http://b:2 ,http://a:1") == (
        "http://a:1",
        "http://b:2",
    )


def test_configured_runtime_hosts_empty_falls_back() -> None:
    assert configured_runtime_hosts("") == ()
    assert configured_runtime_hosts(None) == ()


def test_session_id_from_path_extracts_nested_session_id() -> None:
    assert session_id_from_path("/v1/runtimes/r1/sessions/sess-abc") == "sess-abc"
    assert session_id_from_path("/v1/runtimes/r1/sessions/sess-abc/event-stream") == "sess-abc"
    assert session_id_from_path("/v1/runtimes/r1") is None
    assert session_id_from_path("/health") is None


# --------------------------------------------------------------------------
# X-Session-Id propagation
# --------------------------------------------------------------------------



@pytest.mark.asyncio
async def test_session_header_is_sent_for_session_scoped_calls() -> None:
    transport, recorders = _build(("http://a:1", "http://b:2", "http://c:3"))
    session_id = "dsh-session-1"
    await transport.request("GET", f"/v1/runtimes/r1/sessions/{session_id}")
    routers = [r for r in recorders.values() if r.requests]
    assert len(routers) == 1, "a session call must reach exactly one host"
    assert routers[0].requests[0].headers[SESSION_HEADER] == session_id



@pytest.mark.asyncio
async def test_session_header_is_absent_for_sessionless_calls() -> None:
    transport, recorders = _build(("http://a:1", "http://b:2"))
    await transport.request("GET", "/health")
    sent = [r for r in recorders.values() if r.requests]
    assert len(sent) == 1
    assert SESSION_HEADER not in sent[0].requests[0].headers



@pytest.mark.asyncio
async def test_explicit_session_id_overrides_path_extraction() -> None:
    transport, recorders = _build(("http://a:1", "http://b:2", "http://c:3"))
    await transport.request(
        "GET",
        "/v1/runtimes/r1",
        session_id="explicit-session",
    )
    target = transport._select_base_url("explicit-session")
    assert recorders[target].requests[0].headers[SESSION_HEADER] == "explicit-session"


# --------------------------------------------------------------------------
# P2: concurrent contract test — 50 concurrent requests across 3 hosts
# --------------------------------------------------------------------------



@pytest.mark.asyncio
async def test_concurrent_requests_keep_session_affinity() -> None:
    """50 concurrent calls per session must all hit that session's host."""
    hosts = ("http://host-a:8101", "http://host-b:8101", "http://host-c:8101")
    transport, recorders = _build(hosts)
    sessions = [f"sess-{i}" for i in range(10)]

    async def call(session_id: str) -> str:
        response = await transport.request(
            "GET",
            f"/v1/runtimes/r1/sessions/{session_id}/event-stream",
        )
        return str(response["host"])

    results = await asyncio.gather(
        *[call(session_id) for session_id in sessions for _ in range(5)]
    )

    # Every request of one session must land on the same host.
    per_session: dict[str, set[str]] = {}
    for session_id, host in zip([s for s in sessions for _ in range(5)], results):
        per_session.setdefault(session_id, set()).add(host)
    for session_id, hosts_seen in per_session.items():
        assert len(hosts_seen) == 1, f"{session_id} was split across {hosts_seen}"

    # And each host records exactly the sessions routed to it.
    for url, recorder in recorders.items():
        recorded_sessions = {
            session_id_from_path(str(request.url.path)) for request in recorder.requests
        }
        assert len(recorded_sessions) <= len(sessions)
        for session_id in recorded_sessions:
            assert transport._select_base_url(session_id) == url



@pytest.mark.asyncio
async def test_concurrent_requests_spread_across_hosts() -> None:
    """Different sessions must actually be spread over the host pool."""
    hosts = ("http://host-a:8101", "http://host-b:8101", "http://host-c:8101")
    transport, recorders = _build(hosts)

    await asyncio.gather(
        *[
            transport.request("GET", f"/v1/runtimes/r1/sessions/sess-{i}")
            for i in range(60)
        ]
    )

    used = {url for url, recorder in recorders.items() if recorder.requests}
    assert len(used) == len(hosts), f"expected all hosts used, got {used}"



@pytest.mark.asyncio
async def test_stream_requests_follow_the_same_sticky_routing() -> None:
    """Event streams must be pinned too, otherwise resume misses host memory."""
    hosts = ("http://host-a:8101", "http://host-b:8101")
    transport, recorders = _build(hosts)

    async def consume(session_id: str) -> None:
        async for _ in transport.stream(
            "GET", f"/v1/runtimes/r1/sessions/{session_id}/event-stream"
        ):
            break

    # Streaming from a host that returns a non-stream body yields nothing; the
    # assertion is about which host received the request.
    for session_id in ("sess-x", "sess-y", "sess-z"):
        try:
            await consume(session_id)
        except Exception:  # noqa: BLE001 - body shape is irrelevant here
            pass

    for url, recorder in recorders.items():
        for request in recorder.requests:
            session_id = session_id_from_path(str(request.url.path))
            assert transport._select_base_url(session_id) == url
            assert request.headers[SESSION_HEADER] == session_id



@pytest.mark.asyncio
async def test_multi_host_request_and_stream_agree_on_target() -> None:
    """A session's request and stream calls must select the same host."""
    hosts = ("http://host-a:8101", "http://host-b:8101", "http://host-c:8101")
    transport, recorders = _build(hosts)
    session_id = "sess-paired"

    await transport.request("GET", f"/v1/runtimes/r1/sessions/{session_id}")
    try:
        async for _ in transport.stream(
            "GET", f"/v1/runtimes/r1/sessions/{session_id}/event-stream"
        ):
            break
    except Exception:  # noqa: BLE001
        pass

    hosts_hit = {
        url
        for url, recorder in recorders.items()
        if any(
            session_id_from_path(str(r.url.path)) == session_id for r in recorder.requests
        )
    }
    assert hosts_hit == {transport._select_base_url(session_id)}
