"""Shared ASKAI admission for every server-side DSH turn.

009 T009：PreToolUse 钩子在 ``admit_skill_selection`` 之前执行（fail-closed）。
规则在调用时从 ``hook_rules`` 声明式存储读取（FR-4 即时生效）；无规则时行为
与原始 admission 路径完全一致（no-op）。命中或被拒绝的钩子执行经
``integration.audit_hook_execution`` 落 001 治理审计流（009 US2 / T011）。

001 运行时侧（US1）：工具调用在门禁链之前叠加 019 ``gate_adapter`` 的六层
启用计划（``build_gate_plan``）。当 001 gatekeeper 尚未就绪时走 019 的
transition 后端（挂载 approval_runtime + audit）；就绪后切回 gatekeeper
后端。审计层（第 6 层）在 thin 模式下保持打开，不得被跳过。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.dsh_runtime.profile.skills import MongoSkillCatalog
from app.dsh_runtime.profile.skills.resolver import require_selected_skill
from app.governance.audit import record_position_policy_event
from app.governance.position_policy import MongoEmployeePolicyResolver


@dataclass(frozen=True)
class TurnSkillSelection:
    selected_skill_id: str | None = None
    selected_writing_skill_id: str | None = None


@dataclass(frozen=True)
class PreToolUseGate:
    """009 PreToolUse 钩子的 fail-closed 判定结果。"""

    allowed: bool
    denied_reason: str = ""
    denied_rule_type: str = ""
    denied_scope: str = ""


async def run_pre_tool_use(
    *,
    tenant_id: str,
    user_id: str,
    tool: str,
    request: Optional[dict[str, Any]] = None,
    session_id: str = "",
) -> Optional[PreToolUseGate]:
    """PreToolUse gate（009 T009）。

    求值声明式规则；无匹配规则返回 ``None``（admission 不变）。任一 deny /
    解析失败（fail-closed）返回带拒绝原因的门禁，钩子执行同时落 001 审计。
    本函数即 009 生产接线入口：``dsh_chat`` 在技能选择前调用它。
    """
    from app.core.db import get_db
    from app.dsh_runtime.hooks.integration import audit_hook_execution, mount_pre_tool_use
    from app.dsh_runtime.hooks.store import HookRuleStore

    store = HookRuleStore(get_db())
    raw_rules = [
        document.as_document()
        for document in await store.rules_in_scope(
            tool=tool, session_id=session_id, tenant_id=tenant_id
        )
    ]
    if not raw_rules:
        return None
    outcome = mount_pre_tool_use(tool, request or {}, raw_rules=raw_rules)
    await audit_hook_execution(outcome, tenant_id=tenant_id, user_id=user_id, tool=tool)
    if outcome.allowed:
        return None
    return PreToolUseGate(
        allowed=False,
        denied_reason=outcome.reason,
        denied_rule_type=outcome.rule_type,
        denied_scope=outcome.scope,
    )


@dataclass(frozen=True)
class GatePlan:
    """001 运行时侧（US1）：工具调用在门禁链之前求值的 019 层启用计划。

    把 019 ``build_gate_plan`` 的六层启用集真正挂到 admission 工具路径上。
    审计层（第 6 层）受 floor 约束在 thin 模式下仍必须开启，否则计划被
    ``assert_floor_intact`` 拒绝（fail-closed）。
    """

    backend: str
    layers: tuple[str, ...]
    audit_enabled: bool
    skipped: tuple[str, ...]


def _resolve_gate_plan(tool: str, request: Optional[dict[str, Any]]) -> GatePlan:
    """Build the 001/019 gate plan for a tool call (001 US1 运行时侧接线)。

    后端选择沿用 019 ``backend_for``：001 gatekeeper 就绪 → ``gatekeeper``，
    否则走 transition 后端（approval_runtime + audit）。审计层永远保留。
    """
    from app.harness_config.gate_adapter import backend_for, build_gate_plan, GATEKEEPER_READY

    payload = request or {}
    mode = str(payload.get("harness_mode") or "thick")
    gatekeeper_ready = bool(payload.get("gatekeeper_ready"))
    plan = build_gate_plan(
        mode=mode,
        audit_granularity=str(payload.get("audit_granularity") or ""),
        backend=backend_for(gatekeeper_ready),
    )
    return GatePlan(
        backend=plan.backend,
        layers=tuple(plan.layers),
        audit_enabled=plan.audit_enabled(),
        skipped=tuple(plan.skipped_layers),
    )


async def run_gate_plan(
    *,
    tenant_id: str,
    user_id: str,
    tool: str,
    request: Optional[dict[str, Any]] = None,
) -> GatePlan:
    """001 US1 运行时侧：把 001 六层启用计划真正作用于工具调用路径。

    求值 019 ``build_gate_plan``（``assert_floor_intact`` 校验）并落 001 审计；
    若审计层被意外跳过（floor 违规）则 fail-closed 拒绝。审计事件复用 001
    的 ``record_position_policy_event``（009 US2 / T999 共用落点）。
    """
    plan = _resolve_gate_plan(tool, request)
    await record_position_policy_event(
        tenant_id=tenant_id,
        user_id=user_id,
        action="gate.plan.resolved",
        target=tool,
        details={
            "backend": plan.backend,
            "layers": list(plan.layers),
            "audit_enabled": plan.audit_enabled,
            "skipped": list(plan.skipped),
        },
    )
    if not plan.audit_enabled:
        raise PermissionError("门禁计划违反 floor（审计层不可跳过），已 fail-closed 拒绝")
    return plan


async def admit_skill_selection(
    *,
    tenant_id: str,
    user_id: str,
    selected_skill_id: str | None,
    tool: str = "",
    request: Optional[dict[str, Any]] = None,
    session_id: str = "",
) -> TurnSkillSelection:
    """Authorize one opaque control-plane Skill id before Profile execution.

    009 T009：当调用方声明了 ``tool``（工具调用语义）时，先过 PreToolUse
    声明式钩子门禁（fail-closed）；被拒直接抛 ``PermissionError``，不进入
    岗位技能策略求值。无 ``tool`` 时与原路径完全一致（no-op）。

    001 US1 运行时侧：钩子通过后，再把 001 六层启用计划（019
    ``build_gate_plan``）挂到工具路径上——审计层受 floor 约束必须开启，
    计划求值与门禁事件同落 001 审计流。
    """
    if tool:
        gate = await run_pre_tool_use(
            tenant_id=tenant_id,
            user_id=user_id,
            tool=tool,
            request=request,
            session_id=session_id,
        )
        if gate is not None:
            await record_position_policy_event(
                tenant_id=tenant_id,
                user_id=user_id,
                action="hook.denied",
                target=tool,
                details={
                    "reason": gate.denied_reason,
                    "rule_type": gate.denied_rule_type,
                    "scope": gate.denied_scope,
                },
            )
            raise PermissionError(f"钩子规则拒绝工具调用：{gate.denied_reason}")
        # 001 运行时侧：钩子放行后再走 001/019 六层启用计划门禁（审计层强制）。
        await run_gate_plan(
            tenant_id=tenant_id,
            user_id=user_id,
            tool=tool,
            request=request,
        )

    selected = str(selected_skill_id or "").strip()
    if not selected:
        return TurnSkillSelection()
    policy = await MongoEmployeePolicyResolver().resolve(tenant_id, user_id)
    if not policy.allows_skill(selected):
        await record_position_policy_event(
            tenant_id=tenant_id,
            user_id=user_id,
            action="capability.denied",
            target="skill",
            details={"skill_id": selected},
        )
        raise PermissionError("当前岗位未开通该 Skill")
    kind, _row = await require_selected_skill(
        MongoSkillCatalog(MongoEmployeePolicyResolver()),
        skill_id=selected,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    await record_position_policy_event(
        tenant_id=tenant_id,
        user_id=user_id,
        action="capability.used",
        target="skill",
        details={"skill_id": selected},
    )
    if tool:
        # 009 US2：钩子通过也落 001 审计（与拒绝事件对称，100% 覆盖）
        await record_position_policy_event(
            tenant_id=tenant_id,
            user_id=user_id,
            action="hook.executed",
            target=tool,
            details={"skill_id": selected, "reason": "hooks passed"},
        )
    if kind == "writing_style":
        return TurnSkillSelection(selected_writing_skill_id=selected)
    return TurnSkillSelection(selected_skill_id=selected)
