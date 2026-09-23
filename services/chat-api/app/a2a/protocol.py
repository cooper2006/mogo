"""A2A JSON-RPC protocol shapes (012 FR-2 / FR-7 / FR-10).

Standard methods: ``message/send`` (dispatch), ``tasks/get`` (status),
``tasks/result`` (result). Errors follow the JSON-RPC spec; a MOVO gatekeeper
denial is mapped into the server-error range with the denial reason preserved
(FR-7) so callers can distinguish "rejected by governance" from other failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# A2A standard method names (FR-2).
METHOD_MESSAGE_SEND = "message/send"
METHOD_TASKS_GET = "tasks/get"
METHOD_TASKS_RESULT = "tasks/result"
SUPPORTED_METHODS = (METHOD_MESSAGE_SEND, METHOD_TASKS_GET, METHOD_TASKS_RESULT)

# JSON-RPC standard error codes.
ERROR_PARSE = -32700
ERROR_INVALID_REQUEST = -32600
ERROR_METHOD_NOT_FOUND = -32601
ERROR_INVALID_PARAMS = -32602
ERROR_INTERNAL = -32603
# Server-error range used for governance denials (FR-7).
ERROR_MOVO_DENIED = -32000

ERROR_CODES: dict[str, int] = {
    "parse_error": ERROR_PARSE,
    "invalid_request": ERROR_INVALID_REQUEST,
    "method_not_found": ERROR_METHOD_NOT_FOUND,
    "invalid_params": ERROR_INVALID_PARAMS,
    "internal_error": ERROR_INTERNAL,
    "movo_denied": ERROR_MOVO_DENIED,
}


class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JsonRpcRequest:
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    id: Any = None
    jsonrpc: str = "2.0"

    def validate(self) -> Optional["JsonRpcError"]:
        if self.jsonrpc != "2.0":
            return JsonRpcError(ERROR_INVALID_REQUEST, "jsonrpc must be '2.0'")
        if self.method not in SUPPORTED_METHODS:
            return JsonRpcError(ERROR_METHOD_NOT_FOUND, f"unsupported method: {self.method}")
        if not isinstance(self.params, dict):
            return JsonRpcError(ERROR_INVALID_PARAMS, "params must be an object")
        return None


@dataclass
class JsonRpcError:
    code: int
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data:
            payload["data"] = self.data
        return payload


@dataclass
class JsonRpcResponse:
    id: Any = None
    result: Optional[dict[str, Any]] = None
    error: Optional[JsonRpcError] = None
    jsonrpc: str = "2.0"

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            payload["error"] = self.error.as_dict()
        else:
            payload["result"] = self.result or {}
        return payload


def rpc_error_from_denial(*, layer: str, reason: str, status_code: Optional[int] = None) -> JsonRpcError:
    """Map a gatekeeper denial into a JSON-RPC error (FR-7)."""
    return JsonRpcError(
        ERROR_MOVO_DENIED,
        "调用被治理层拒绝",
        data={"layer": layer, "reason": reason, "statusCode": status_code},
    )


class TaskLifecycle:
    """Tracks task state and enforces ``task id`` idempotency (FR-10).

    Re-sending the same task id returns the existing task instead of executing it
    again.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}

    def submit(self, task_id: str, *, payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
        """Register a task; returns ``(task, created)``.

        ``created`` is False when the id already exists (idempotent replay).
        """
        existing = self._tasks.get(task_id)
        if existing is not None:
            return existing, False
        task = {
            "id": task_id,
            "state": TaskState.SUBMITTED.value,
            "payload": dict(payload or {}),
            "result": None,
            "error": None,
        }
        self._tasks[task_id] = task
        return task, True

    def get(self, task_id: str) -> Optional[dict[str, Any]]:
        return self._tasks.get(task_id)

    def set_state(self, task_id: str, state: str) -> Optional[dict[str, Any]]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task["state"] = state
        return task

    def complete(self, task_id: str, result: dict[str, Any]) -> Optional[dict[str, Any]]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task["state"] = TaskState.COMPLETED.value
        task["result"] = dict(result)
        return task

    def fail(self, task_id: str, error: JsonRpcError) -> Optional[dict[str, Any]]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task["state"] = TaskState.FAILED.value
        task["error"] = error.as_dict()
        return task

    def result(self, task_id: str) -> Optional[dict[str, Any]]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        return {
            "id": task["id"],
            "state": task["state"],
            "result": task.get("result"),
            "error": task.get("error"),
        }
