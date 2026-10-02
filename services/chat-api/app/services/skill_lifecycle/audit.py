"""004 FR-8: skill lifecycle audit (001 audit stream, wired 2026-10-03).

Every 004 lifecycle write event lands on the 001 governance audit stream
(``position_role_audit_logs``) with the FR-8 fields: operator / time / resource /
event type / release or version reference. Before 2026-10-03 these endpoints had
**zero** audit wiring (001 audit report), so a skill publish / install / share /
revoke could not be traced at all.

Events (``skill.<verb>``):
* ``skill.published``  — publish created a release
* ``skill.installed``  — ZIP install (personal or organization)
* ``skill.shared``     — a share was created
* ``skill.share_redeemed`` — a share token was installed
* ``skill.share_revoked``  — a share was revoked
"""

from __future__ import annotations

from typing import Any

FR8_ACTIONS = (
    "skill.published",
    "skill.installed",
    "skill.shared",
    "skill.share_redeemed",
    "skill.share_revoked",
)


async def record_skill_event(
    *,
    main_id: str,
    user_id: str,
    action: str,
    target: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Write one 004 lifecycle event onto the 001 governance audit stream.

    ``action`` must be one of :data:`FR8_ACTIONS`; an unknown action raises so a
    mis-labelled event is not silently dropped (mirrors 011's feature-audit guard).
    """
    if action not in FR8_ACTIONS:
        raise ValueError(f"unknown 004 FR-8 audit action: {action!r}")

    from app.governance.audit import record_position_policy_event

    await record_position_policy_event(
        tenant_id=str(main_id or ""),
        user_id=str(user_id or ""),
        action=action,
        target=str(target or ""),
        details=dict(details or {}),
    )
