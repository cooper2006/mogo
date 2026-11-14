"""Promotion approval state machine (017 T035).

A normal end-user may *request* that one of their memories be promoted to the
``department`` scope. The request enters ``pending`` and a ``full_access_admin``
*approves* (which performs the actual promotion) or *rejects* it.

This is the ``portal_requests``-style state machine the design (§9.1) calls for:
the old flow promoted directly under ``full_access_admin`` with no queue, so the
admin "pending" counter was always zero. Now the queue is real and every
transition is audited.

States
------
* ``none``     — no request made / admin direct promote (terminal-ish).
* ``pending``  — user requested; awaiting admin decision.
* ``approved`` — admin approved; memory is now ``department``-scoped (terminal).
* ``rejected`` — admin rejected; may be re-requested (→ ``pending``).

Transitions
-----------
* ``request``  : ``none`` | ``rejected`` → ``pending``   (memory owner only)
* ``approve``  : ``pending`` → ``approved``              (full_access_admin)
* ``reject``   : ``pending`` → ``rejected``              (full_access_admin)

Only the ``approve`` transition mutates ``scope``/``department_id`` (it delegates
to :func:`app.memory.scope.promote_to_department`).
"""

from __future__ import annotations

import time
from typing import Any

from app.memory.scope import (
    Memory,
    MemoryAccessError,
    PROMOTION_STATUS_APPROVED,
    PROMOTION_STATUS_NONE,
    PROMOTION_STATUS_PENDING,
    PROMOTION_STATUS_REJECTED,
    promote_to_department,
)

# (from_state) -> {action: to_state}
_PROMOTION_TRANSITIONS: dict[str, dict[str, str]] = {
    PROMOTION_STATUS_NONE: {"request": PROMOTION_STATUS_PENDING},
    PROMOTION_STATUS_PENDING: {
        "approve": PROMOTION_STATUS_APPROVED,
        "reject": PROMOTION_STATUS_REJECTED,
    },
    PROMOTION_STATUS_REJECTED: {"request": PROMOTION_STATUS_PENDING},
    PROMOTION_STATUS_APPROVED: {},  # terminal
}


def _field(memory: Memory | dict[str, Any], name: str) -> Any:
    if isinstance(memory, dict):
        return memory.get(name)
    return getattr(memory, name, None)


def _set(memory: Memory, **fields: Any) -> None:
    for key, value in fields.items():
        setattr(memory, key, value)


def promotion_status_of(memory: Memory | dict[str, Any]) -> str:
    return str(_field(memory, "promotion_status") or PROMOTION_STATUS_NONE)


def can_transition(memory: Memory | dict[str, Any], action: str) -> bool:
    return action in _PROMOTION_TRANSITIONS.get(promotion_status_of(memory), {})


def next_state(memory: Memory | dict[str, Any], action: str) -> str:
    """Return the target state for ``action`` or raise for an illegal transition."""
    current = promotion_status_of(memory)
    table = _PROMOTION_TRANSITIONS.get(current)
    if not table or action not in table:
        raise MemoryAccessError(
            f"promotion transition '{action}' not allowed from '{current}'"
        )
    return table[action]


def request_promotion(
    memory: Memory,
    *,
    viewer: Any,
    department_id: str,
    reason: str = "",
) -> Memory:
    """Owner requests promotion to ``department`` (→ ``pending``).

    Authorization: the caller must own the memory and the target department must
    be visible to them (a user can only request promotion into a department they
    belong to / descend from, per D3 visibility).
    """
    if not viewer.is_valid:
        raise MemoryAccessError("invalid viewer context")
    if str(getattr(memory, "owner_id", "")) != viewer.user_id:
        raise MemoryAccessError("only the memory owner may request promotion")
    if not department_id or not viewer.department_is_visible(department_id):
        raise MemoryAccessError(f"department {department_id!r} is not visible to the caller")
    if not can_transition(memory, "request"):
        raise MemoryAccessError(
            f"cannot request promotion from status '{promotion_status_of(memory)}'"
        )
    _set(
        memory,
        promotion_status=PROMOTION_STATUS_PENDING,
        pending_department_id=department_id,
        promotion_requested_by=viewer.user_id,
        promotion_requested_at=time.time(),
        promotion_reason=str(reason or ""),
        promotion_resolved_by="",
        promotion_resolved_at=0.0,
    )
    return memory


def approve_promotion(
    memory: Memory,
    *,
    viewer: Any,
    department_id: str = "",
) -> Memory:
    """Admin approves a pending request → promotes to ``department`` (→ ``approved``)."""
    if not viewer.is_valid:
        raise MemoryAccessError("invalid viewer context")
    if not getattr(viewer, "is_full_access_admin", False):
        raise MemoryAccessError("full_access_admin required to approve promotion")
    if promotion_status_of(memory) != PROMOTION_STATUS_PENDING:
        raise MemoryAccessError("promotion is not pending")
    target = department_id or str(getattr(memory, "pending_department_id", "") or "")
    if not target:
        raise MemoryAccessError("no target department for promotion")
    # Delegates scope/department validation + audit to the existing promote path.
    promoted = promote_to_department(memory, viewer=viewer, department_id=target)
    _set(
        promoted,
        promotion_status=PROMOTION_STATUS_APPROVED,
        promotion_resolved_by=viewer.user_id,
        promotion_resolved_at=time.time(),
    )
    return promoted


def reject_promotion(
    memory: Memory,
    *,
    viewer: Any,
    reason: str = "",
) -> Memory:
    """Admin rejects a pending request (→ ``rejected``). Scope is unchanged."""
    if not viewer.is_valid:
        raise MemoryAccessError("invalid viewer context")
    if not getattr(viewer, "is_full_access_admin", False):
        raise MemoryAccessError("full_access_admin required to reject promotion")
    if promotion_status_of(memory) != PROMOTION_STATUS_PENDING:
        raise MemoryAccessError("promotion is not pending")
    _set(
        memory,
        promotion_status=PROMOTION_STATUS_REJECTED,
        promotion_resolved_by=viewer.user_id,
        promotion_resolved_at=time.time(),
        promotion_reason=str(reason or ""),
    )
    return memory


__all__ = [
    "PROMOTION_STATUS_APPROVED",
    "PROMOTION_STATUS_NONE",
    "PROMOTION_STATUS_PENDING",
    "PROMOTION_STATUS_REJECTED",
    "approve_promotion",
    "can_transition",
    "next_state",
    "promotion_status_of",
    "reject_promotion",
    "request_promotion",
]
