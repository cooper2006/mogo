"""004 FR-8: skill lifecycle events are audited on the 001 audit stream.

Regression guard for the 2026-10-03 audit finding: the four 004 skill endpoints
had **zero** audit wiring, so publish / install / share / revoke were untraceable.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.skill_lifecycle.audit import FR8_ACTIONS, record_skill_event


def test_all_fr8_actions_are_known() -> None:
    assert "skill.published" in FR8_ACTIONS
    assert "skill.installed" in FR8_ACTIONS
    assert "skill.shared" in FR8_ACTIONS
    assert "skill.share_redeemed" in FR8_ACTIONS
    assert "skill.share_revoked" in FR8_ACTIONS


def test_unknown_action_is_rejected(monkeypatch) -> None:
    """A mis-labelled event must not be silently dropped (011-style guard)."""
    captured: dict = {}

    async def _fake_record(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("app.governance.audit.record_position_policy_event", _fake_record)

    with pytest.raises(ValueError, match="unknown 004 FR-8 audit action"):
        asyncio.run(
            record_skill_event(
                tenant_id="m-1", user_id="u-1", action="skill.bogus", target="s-1"
            )
        )
    assert "action" not in captured or captured.get("action") != "skill.bogus"


def test_skill_event_lands_on_the_001_stream(monkeypatch) -> None:
    """The 004 helper writes through the 001 governance audit sink."""
    captured: dict = {}

    async def _fake_record(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("app.governance.audit.record_position_policy_event", _fake_record)

    asyncio.run(
        record_skill_event(
            tenant_id="m-1",
            user_id="u-1",
            action="skill.published",
            target="skill-9",
            details={"release_id": "rel-1", "version": "2.0.0"},
        )
    )
    assert captured["tenant_id"] == "m-1"
    assert captured["user_id"] == "u-1"
    assert captured["action"] == "skill.published"
    assert captured["target"] == "skill-9"
    assert captured["details"] == {"release_id": "rel-1", "version": "2.0.0"}
