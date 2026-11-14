"""team 编排模式契约测试（052 T017 / T018）。

覆盖：拆解指派 / 黑板版本与命名空间 / 验收 accept-rework / 轮次钳制 / 达上限
fail-closed / 单成员失败与重指派 / 领导失败 / 分派表非法 fail-closed /
接管挂起-决策覆盖审计（050 语义）/ 子节点原子性（044 R-16）。全部使用
transport-agnostic 的 mock runner（与 050 测试同风格），不触库。
"""

from __future__ import annotations

import pytest

from app.orchestration.graph import Node
from app.orchestration.team import (
    DEFAULT_MAX_REVIEW_ROUNDS,
    EVENT_TAKEOVER,
    NODE_MODE_TEAM,
    TeamError,
    TeamPlan,
    ReviewVerdict,
    clamp_reassign,
    clamp_review_rounds,
    run_team,
    _should_take_over,
)


# --- 纯函数：钳制与解析 ------------------------------------------------


def test_clamp_review_rounds_bounds():
    assert clamp_review_rounds(0) == 1
    assert clamp_review_rounds(7) == 5
    assert clamp_review_rounds(3) == 3
    assert clamp_review_rounds("bad") == DEFAULT_MAX_REVIEW_ROUNDS


def test_clamp_reassign_bounds():
    assert clamp_reassign(0) == 1
    assert clamp_reassign(20) == 10
    assert clamp_reassign(3) == 3


def test_team_plan_rejects_unknown_member():
    with pytest.raises(TeamError, match="不存在"):
        TeamPlan.from_output({"assignments": {"m3": {"task": "x"}}}, member_ids=["m1"])


def test_team_plan_empty_fails_closed():
    with pytest.raises(TeamError, match="为空"):
        TeamPlan.from_output({}, member_ids=["m1"])


def test_review_verdict_requires_accept_or_rework():
    with pytest.raises(TeamError, match="无效"):
        ReviewVerdict.from_output({"verdict": "maybe"}, member_ids=["m1"])


def test_review_verdict_rework_unknown_target():
    with pytest.raises(TeamError, match="不存在"):
        ReviewVerdict.from_output({"verdict": "rework", "target_member": "m9"}, member_ids=["m1"])


# --- run_team：拆解指派 + 黑板 ------------------------------------------


async def _leader_decompose(node, ctx):
    return {"assignments": {"m1": {"task": "a"}, "m2": {"task": "b"}}}


async def _member_echo(node, ctx):
    return {"member": node.id, "task": (node.payload or {}).get("task"), "output": f"out:{node.id}"}


async def _leader_accept(node, ctx):
    return {"verdict": "accept"}


def _combined_runner(plan=None, verdict=None, member=_member_echo):
    """Leader 返回分派表/判定，成员返回产出（同 runner 双职责）。"""

    async def runner(node, ctx):
        if node.id == "leader":
            if verdict is not None and "review" in ctx:
                return verdict
            if plan is not None:
                return plan
            return await _leader_decompose(node, ctx)
        return await member(node, ctx)

    return runner


async def _event_sink(events):
    async def emit(payload):
        events.append(payload)
    return emit


def _members():
    return [Node(id="m1", mode=NODE_MODE_TEAM), Node(id="m2", mode=NODE_MODE_TEAM)]


def test_run_team_decompose_execute_blackboard():
    async def scenario():
        events = []
        result = await run_team(
            Node(id="team", mode=NODE_MODE_TEAM),
            _combined_runner(verdict={"verdict": "accept"}),
            context={},
            member_nodes=_members(),
            leader_node=Node(id="leader", mode=NODE_MODE_TEAM),
            event=await _event_sink(events),
        )
        assert result.ok, result.reason
        # 黑板含两成员各自的作者前缀条目（命名空间隔离）。
        keys = [b["key"] for b in result.blackboard]
        assert any("m1:" in k for k in keys)
        assert any("m2:" in k for k in keys)
        # 各成员执行了自己的子任务。
        assert result.output["m1"]["task"] == "a"
        assert result.output["m2"]["task"] == "b"
        # 事件可还原：拆解 + 成员开始/完成 + 黑板写入。
        names = [e["event"] for e in events]
        assert "team.decomposed" in names
        assert "team.blackboard.write" in names
    asyncio_run(scenario)


def test_run_team_rework_loop_and_cap():
    """验收循环：首轮 rework → 次轮 accept → 完成；黑板两个版本。"""
    async def scenario():
        calls = {"leader": 0, "m1": 0}

        async def leader(node, ctx):
            calls["leader"] += 1
            if calls["leader"] == 1:
                return {"assignments": {"m1": {"task": "a"}}}
            if calls["leader"] == 2:
                return {"verdict": "rework", "opinion": "重写", "target_member": "m1"}
            return {"verdict": "accept"}

        async def member(node, ctx):
            calls["m1"] += 1
            return {"output": f"v{calls['m1']}", "opinion": (node.payload or {}).get("review_opinion")}

        async def runner(node, ctx):
            if node.id == "leader":
                return await leader(node, ctx)
            return await member(node, ctx)

        result = await run_team(
            Node(id="team", mode=NODE_MODE_TEAM),
            runner,
            context={},
            member_nodes=[Node(id="m1", mode=NODE_MODE_TEAM)],
            leader_node=Node(id="leader", mode=NODE_MODE_TEAM),
            max_review_rounds=3,
        )
        assert result.ok, result.reason
        # rework 意见传到重做成员，黑板两个版本，旧版本保留。
        assert result.output["m1"]["output"] == "v2"
        assert result.output["m1"]["opinion"] == "重写"
        m1_versions = [b for b in result.blackboard if b["author"] == "m1"]
        assert len(m1_versions) == 2
        assert [b["version"] for b in m1_versions] == [1, 2]
        # 验收记录可查：首轮 rework。
        assert result.rounds[0]["verdict"] == "rework"
        assert result.rounds[1]["verdict"] == "accept"
    asyncio_run(scenario)


def test_run_team_reaches_cap_fails_closed():
    """领导持续 rework → 达上限团队失败（不无限循环）。"""
    async def scenario():
        async def leader(node, ctx):
            if "review" in ctx:
                return {"verdict": "rework", "opinion": "继续"}
            return {"assignments": {"m1": {"task": "a"}}}

        async def member(node, ctx):
            return {"output": "x"}

        async def runner(node, ctx):
            if node.id == "leader":
                return await leader(node, ctx)
            return await member(node, ctx)

        result = await run_team(
            Node(id="team", mode=NODE_MODE_TEAM),
            runner,
            context={},
            member_nodes=[Node(id="m1", mode=NODE_MODE_TEAM)],
            leader_node=Node(id="leader", mode=NODE_MODE_TEAM),
            max_review_rounds=2,
        )
        assert not result.ok
        assert "上限" in result.reason
        assert len(result.rounds) == 2
    asyncio_run(scenario)


def test_run_team_leader_failure_fails_team():
    async def scenario():
        async def leader(node, ctx):
            raise RuntimeError("领导崩了")

        async def member(node, ctx):
            return {"output": "x"}

        result = await run_team(
            Node(id="team", mode=NODE_MODE_TEAM),
            leader,  # leader 抛错 → 拆解失败 → 团队失败
            context={},
            member_nodes=[Node(id="m1", mode=NODE_MODE_TEAM)],
            leader_node=Node(id="leader", mode=NODE_MODE_TEAM),
        )
        assert not result.ok
        assert "领导" in result.reason
    asyncio_run(scenario)


def test_run_team_member_failure_isolated_reassign():
    """单成员失败不拖垮其它成员；重指派计数受上限约束。"""
    async def scenario():
        async def member(node, ctx):
            if node.id == "m1":
                raise RuntimeError("m1 失败")
            return {"output": "ok"}

        runner = _combined_runner(
            plan={"assignments": {"m1": {"task": "a"}, "m2": {"task": "b"}}},
            verdict={"verdict": "accept"},
            member=member,
        )
        result = await run_team(
            Node(id="team", mode=NODE_MODE_TEAM),
            runner,
            context={},
            member_nodes=[Node(id="m1", mode=NODE_MODE_TEAM), Node(id="m2", mode=NODE_MODE_TEAM)],
            leader_node=Node(id="leader", mode=NODE_MODE_TEAM),
            max_review_rounds=1,
            max_reassign=1,
        )
        # m1 失败数 1 未超上限（1），团队继续；m2 产出可用。
        assert result.ok, result.reason
        assert "m2" in result.output
    asyncio_run(scenario)


def test_run_team_member_failure_exceeds_reassign_cap():
    async def scenario():
        async def member(node, ctx):
            raise RuntimeError("失败")

        runner = _combined_runner(
            plan={"assignments": {"m1": {"task": "a"}, "m2": {"task": "b"}}},
            verdict={"verdict": "accept"},
            member=member,
        )
        result = await run_team(
            Node(id="team", mode=NODE_MODE_TEAM),
            runner,
            context={},
            member_nodes=[Node(id="m1", mode=NODE_MODE_TEAM), Node(id="m2", mode=NODE_MODE_TEAM)],
            leader_node=Node(id="leader", mode=NODE_MODE_TEAM),
            max_review_rounds=1,
            max_reassign=1,
        )
        assert not result.ok
        assert "重指派上限" in result.reason
    asyncio_run(scenario)


def test_run_team_no_members_fails():
    async def scenario():
        with pytest.raises(TeamError, match="成员"):
            await run_team(
                Node(id="team", mode=NODE_MODE_TEAM),
                _member_echo,
                context={},
                member_nodes=[],
                leader_node=Node(id="leader", mode=NODE_MODE_TEAM),
            )
    asyncio_run(scenario)


# --- 子节点原子性（044 R-16）：team 作为 graph 子节点 -----------------


def test_team_node_atomic_success_or_failure():
    """team 子节点对外表现为一次原子成功/失败。"""
    async def scenario():
        result = await run_team(
            Node(id="team-child", mode=NODE_MODE_TEAM),
            _combined_runner(
                plan={"assignments": {"m1": {"task": "a"}}},
                verdict={"verdict": "accept"},
            ),
            context={},
            member_nodes=[Node(id="m1", mode=NODE_MODE_TEAM)],
            leader_node=Node(id="leader", mode=NODE_MODE_TEAM),
        )
        payload = result.as_payload()
        assert payload["ok"] is True
        assert payload["team_id"] == "team-child"
        assert "blackboard" in payload
        assert "rounds" in payload
        assert "state" in payload
    asyncio_run(scenario)


# --- 接管（052 FR-006 / T015，050 human_approval 语义） ---------------


def test_run_team_takeover_on_rework_human_accept():
    """接管点 on_rework 命中 → approval_hook 被调 + 审计事件 + 人工 accept 覆盖。"""
    async def scenario():
        events = []
        human_calls = []

        async def approval(node, ctx, info):
            human_calls.append(info)
            return {"verdict": "accept", "approver": "reviewer", "reason": "我审过"}

        async def leader(node, ctx):
            if "review" in ctx:
                return {"verdict": "rework", "opinion": "再改", "target_member": "m1"}
            return {"assignments": {"m1": {"task": "a"}}}

        async def runner(node, ctx):
            if node.id == "leader":
                return await leader(node, ctx)
            return await _member_echo(node, ctx)

        result = await run_team(
            Node(id="team", mode=NODE_MODE_TEAM),
            runner,
            context={},
            member_nodes=[Node(id="m1", mode=NODE_MODE_TEAM)],
            leader_node=Node(id="leader", mode=NODE_MODE_TEAM),
            event=await _event_sink(events),
            takeover={"trigger": "on_rework", "approver": "reviewer"},
            approval_hook=approval,
        )
        assert result.ok, result.reason
        # 人工 accept 覆盖领导 rework → 团队完成，未走成员重做。
        assert result.state["takeover"] is True
        # 接管决策进审计（SC-005）。
        names = [e["event"] for e in events]
        assert EVENT_TAKEOVER in names
        takeover_event = next(e for e in events if e["event"] == EVENT_TAKEOVER)
        assert takeover_event["decision"] == "accept"
        assert takeover_event["approver"] == "reviewer"
        # 接管轮次入 round log，标注 takeover。
        assert any(r.get("takeover") for r in result.rounds)
        # hook 收到完整上下文（触发点/轮次/被覆盖判定/产出）。
        assert human_calls
        assert human_calls[0]["takeover"]["trigger"] == "on_rework"
        assert human_calls[0]["verdict"]["verdict"] == "rework"
    asyncio_run(scenario)


def test_run_team_takeover_human_terminate_fails():
    """人工 terminate → 团队 fail + 审计含接管终止。"""
    async def scenario():
        events = []

        async def approval(node, ctx, info):
            return {"verdict": "terminate", "approver": "admin", "reason": "方向错了"}

        result = await run_team(
            Node(id="team", mode=NODE_MODE_TEAM),
            _combined_runner(verdict={"verdict": "rework", "opinion": "再改"}),
            context={},
            member_nodes=_members(),
            leader_node=Node(id="leader", mode=NODE_MODE_TEAM),
            event=await _event_sink(events),
            takeover={"trigger": "manual", "approver": "admin"},
            approval_hook=approval,
        )
        assert not result.ok
        assert "人工接管终止" in result.reason
        assert "方向错了" in result.reason
        takeover_event = next(e for e in events if e["event"] == EVENT_TAKEOVER)
        assert takeover_event["decision"] == "terminate"
        assert takeover_event["approver"] == "admin"
    asyncio_run(scenario)


def test_run_team_takeover_no_hook_ignored():
    """无 approval_hook（050 未接）→ 忽略接管点，走领导判定（soft dependency）。"""
    async def scenario():
        result = await run_team(
            Node(id="team", mode=NODE_MODE_TEAM),
            _combined_runner(verdict={"verdict": "accept"}),
            context={},
            member_nodes=_members(),
            leader_node=Node(id="leader", mode=NODE_MODE_TEAM),
            takeover={"trigger": "manual", "approver": "reviewer"},
            approval_hook=None,
        )
        # 无 hook：接管声明被忽略，团队按领导 accept 正常完成。
        assert result.ok, result.reason
        assert result.state["takeover"] is False
    asyncio_run(scenario)


def test_run_team_takeover_trigger_predicates():
    """触发谓词：manual 恒命中 / on_rework 仅 rework / on_round_cap 仅末轮+rework。"""
    # manual 恒触发。
    assert _should_take_over({"trigger": "manual"}, ReviewVerdict("accept"), 1, 3) is True
    assert _should_take_over({"trigger": "manual"}, ReviewVerdict("rework"), 2, 3) is True
    # on_rework：仅 rework 判定。
    assert _should_take_over({"trigger": "on_rework"}, ReviewVerdict("rework"), 1, 3) is True
    assert _should_take_over({"trigger": "on_rework"}, ReviewVerdict("accept"), 1, 3) is False
    # on_round_cap：仅末轮且 rework。
    assert _should_take_over({"trigger": "on_round_cap"}, ReviewVerdict("rework"), 3, 3) is True
    assert _should_take_over({"trigger": "on_round_cap"}, ReviewVerdict("rework"), 2, 3) is False
    assert _should_take_over({"trigger": "on_round_cap"}, ReviewVerdict("accept"), 3, 3) is False
    # 无声明 / 未知 trigger：不触发。
    assert _should_take_over(None, ReviewVerdict("rework"), 1, 3) is False
    assert _should_take_over({"trigger": "unknown"}, ReviewVerdict("rework"), 1, 3) is False


# --- 辅助 -------------------------------------------------------------


def asyncio_run(coro):
    import asyncio
    asyncio.run(coro())
