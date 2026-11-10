"""053-plaza-template-distribution：模板上架门禁（FR-002）+ 001 审批接线.

门禁（fail-closed，三类拒绝见 spec SC-002）：

* **SOP 模板**：MUST 过 032 评估门禁（``eval_gate.gate.run_gate``，复用
  ``skill_eval`` 既有范式）。**无测试集不得上架**（032 口径，不豁免）。
* **员工模板**：校验档案引用有效性——引用的工具 / Skill / 知识库存在且
  上架者有权（已定决策 #4）。

上架走 001 审批：复用 ``portal_admin`` 的上架与审批链路（037 口径），
本模块不另建审批通道。
"""

from __future__ import annotations

from typing import Any

from app.core.db import get_db

from .model import (
    EMPLOYEE_TEMPLATE,
    SOP_TEMPLATE,
    AssetTemplate,
    TemplateError,
    utcnow,
)
from .repository import TemplateRepository


class PublishBlocked(RuntimeError):
    """上架门禁阻断（携带原因与门禁详情，供 API 层返回）。"""

    def __init__(self, reason: str, *, detail: dict[str, Any] | None = None, status_code: int = 409) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}
        self.status_code = status_code


async def _run_sop_gate(template: AssetTemplate) -> dict[str, Any]:
    """SOP 模板上架门禁：032 评估（无测试集拒绝，不豁免）。

    无测试集（``count_cases == 0``）直接 fail-closed 拒绝，不进入评测执行
    （spec Edge Cases：SOP 模板无测试集不得上架，032 口径）。
    """
    from app.services.eval_gate.gate import run_gate
    from app.services.eval_gate.test_sets import count_cases

    # SOP 模板定义载体 = dag_definitions；skill_id 使用模板坐标作为评测归属键。
    skill_id = f"template:{template.template_id}"
    total = await count_cases(tenant_id=template.tenant_id, skill_id=skill_id)
    if total == 0:
        raise PublishBlocked(
            "该 SOP 模板尚未配置评测测试集，请先创建黄金测试集再上架（032 口径，不豁免）",
            detail={"gate": "eval", "reason": "no_test_set"},
        )
    try:
        report = await run_gate(
            tenant_id=template.tenant_id,
            skill_id=skill_id,
            version=str(template.version),
            skill_draft=template.content,
            dry_run=False,
        )
    except Exception as exc:  # noqa: BLE001 - EvalGateBlocked 及底层失败均 fail-closed
        # 032 门禁异常：样本不足 / 未达阈值 / 执行失败。
        raise PublishBlocked(str(exc), detail={"gate": "eval", "error": str(exc)}) from exc
    if not report.get("passed"):
        raise PublishBlocked(
            str(report.get("blockedReason") or "评估未通过"),
            detail={"gate": "eval", "metrics": report.get("metrics"), "thresholds": report.get("thresholds")},
        )
    return {"runId": report.get("runId"), "passed": True, "metrics": report.get("metrics")}


async def _validate_employee_refs(template: AssetTemplate) -> dict[str, Any]:
    """员工模板上架：校验档案引用有效性（工具/Skill/知识库存在且上架者有权）。"""
    db = get_db()
    content = template.content or {}
    refs: dict[str, Any] = {"tools": [], "skills": [], "knowledge": []}
    # 能力白名单（工具 + Skill）沿用 051 档案 / 006 白名单范式。
    capability = content.get("capabilities") or {}
    tool_ids = capability.get("tools") or content.get("tools") or []
    skill_ids = capability.get("skills") or content.get("skills") or []
    knowledge_ids = content.get("knowledge_base_ids") or content.get("knowledge") or []
    refs["tools"] = list(tool_ids)
    refs["skills"] = list(skill_ids)
    refs["knowledge"] = list(knowledge_ids)

    for tool_id in tool_ids:
        row = await db["external_tools"].find_one({"tool_id": str(tool_id)})
        if row is None:
            row = await db["external_tools"].find_one({"_id": str(tool_id)})
        if row is None:
            raise PublishBlocked(f"引用的工具不存在或已下线：{tool_id}", detail={"ref": "tool", "key": str(tool_id)})
    for skill_id in skill_ids:
        row = await db["skills"].find_one({"_id": str(skill_id), "tenant_id": template.tenant_id})
        if row is None:
            raise PublishBlocked(f"引用的 Skill 不存在：{skill_id}", detail={"ref": "skill", "key": str(skill_id)})
        # 上架者有权判定（owner 或管理面）——此处校验存在性，权限由 API 层鉴权。
    for knowledge_id in knowledge_ids:
        row = await db["knowledge_bases"].find_one({"_id": str(knowledge_id), "tenant_id": template.tenant_id})
        if row is None:
            raise PublishBlocked(f"引用的知识库不存在：{knowledge_id}", detail={"ref": "knowledge", "key": str(knowledge_id)})
    return {"valid": True, "refs": refs}


async def run_publish_gate(template: AssetTemplate) -> dict[str, Any]:
    """模板上架门禁入口（FR-002）。通过返回门禁报告；否则抛 ``PublishBlocked``。"""
    if template.asset_type == SOP_TEMPLATE:
        return await _run_sop_gate(template)
    if template.asset_type == EMPLOYEE_TEMPLATE:
        return await _validate_employee_refs(template)
    raise PublishBlocked(f"不支持的模板类型：{template.asset_type!r}", status_code=400)


async def publish_template(
    template: AssetTemplate,
    *,
    actor: str,
    repo: TemplateRepository | None = None,
) -> AssetTemplate:
    """上架：跑门禁 → 记录版本快照 → 标记 published → 审计。

    门禁失败抛 ``PublishBlocked``（fail-closed，不静默上架）。
    """
    repo = repo or TemplateRepository()
    gate_report = await run_publish_gate(template)
    template.publish(gate_report=gate_report)
    await repo.save_template(template)
    await repo.audit(
        tenant_id=template.tenant_id,
        actor=actor,
        action="publish",
        detail={"template_id": template.template_id, "version": template.version, "asset_type": template.asset_type},
    )
    return template


async def unpublish_template(
    template: AssetTemplate,
    *,
    actor: str,
    repo: TemplateRepository | None = None,
) -> AssetTemplate:
    """下架（FR-006）：不撤销已克隆副本（副本独立存活）；仅标记 offline。"""
    repo = repo or TemplateRepository()
    template.unpublish()
    await repo.save_template(template)
    await repo.audit(
        tenant_id=template.tenant_id,
        actor=actor,
        action="unpublish",
        detail={"template_id": template.template_id, "asset_type": template.asset_type},
    )
    return template


__all__ = [
    "PublishBlocked",
    "publish_template",
    "run_publish_gate",
    "unpublish_template",
]
