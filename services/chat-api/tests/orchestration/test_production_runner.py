"""050 P0-2 接线回归：生产 runner 与周期恢复扫描（2026-11-12 复审整改）。

覆盖四块：
* 无 agent 会话 → 诚实降级 ``unavailable``（不抛、不伪造输出，fail-closed）；
* LocalBridge 三态：未连接 / envelope 不 ok / ok（goal 提取通用化：payload.goal
  优先于 context.goal）；
* ``set_run_runner`` 注入与复位（``effective_runner`` 的生产语义）；
* ``periodic_recovery_sweep`` 在 db 未就绪时返回 None 不抛（循环下一轮重试）。

LocalBridge 的真实执行链（WS → agent_registry）不在本文件范围：这里只锁
降级判定与注入缝；端到端执行由手工链路验收（见 spec 050 / 交付记录）。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import app.browser.local_bridge as local_bridge_module
from app.api.endpoints import orchestration_runs
from app.orchestration.production_runner import production_node_runner


def _node(payload: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(id="research", payload=payload or {"skill": "researcher"})


def test_no_session_degrades_honestly() -> None:
    result = asyncio.run(production_node_runner(_node(), {"user_id": "u-1"}))
    assert result == {"status": "unavailable", "skill": "researcher", "reason": "no agent session"}


class _FakeBridge:
    """替身 LocalBridge：按用例需要呈现三态。"""

    instances: list["_FakeBridge"] = []
    #: 可达性开关（LocalBridge.available 是 property，这里同构以免 bool 被当函数调）。
    reachable: bool = True
    envelope: dict = {"ok": True, "result": {"status": "ok", "summary": "done"}}

    def __init__(self, user_id: str, session_id: str = "default") -> None:
        self.user_id = user_id
        self.session_id = session_id
        self.calls: list[dict] = []
        _FakeBridge.instances.append(self)

    def available(self) -> bool:
        """与真身 LocalBridge.available 同形：普通方法（不是 property），
        调用方写的是 ``bridge.available()``。"""
        return _FakeBridge.reachable

    async def execute(self, tool: str, args: dict, **kwargs) -> dict:
        self.calls.append({"tool": tool, "args": args, **kwargs})
        return _FakeBridge.envelope


def _with_fake_bridge(monkeypatch) -> type[_FakeBridge]:
    _FakeBridge.instances = []
    _FakeBridge.reachable = True
    _FakeBridge.envelope = {"ok": True, "result": {"status": "ok", "summary": "done"}}
    monkeypatch.setattr(local_bridge_module, "LocalBridge", _FakeBridge)
    return _FakeBridge


def test_bridge_unavailable_degrades(monkeypatch) -> None:
    fake = _with_fake_bridge(monkeypatch)
    fake.reachable = False
    result = asyncio.run(production_node_runner(_node(), {"session_id": "s-1", "user_id": "u-1"}))
    assert result["status"] == "unavailable"
    assert result["reason"] == "agent not connected"
    assert fake.instances[0].calls == []


def test_bridge_envelope_not_ok_degrades(monkeypatch) -> None:
    fake = _with_fake_bridge(monkeypatch)
    fake.envelope = {"ok": False, "error": "skill not found"}
    result = asyncio.run(production_node_runner(_node(), {"session_id": "s-1", "user_id": "u-1"}))
    assert result["status"] == "unavailable"
    assert result["reason"] == "skill not found"


def test_bridge_ok_returns_result_and_generalized_goal(monkeypatch) -> None:
    fake = _with_fake_bridge(monkeypatch)
    result = asyncio.run(
        production_node_runner(
            _node({"skill": "researcher", "goal": "调研 A 公司"}),
            {"session_id": "s-1", "user_id": "u-1", "goal": "不应被选中"},
        )
    )
    assert result == {"status": "ok", "summary": "done"}
    call = fake.instances[0].calls[0]
    assert call["tool"] == "browser_execute_workflow"
    assert call["args"] == {"skill": "researcher", "goal": "调研 A 公司"}
    assert call["domain"] == "orchestration"
    # payload 无 goal 时回落 context.goal（原版特化 competitor_name 的通用化）。
    asyncio.run(production_node_runner(_node(), {"session_id": "s-1", "goal": "回落目标"}))
    assert fake.instances[1].calls[0]["args"]["goal"] == "回落目标"


def test_effective_runner_injection_and_reset() -> None:
    async def production_like(node, context):  # pragma: no cover - 仅作身份标记
        return None

    try:
        orchestration_runs.set_run_runner(production_like)
        assert orchestration_runs.effective_runner() is production_like
    finally:
        orchestration_runs.set_run_runner(None)  # 复位，避免泄漏进其它用例
    assert orchestration_runs.effective_runner() is orchestration_runs._declarative_runner


def test_periodic_recovery_sweep_returns_none_without_db(monkeypatch) -> None:
    monkeypatch.setattr(orchestration_runs, "get_db", lambda: None)
    assert asyncio.run(orchestration_runs.periodic_recovery_sweep()) is None
