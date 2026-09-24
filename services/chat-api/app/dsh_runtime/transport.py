"""HTTP transport used by ASKAI to call the Node DSH Runtime Host.

The transport supports one or more Runtime Host instances. A single instance is
the default and behaves exactly like the historical single-URL client. With
several instances the transport routes every request with a **sticky** hash over
``kernel_session_id`` so that all traffic for one kernel session lands on the
same host: the Node host keeps session state in process memory, therefore a
``resume_session`` / event-stream call must reach the instance that owns it.

Two pieces cooperate to make the routing decision:

1. ``X-Session-Id`` is sent on every request that belongs to a kernel session, so
   an upstream load balancer (nginx ``hash $http_x_session_id consistent``) can
   pin the connection without inspecting the body.
2. ``_select_base_url`` applies the same stable hash in-process, which keeps the
   behaviour correct even when no LB is deployed (for example a caller that is
   configured with a comma-separated host list directly).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
import hashlib
import json as jsonlib
import re
from typing import Any, Protocol

import httpx

from .errors import DshProtocolError, DshTransportError

# ``/v1/runtimes/{runtime_id}/sessions/{session_id}/...`` and its nested paths.
# Session-scoped calls are the ones that require sticky routing.
_SESSION_PATH = re.compile(r"/sessions/(?P<session_id>[^/]+)")

SESSION_HEADER = "X-Session-Id"


class KernelHostTransport(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]: ...

    def stream(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]: ...


def normalize_base_urls(
    base_url: str | None = None,
    base_urls: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Return the de-duplicated, order-stable list of Runtime Host base URLs.

    A plain ``base_url`` is accepted for backwards compatibility; ``base_urls``
    (or the comma separated ``DSH_RUNTIME_HOSTS_URL`` setting) takes precedence
    when it carries at least one usable entry.
    """
    candidates: list[str] = []
    for raw in base_urls or ():
        candidates.append(str(raw))
    if not candidates and base_url:
        candidates.append(str(base_url))
    seen: list[str] = []
    for raw in candidates:
        for piece in str(raw).split(","):
            value = piece.strip().rstrip("/")
            if value and value not in seen:
                seen.append(value)
    if not seen:
        raise DshTransportError("no DSH Runtime Host URL is configured")
    return tuple(seen)


def session_id_from_path(path: str) -> str | None:
    """Extract the kernel session id from a Runtime Host path, when present."""
    match = _SESSION_PATH.search(path or "")
    if match is None:
        return None
    value = match.group("session_id").strip()
    return value or None


def configured_runtime_hosts(hosts_url: str | None) -> tuple[str, ...]:
    """Split a comma separated ``DSH_RUNTIME_HOSTS_URL`` into host URLs.

    Returns an empty tuple when nothing usable is configured, which makes the
    transport fall back to the single ``DSH_RUNTIME_HOST_URL``.
    """
    values: list[str] = []
    for piece in str(hosts_url or "").split(","):
        value = piece.strip()
        if value and value not in values:
            values.append(value)
    return tuple(values)


def sticky_index(key: str, host_count: int) -> int:
    """Map a sticky key to a host index with a stable, seed-independent hash.

    ``hashlib`` is used instead of the builtin ``hash`` because the builtin is
    randomised per process (``PYTHONHASHSEED``), which would send the same
    session to a different host after a restart.
    """
    if host_count <= 1:
        return 0
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % host_count


class HttpKernelHostTransport:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        base_urls: Sequence[str] | None = None,
        timeout_seconds: float = 10.0,
        access_token: str = "",
    ) -> None:
        self._base_urls = normalize_base_urls(base_url, base_urls)
        headers = {"Authorization": f"Bearer {access_token}"} if access_token else None
        self._clients = [
            httpx.AsyncClient(
                base_url=url,
                timeout=httpx.Timeout(timeout_seconds),
                headers=headers,
            )
            for url in self._base_urls
        ]

    @property
    def base_urls(self) -> tuple[str, ...]:
        """The configured Runtime Host URLs, in routing order."""
        return self._base_urls

    def _select_base_url(self, sticky_key: str | None) -> str:
        """Return the host that owns ``sticky_key`` (round-robin when absent)."""
        if sticky_key is None:
            return self._base_urls[0]
        return self._base_urls[sticky_index(sticky_key, len(self._base_urls))]

    def _select_client(self, sticky_key: str | None) -> httpx.AsyncClient:
        index = 0 if sticky_key is None else sticky_index(sticky_key, len(self._clients))
        return self._clients[index]

    @staticmethod
    def _routing_key(path: str, session_id: str | None) -> str | None:
        return session_id or session_id_from_path(path)

    @staticmethod
    def _request_headers(
        routing_key: str | None,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str] | None:
        headers = dict(extra or {})
        if routing_key:
            headers[SESSION_HEADER] = routing_key
        return headers or None

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        routing_key = self._routing_key(path, session_id)
        client = self._select_client(routing_key)
        try:
            response = await client.request(
                method,
                path,
                json=json,
                params=params,
                headers=self._request_headers(routing_key),
            )
        except httpx.HTTPError as exc:
            raise DshTransportError(f"DSH Runtime Host is unavailable: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise DshProtocolError("DSH Runtime Host returned non-JSON data") from exc
        if not isinstance(payload, dict):
            raise DshProtocolError("DSH Runtime Host returned a non-object response")
        if response.is_error:
            error = payload.get("error")
            message = error.get("message") if isinstance(error, dict) else response.reason_phrase
            raise DshTransportError(f"DSH Runtime Host rejected the request: {message}")
        return payload

    async def stream(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        routing_key = self._routing_key(path, session_id)
        client = self._select_client(routing_key)
        try:
            async with client.stream(
                method,
                path,
                params=params,
                headers=self._request_headers(routing_key),
            ) as response:
                if response.is_error:
                    body = await response.aread()
                    try:
                        payload = jsonlib.loads(body)
                    except (TypeError, ValueError):
                        payload = {}
                    error = payload.get("error") if isinstance(payload, dict) else None
                    message = error.get("message") if isinstance(error, dict) else response.reason_phrase
                    raise DshTransportError(f"DSH Runtime Host rejected the stream: {message}")
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        payload = jsonlib.loads(line)
                    except ValueError as exc:
                        raise DshProtocolError("DSH Runtime Host returned malformed stream data") from exc
                    if not isinstance(payload, dict):
                        raise DshProtocolError("DSH Runtime Host streamed a non-object event")
                    yield payload
        except DshProtocolError:
            raise
        except DshTransportError:
            raise
        except httpx.HTTPError as exc:
            raise DshTransportError(f"DSH Runtime Host stream is unavailable: {exc}") from exc

    async def close(self) -> None:
        for client in self._clients:
            await client.aclose()
