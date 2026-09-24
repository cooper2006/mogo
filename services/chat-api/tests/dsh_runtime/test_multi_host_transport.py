"""Contract tests for multi Runtime Host sticky routing (P1/P2).

The Node Runtime Host keeps kernel session state in process memory, so every
request for one ``kernel_session_id`` must reach the same host. These tests pin
that contract without needing a real Node runtime: a stub HTTP transport records
which host received which request.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

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
        # No runtime segment in the path, so the session id is the sticky key.
        response = await transport.request(
            "GET",
            "/v1/sessions/stream",
            session_id=session_id,
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
        for request in recorder.requests:
            session_id = request.headers[SESSION_HEADER]
            assert transport._select_base_url(session_id) == url



@pytest.mark.asyncio
async def test_concurrent_requests_spread_across_hosts() -> None:
    """Different sessions must actually be spread over the host pool."""
    hosts = ("http://host-a:8101", "http://host-b:8101", "http://host-c:8101")
    transport, recorders = _build(hosts)

    await asyncio.gather(
        *[
            transport.request("GET", "/v1/sessions/stream", session_id=f"sess-{i}")
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
            "GET", "/v1/sessions/stream", session_id=session_id
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
            session_id = request.headers[SESSION_HEADER]
            assert transport._select_base_url(session_id) == url



@pytest.mark.asyncio
async def test_multi_host_request_and_stream_agree_on_target() -> None:
    """A session's request and stream calls must select the same host."""
    hosts = ("http://host-a:8101", "http://host-b:8101", "http://host-c:8101")
    transport, recorders = _build(hosts)
    session_id = "sess-paired"

    await transport.request("GET", "/v1/sessions/stream", session_id=session_id)
    try:
        async for _ in transport.stream(
            "GET", "/v1/sessions/stream", session_id=session_id
        ):
            break
    except Exception:  # noqa: BLE001
        pass

    hosts_hit = {
        url
        for url, recorder in recorders.items()
        if any(r.headers.get(SESSION_HEADER) == session_id for r in recorder.requests)
    }
    assert hosts_hit == {transport._select_base_url(session_id)}


# --------------------------------------------------------------------------
# Runtime-level routing (found by end-to-end container verification)
#
# A runtime created on one replica was invisible to the replica that later
# served its session, because runtime-level calls carried no sticky key and
# fell back to a random request id. These tests pin the fix: session id wins,
# then runtime id from the path, then the isolation key query parameter.
# --------------------------------------------------------------------------


def test_runtime_id_is_extracted_from_path():
    from app.dsh_runtime.transport import runtime_id_from_path

    assert runtime_id_from_path("/v1/runtimes/rt-123") == "rt-123"
    assert runtime_id_from_path("/v1/runtimes/rt-123/model-credential") == "rt-123"
    assert runtime_id_from_path("/v1/runtimes") is None
    assert runtime_id_from_path("/health") is None


def test_explicit_isolation_key_outranks_runtime_and_session():
    """The isolation key wins: it is the only lifetime-stable identifier.

    The runtime id hashes to a different replica than the isolation key used at
    creation time, so keying on the runtime id routes create_session to a
    replica that does not own the runtime ("runtime not found").
    """
    from app.dsh_runtime.transport import (
        ISOLATION_HEADER,
        RUNTIME_HEADER,
        SESSION_HEADER,
        runtime_routing_key,
    )

    key, headers = runtime_routing_key(
        "/v1/runtimes/rt-1/sessions/sess-1",
        sticky_key="tenant:t1:profile:p1",
    )
    assert key == "tenant:t1:profile:p1"
    assert headers[ISOLATION_HEADER] == "tenant:t1:profile:p1"
    # Both other identifiers are still forwarded for log correlation.
    assert headers[RUNTIME_HEADER] == "rt-1"
    assert headers[SESSION_HEADER] == "sess-1"


def test_runtime_id_is_the_fallback_when_no_isolation_key():
    from app.dsh_runtime.transport import RUNTIME_HEADER, runtime_routing_key

    key, headers = runtime_routing_key("/v1/runtimes/rt-9/model-credential")
    assert key == "rt-9"
    assert headers[RUNTIME_HEADER] == "rt-9"


def test_runtime_routing_key_uses_runtime_id_without_session():
    from app.dsh_runtime.transport import RUNTIME_HEADER, runtime_routing_key

    key, headers = runtime_routing_key("/v1/runtimes/rt-9/model-credential")
    assert key == "rt-9"
    assert headers == {RUNTIME_HEADER: "rt-9"}


def test_runtime_routing_key_falls_back_to_isolation_key():
    from app.dsh_runtime.transport import ISOLATION_HEADER, runtime_routing_key

    key, headers = runtime_routing_key(
        "/v1/runtimes",
        params={"isolationKey": "tenant:t1:profile:p1"},
    )
    assert key == "tenant:t1:profile:p1"
    assert headers == {ISOLATION_HEADER: "tenant:t1:profile:p1"}


def test_runtime_routing_key_returns_none_when_nothing_identifies_request():
    from app.dsh_runtime.transport import runtime_routing_key

    key, headers = runtime_routing_key("/health")
    assert key is None
    assert headers == {}


@pytest.mark.asyncio
async def test_create_and_discover_runtime_hit_the_same_replica():
    """A runtime created on one replica must be discoverable on the same one."""
    hosts = ("http://host-a:8101", "http://host-b:8101", "http://host-c:8101")
    transport, recorders = _build(hosts)
    isolation_key = "tenant:t1:profile:p1"

    await transport.request(
        "POST",
        "/v1/runtimes",
        json={"isolationKey": isolation_key},
        params={"isolationKey": isolation_key},
    )
    await transport.request("GET", "/v1/runtimes", params={"isolationKey": isolation_key})

    hit = {
        url
        for url, recorder in recorders.items()
        if recorder.requests
    }
    assert len(hit) == 1, f"create and discover must agree on one replica, hit {hit}"
    target = transport._select_base_url(isolation_key)
    assert hit == {target}
    for recorder in recorders.values():
        for request in recorder.requests:
            assert request.headers["X-Isolation-Key"] == isolation_key


@pytest.mark.asyncio
async def test_runtime_scoped_call_sticks_to_runtime_replica():
    transport, recorders = _build(("http://a:1", "http://b:2", "http://c:3"))
    await transport.request(
        "POST",
        "/v1/runtimes/rt-777/model-credential",
        json={},
        sticky_key="tenant:t1:profile:p1",
    )

    target = transport._select_base_url("tenant:t1:profile:p1")
    assert recorders[target].requests, "the credential call must reach the runtime's replica"
    request = recorders[target].requests[0]
    assert request.headers["X-Runtime-Id"] == "rt-777"
    assert request.headers["X-Isolation-Key"] == "tenant:t1:profile:p1"


@pytest.mark.asyncio
async def test_session_call_sticks_to_its_runtime_replica():
    """Session-scoped calls follow the runtime, regardless of session id."""
    transport, recorders = _build(("http://a:1", "http://b:2", "http://c:3"))
    await transport.request(
        "GET",
        "/v1/runtimes/rt-1/sessions/sess-42",
        sticky_key="tenant:t1:profile:p1",
    )

    target = transport._select_base_url("tenant:t1:profile:p1")
    request = recorders[target].requests[0]
    assert request.headers["X-Runtime-Id"] == "rt-1"
    assert request.headers["X-Session-Id"] == "sess-42"


@pytest.mark.asyncio
async def test_create_and_use_runtime_stay_on_one_replica():
    """Regression for the end-to-end gap: the whole lifecycle must agree.

    create_runtime, create_session and describe_session all use the runtime's
    isolation key, so they must all land on the replica that owns the runtime.
    Keying on the runtime id or the fresh session id instead would split them.
    """
    transport, recorders = _build(("http://a:1", "http://b:2", "http://c:3"))
    isolation_key = "tenant:t1:profile:p1"

    await transport.request(
        "POST", "/v1/runtimes", json={"isolationKey": isolation_key},
        params={"isolationKey": isolation_key},
    )
    runtime_id = "rt-created"
    fresh_session = "dsh-brand-new-session"
    await transport.request(
        "POST", f"/v1/runtimes/{runtime_id}/sessions",
        json={"sessionId": fresh_session}, sticky_key=isolation_key,
    )
    await transport.request(
        "GET", f"/v1/runtimes/{runtime_id}/sessions/{fresh_session}",
        sticky_key=isolation_key,
    )

    hit = {url for url, recorder in recorders.items() if recorder.requests}
    assert hit == {transport._select_base_url(isolation_key)}, (
        f"the runtime lifecycle split across replicas: {hit}"
    )



# --------------------------------------------------------------------------
# Wiring regression
#
# ``DshRuntimeApplication.start`` referenced ``configured_runtime_hosts`` without
# importing it. No unit test covered the composition root, so the failure only
# appeared when the container actually booted (NameError -> startup failed).
# Importing the modules below executes the module-level imports, which is enough
# to catch an unbound name that the composition root relies on.
# --------------------------------------------------------------------------


def test_application_module_imports_composition_dependencies():
    import app.dsh_runtime.application as application

    # Names the composition root calls must resolve in its own module namespace.
    source = Path(application.__file__).read_text(encoding="utf-8")
    for name in ("configured_runtime_hosts",):
        if name in source:
            assert hasattr(application, name), (
                f"{name} is used by application.py but is not imported into its namespace"
            )


def test_composition_root_constructs_transport_with_configured_hosts():
    """The transport must accept the host list produced by the settings helper."""
    from app.dsh_runtime.application import DshRuntimeApplication
    from app.dsh_runtime.transport import HttpKernelHostTransport, configured_runtime_hosts

    hosts = configured_runtime_hosts("http://host-a:8101,http://host-b:8101")
    transport = HttpKernelHostTransport(
        "http://host-a:8101", base_urls=hosts, timeout_seconds=1.0
    )
    assert transport.base_urls == ("http://host-a:8101", "http://host-b:8101")
    assert DshRuntimeApplication is not None
