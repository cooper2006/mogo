"""Ownership probe and affinity cache (§12.4 option B).

A Runtime Host keeps sessions in process memory, so a session lives on exactly
one replica. These tests pin the contract that lets chat-api *find* that replica
instead of resuming blind and failing with "session is not live".
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.dsh_runtime.session_affinity import SessionAffinityCache
from app.dsh_runtime.transport import HttpKernelHostTransport


class _OwnerTransport(httpx.AsyncBaseTransport):
    """Answers the ownership probe the way a real replica would."""

    def __init__(self, host: str, *, owns: set[str], instance_id: str) -> None:
        self.host = host
        self.owns = owns
        self.instance_id = instance_id
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        await asyncio.sleep(0)
        # /v1/runtimes/{rid}/sessions/{sid}/owner
        parts = [p for p in request.url.path.split("/") if p]
        session_id = parts[-2] if len(parts) >= 2 else ""
        return httpx.Response(200, json={
            "owned": session_id in self.owns,
            "instanceId": self.instance_id,
            "runtimeId": parts[2] if len(parts) > 2 else "",
            "sessionId": session_id,
        })


def _build(replica_urls: tuple[str, ...], owners: dict[str, str | None]):
    """Transport whose replicas each own the sessions listed in ``owners``."""
    recorders: dict[str, _OwnerTransport] = {}

    def _factory(url: str) -> httpx.AsyncBaseTransport:
        instance_id = url.rsplit("//", 1)[-1].split(":")[0]
        owned = {s for s, inst in owners.items() if inst == instance_id}
        recorder = _OwnerTransport(url, owns=owned, instance_id=instance_id)
        recorders[url] = recorder
        return recorder

    transport = HttpKernelHostTransport(
        base_url=replica_urls[0],
        replica_urls=replica_urls,
        transport_factory=_factory,
    )
    return transport, recorders


@pytest.mark.asyncio
async def test_probe_reports_the_replica_that_owns_the_session():
    hosts = ("http://host-a:8101", "http://host-b:8101", "http://host-c:8101")
    transport, recorders = _build(hosts, {"sess-1": "host-b"})

    result = await transport.probe_session_owner(runtime_id="rt-1", session_id="sess-1")

    assert result["found"] is True
    assert result["instance_id"] == "host-b"
    assert result["url"] == "http://host-b:8101"
    # Every replica is asked, because the whole point is to bypass the router.
    assert all(recorder.requests for recorder in recorders.values())


@pytest.mark.asyncio
async def test_probe_asks_replicas_directly_not_through_the_base_url():
    """Behind a sticky LB the base URL is the LB; probes must skip it."""
    hosts = ("http://host-a:8101", "http://host-b:8101")
    recorded: list[str] = []

    def _factory(url: str) -> httpx.AsyncBaseTransport:
        class _Recorder(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                recorded.append(url)
                return httpx.Response(200, json={"owned": False, "instanceId": url})

        return _Recorder()

    transport = HttpKernelHostTransport(
        base_url="http://lb:8101",     # business traffic goes here
        replica_urls=hosts,            # probes go here instead
        transport_factory=_factory,
    )
    assert transport.base_urls == ("http://lb:8101",)
    assert transport.replica_urls == hosts

    await transport.probe_session_owner(runtime_id="rt-1", session_id="sess-1")

    assert sorted(recorded) == sorted(hosts)
    assert "http://lb:8101" not in recorded


@pytest.mark.asyncio
async def test_probe_reports_not_found_when_no_replica_owns_the_session():
    hosts = ("http://host-a:8101", "http://host-b:8101")
    transport, _ = _build(hosts, {})

    result = await transport.probe_session_owner(runtime_id="rt-1", session_id="gone")

    assert result["found"] is False
    assert result["instance_id"] is None


@pytest.mark.asyncio
async def test_probe_tolerates_a_replica_that_errors():
    """One unreachable replica must not hide the owner on another."""
    def _factory(url: str) -> httpx.AsyncBaseTransport:
        class _Flaky(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                if "host-a" in url:
                    raise httpx.ConnectError("boom", request=request)
                return httpx.Response(200, json={"owned": True, "instanceId": "host-b"})

        return _Flaky()

    transport = HttpKernelHostTransport(
        base_url="http://host-a:8101",
        replica_urls=("http://host-a:8101", "http://host-b:8101"),
        transport_factory=_factory,
    )

    result = await transport.probe_session_owner(runtime_id="rt-1", session_id="sess-1")

    assert result["found"] is True
    assert result["instance_id"] == "host-b"
    errors = [item for item in result["probed"] if item["error"]]
    assert errors and errors[0]["url"] == "http://host-a:8101"


def test_affinity_cache_degrades_to_memory_without_redis():
    cache = SessionAffinityCache(None)
    assert cache.backend == "memory"

    cache.set("sess-1", "host-b")
    assert cache.get("sess-1") == "host-b"

    cache.forget("sess-1")
    assert cache.get("sess-1") is None


def test_affinity_cache_survives_an_unreachable_redis():
    """A bad Redis URL must degrade, never raise: the cache is an optimisation."""
    cache = SessionAffinityCache("redis://127.0.0.1:1/0", ttl_seconds=60)
    assert cache.backend == "memory"

    cache.set("sess-1", "host-b")
    assert cache.get("sess-1") == "host-b"


def test_affinity_cache_ignores_empty_values():
    cache = SessionAffinityCache(None)
    cache.set("", "host-b")
    cache.set("sess-1", "")
    assert cache.get("") is None
    assert cache.get("sess-1") is None
