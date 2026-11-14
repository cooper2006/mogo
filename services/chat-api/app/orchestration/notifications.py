"""Approval notification rendering (050 FR-007, OQ-2 口径).

首期承诺 = **站内待办入口（``/api/v1/orchestration-runs/todos``）+ 审计事件**
+ IM **应答式触达**：审批人下次与 bot 交互时，在应答里附加待办提醒。不做全
渠道主动推送（飞书应用消息主动发送等留作扩展）。

本模块保持 transport-agnostic：不 import IM 适配器，只提供
``render_approval_reminder``（单条待办 → 可读文本）与
``pending_reminder_text``（审批人全部待办 → 一段提醒，供 IM 层拼接入应答）。
"""

from __future__ import annotations

from typing import Any

from .run_store import RunStore, RunStoreError


def render_approval_reminder(todo: dict[str, Any]) -> str:
    prompt = str(todo.get("prompt") or "").strip()
    base = (
        f"您有一条待审批：编排 {todo.get('orchestration_id')} "
        f"/ 节点 {todo.get('node_id')}（运行 {todo.get('run_id')}）"
    )
    if prompt:
        base += f"\n说明：{prompt}"
    base += "\n请到审批中心处理。"
    return base


async def pending_reminder_text(
    store: RunStore, *, tenant_id: str, approver: str, limit: int = 5
) -> str:
    """应答式触达：该审批人待办拼成提醒文本；无待办返回空串。"""
    try:
        todos = await store.list_todos(tenant_id=tenant_id, approver=approver)
    except RunStoreError:
        return ""
    if not todos:
        return ""
    shown = todos[: max(1, int(limit))]
    lines = [render_approval_reminder(todo) for todo in shown]
    if len(todos) > len(shown):
        lines.append(f"…另有 {len(todos) - len(shown)} 条待办")
    return "\n".join(lines)