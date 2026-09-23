"""A2A Agent Gateway (feature 012).

Exposes MOVO agents over the A2A protocol and calls external A2A agents:

* **AgentCard** generation / registration (FR-1) with the A2A standard fields;
* a **JSON-RPC** task surface: ``message/send`` / ``tasks/get`` / ``tasks/result``
  (FR-2), with ``task id`` idempotency (FR-10);
* error mapping to JSON-RPC codes, including gatekeeper denials (FR-7).

This package holds the dependency-light core (AgentCard model + JSON-RPC protocol
shapes + idempotency), so it is unit-testable without the runtime or a database.
"""

from __future__ import annotations

from .agent_card import AgentCard, AgentSkill, build_agent_card, parse_agent_card
from .protocol import (
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    TaskLifecycle,
    ERROR_CODES,
    rpc_error_from_denial,
)

__all__ = [
    "AgentCard",
    "AgentSkill",
    "build_agent_card",
    "parse_agent_card",
    "JsonRpcRequest",
    "JsonRpcResponse",
    "JsonRpcError",
    "TaskLifecycle",
    "ERROR_CODES",
    "rpc_error_from_denial",
]
