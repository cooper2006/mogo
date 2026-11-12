"""050 生产节点执行体：经 LocalBridge 把节点技能派给已连接的浏览器 agent。

执行链复用 010 ``research.py::_default_sub_agent`` 的 skill fast-path
（``browser_execute_workflow`` → ``agent_registry.send_tool_call``），差异：

* ``goal`` 提取通用化：``node.payload.goal`` → ``context.goal``（原版特化于
  竞品研究的 ``competitor_name``）；
* ``domain`` 标记为 ``orchestration``（registry 仅透传进 WS 帧，无路由逻辑）；
* 降级语义保持诚实：无 ``context["session_id"]`` / agent 未连接 / envelope
  不 ok 时返回 ``{"status": "unavailable", ...}``，**不伪造输出**（fail-closed：
  比 ``_declarative_runner`` 的 echo 回显强一个量级——回显是假装成功）。

语义边界：真实执行依赖已连接的浏览器 agent 会话（``session_id`` 由发起方
放进 run context，``user_id`` 由 ``start_run`` 端点补齐）；无 agent 场景下的
非浏览器执行体不在 050 首期范围。
"""

from __future__ import annotations

from typing import Any


async def production_node_runner(node: Any, context: dict[str, Any]) -> Any:
    """Run a graph node as a real skill via the connected browser agent."""
    skill = str(node.payload.get("skill") or node.id)
    session_id = str(context.get("session_id") or "")
    if not session_id:
        return {"status": "unavailable", "skill": skill, "reason": "no agent session"}
    from app.browser.local_bridge import AgentNotConnected, LocalBridge

    bridge = LocalBridge(str(context.get("user_id") or ""), session_id)
    if not bridge.available():
        return {"status": "unavailable", "skill": skill, "reason": "agent not connected"}
    goal = str(node.payload.get("goal") or context.get("goal") or "")
    try:
        envelope = await bridge.execute(
            "browser_execute_workflow",
            {"skill": skill, "goal": goal},
            domain="orchestration",
            timeout=120.0,
        )
    except AgentNotConnected:
        return {"status": "unavailable", "skill": skill, "reason": "agent not connected"}
    if not isinstance(envelope, dict) or not bool(envelope.get("ok")):
        return {"status": "unavailable", "skill": skill, "reason": str(envelope.get("error") or "fast-path-failed")}
    result = envelope.get("result")
    return dict(result) if isinstance(result, dict) else {"status": "ok", "result": result}
