"""Outbound A2A client (012 T009 / US2 / FR-3).

MOVO acts as an A2A client calling an external Agent: JSON-RPC
``message/send`` with a 30s default timeout, failover to a configured backup
agent, and retry reusing the 007 backoff primitives (no duplicated backoff).
Errors are mapped to JSON-RPC error codes so callers can distinguish a
governance denial from a transport failure (US2 acceptance: 错误码映射).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from app.a2a.protocol import (
    ERROR_INTERNAL,
    ERROR_MOVO_DENIED,
    JsonRpcError,
    JsonRpcResponse,
    METHOD_MESSAGE_SEND,
)
from app.services.dag.retry import RetryPolicy

DEFAULT_TIMEOUT_SECONDS = 30.0


async def run_with_retry(
    run_one: Callable[[], Awaitable[Any]],
    *,
    policy: RetryPolicy,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> tuple[Any, int, Optional[BaseException]]:
    """Run ``run_one`` with the policy's retry budget (012 T009 / FR-3).

    Returns ``(result, attempts, last_error)``. When the last attempt failed,
    ``result`` is None. ``sleep`` is injectable for tests; defaults to a real
    async backoff sleep (the model-level backoff itself is delegated to the
    007 resilience scheduler — FR-3 / 010 T017 分层不重复).
    """
    attempts = 0
    last_error: Optional[BaseException] = None
    while attempts < policy.max_attempts:
        attempts += 1
        try:
            result = await run_one()
        except Exception as error:  # noqa: BLE001 — retry until exhausted
            last_error = error
            if attempts >= policy.max_attempts:
                break
            delay = policy.delay_for(attempts)
            if delay > 0:
                if sleep is not None:
                    await sleep(delay)
                else:
                    await asyncio.sleep(delay)
            continue
        # The transport succeeded but the response carried an error.
        if isinstance(result, JsonRpcResponse) and result.error is not None:
            return result, attempts, result.error
        return result, attempts, None
    return None, attempts, last_error


@dataclass
class OutboundCall:
    """One outbound A2A invocation (012 US2)."""
    agent_name: str
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    task_id: str = ""
    response: Optional[JsonRpcResponse] = None
    error: Optional[JsonRpcError] = None
    attempts: int = 0
    failed_over_to: str = ""

    def is_ok(self) -> bool:
        return self.error is None

    def as_document(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "agent": self.agent_name,
            "method": self.method,
            "task_id": self.task_id,
            "ok": self.is_ok(),
            "attempts": self.attempts,
            "failed_over_to": self.failed_over_to,
        }
        if self.error is not None:
            doc["error"] = self.error.as_dict()
        if self.response is not None:
            doc["result"] = self.response.result or {}
        return doc


@dataclass
class ClientConfig:
    """Outbound client config (012 T009): timeout + failover + retry policy."""
    primary_agent: str
    backup_agents: tuple[str, ...] = ()
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    retry: RetryPolicy = field(
        default_factory=lambda: RetryPolicy(max_attempts=3, base_seconds=2.0, factor=2.0, cap_seconds=60.0)
    )
    delegate_model_backoff: bool = True  # 复用 007 退避，不重复（FR-3）


# A transport callable: (agent_name, method, params, timeout) -> JsonRpcResponse.
# Real HTTP/JSON-RPC transport plugs in here; tests use an in-memory one.
Transport = Callable[[str, str, dict[str, Any], float], Awaitable[JsonRpcResponse]]


class A2AClient:
    """Outbound A2A client with timeout + failover + 007 retry (012 T009)."""

    def __init__(self, transport: Transport, config: Optional[ClientConfig] = None) -> None:
        self._transport = transport
        self._config = config or ClientConfig(primary_agent="default")

    async def send(
        self,
        params: dict[str, Any],
        *,
        task_id: str = "",
        method: str = METHOD_MESSAGE_SEND,
    ) -> OutboundCall:
        """Invoke the primary agent, failing over to backups on transport error."""
        agents = [self._config.primary_agent, *self._config.backup_agents]
        call = OutboundCall(agent_name=agents[0], method=method, params=dict(params), task_id=task_id)

        for index, agent in enumerate(agents):
            async def _invoke(agent_name: str = agent) -> JsonRpcResponse:
                return await self._transport(agent_name, method, dict(params), self._config.timeout_seconds)

            result, attempts, last_error = await run_with_retry(
                _invoke,
                policy=self._config.retry,
            )
            call.attempts += attempts
            if index > 0:
                call.failed_over_to = agent

            # A governance denial carried on the response stops failover:
            # surface the JSON-RPC error code immediately, no retry, no backup
            # (012 US2 错误码映射).
            if isinstance(last_error, JsonRpcError) and last_error.code == ERROR_MOVO_DENIED:
                call.error = last_error
                call.agent_name = agent
                if result is not None:
                    call.response = result
                return call

            if result is not None:
                call.response = result
                call.agent_name = agent
                # Any JSON-RPC error carried on the response is the terminal outcome.
                if isinstance(result, JsonRpcResponse) and result.error is not None:
                    call.error = result.error
                return call

        # All agents exhausted: record the last transport error as a JSON-RPC internal error.
        call.error = JsonRpcError(ERROR_INTERNAL, "all outbound agents exhausted")
        return call


def map_error_code(exc: Exception) -> int:
    """Map an outbound exception to a JSON-RPC error code (US2 错误码映射)."""
    if isinstance(exc, JsonRpcError):
        return exc.code
    if isinstance(exc, PermissionError):
        return ERROR_MOVO_DENIED
    return ERROR_INTERNAL


__all__ = [
    "A2AClient",
    "ClientConfig",
    "OutboundCall",
    "Transport",
    "DEFAULT_TIMEOUT_SECONDS",
    "map_error_code",
    "run_with_retry",
]
