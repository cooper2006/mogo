from __future__ import annotations

import asyncio
from pathlib import Path

from .harness import ConversationHarness, DeterministicBridge, event_text
from .scenarios import SCENARIOS, SKILL_SCENARIO


def test_real_dsh_conversation_capability_matrix(tmp_path: Path) -> None:
    asyncio.run(_run_capability_matrix(tmp_path))


def test_real_dsh_manual_skill_and_followup_semantics(tmp_path: Path) -> None:
    asyncio.run(_run_skill_turns(tmp_path))


def test_real_dsh_direct_answer_and_multiturn_history(tmp_path: Path) -> None:
    asyncio.run(_run_direct_and_multiturn(tmp_path))


async def _run_capability_matrix(tmp_path: Path) -> None:
    harness = ConversationHarness(tmp_path)
    await harness.start()
    try:
        for index, scenario in enumerate(SCENARIOS):
            session_id = await harness.create_session(f"conversation-{scenario.id}")
            before = len(DeterministicBridge.tool_calls)
            events = await harness.turn(
                session_id,
                f"request-{index}",
                f"REGRESSION_SCENARIO:{scenario.id}\n{scenario.prompt}",
            )
            calls = DeterministicBridge.tool_calls[before:]
            assert len(calls) == 1, scenario.id
            assert calls[0]["toolName"] == scenario.gateway_tool_name
            assert calls[0]["arguments"] == scenario.arguments
            assert any(event.type == "tool.call.started" for event in events)
            assert any(event.type == "tool.call.completed" for event in events)
            assert any(event.type == "agent.message.completed" for event in events)
            if scenario.id != "content_generation":
                assert f"SCENARIO_OK:{scenario.id}" in event_text(events)
    finally:
        await harness.stop()


async def _run_skill_turns(tmp_path: Path) -> None:
    harness = ConversationHarness(tmp_path)
    await harness.start()
    try:
        session_id = await harness.create_session("conversation-dynamic-skill")
        first_events = await harness.turn(
            session_id,
            "request-skill-1",
            f"REGRESSION_SCENARIO:{SKILL_SCENARIO.id}\n{SKILL_SCENARIO.prompt}",
            selected_skill_id="skill-regression-source",
        )
        assert [call["toolName"] for call in DeterministicBridge.tool_calls] == [
            SKILL_SCENARIO.gateway_tool_name
        ]
        selected = [event for event in first_events if event.type == "skill.selected"]
        assert len(selected) == 1
        assert selected[0].payload["selectionMode"] == "manual"
        assert "SCENARIO_OK:dynamic_skill" in event_text(first_events)

        calls_before = len(DeterministicBridge.tool_calls)
        second_events = await harness.turn(
            session_id,
            "request-skill-2",
            "REGRESSION_SCENARIO:skill_followup\n继续上一轮，但本轮不重新选择 Skill。",
        )
        assert len(DeterministicBridge.tool_calls) == calls_before
        assert not any(event.type == "skill.selected" for event in second_events)
        assert "SCENARIO_OK:skill_followup" in event_text(second_events)
    finally:
        await harness.stop()


async def _run_direct_and_multiturn(tmp_path: Path) -> None:
    harness = ConversationHarness(tmp_path)
    await harness.start()
    try:
        direct_session = await harness.create_session("conversation-direct-answer")
        direct_events = await harness.turn(
            direct_session,
            "request-direct",
            "REGRESSION_SCENARIO:direct_answer\n请直接回答，不使用工具。",
        )
        assert "SCENARIO_OK:direct_answer" in event_text(direct_events)

        history_session = await harness.create_session("conversation-history")
        seed_events = await harness.turn(
            history_session,
            "request-context-1",
            "REGRESSION_SCENARIO:context_seed\n请记住本轮标记。",
        )
        assert "SCENARIO_OK:context_seed" in event_text(seed_events)
        followup_events = await harness.turn(
            history_session,
            "request-context-2",
            "REGRESSION_SCENARIO:context_followup\n请根据上一轮标记回答。",
        )
        assert "SCENARIO_OK:context_followup" in event_text(followup_events)
        assert DeterministicBridge.tool_calls == []
    finally:
        await harness.stop()
