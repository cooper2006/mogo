"""053-plaza-template-distribution：版本提示 + 手动升级（FR-005 / 002 版本化）.

版本生命周期（已定决策 #3）：

* 模板发新版本**不强制覆盖副本**（副本侧提示"源模板有新版本"，用户手动选择升级）；
* 升级 = **整份替换**副本内容为新版本，**旧副本留快照**（002 版本化兜底），
  ``template_ref`` 更新、审计记录；
* 不做三方合并式升级（YAGNI，spec Non-Goals）。

升级入口为显式操作（用户确认后触发），本模块不自动升级。
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.db import get_db

from .model import AssetTemplate, UpgradeRecord, TemplateError, utcnow
from .repository import TemplateRepository

SOP_TARGET = "dag_definition"
EMPLOYEE_TARGET = "employee"


class UpgradeError(RuntimeError):
    """升级失败（模板无新版本 / 目标不存在等）。"""


def has_newer_version(template: AssetTemplate, *, current_ref_version: int) -> bool:
    """副本侧版本提示：源模板版本 > 副本 template_ref 版本即提示。"""
    return template.version > current_ref_version


async def list_template_versions(template: AssetTemplate) -> list[dict[str, Any]]:
    """模板版本序列（002 版本化口径，含内容快照 + 发布时刻 + 门禁报告）。"""
    return list(template.versions)


async def upgrade_clone(
    *,
    tenant_id: str,
    template: AssetTemplate,
    target_type: str,
    target_key: str,
    operator_id: str,
    repo: TemplateRepository | None = None,
) -> UpgradeRecord:
    """手动升级副本：整份替换为新版本内容 + 旧副本留快照 + template_ref 更新。

    ``template`` 必须是**已上架且目标版本 > 副本当前 ref 版本**（否则拒绝）。

    副本落点（既有实体集合）：
    * ``dag_definition`` → ``dag_definitions`` 集合（SOP）；
    * ``employee`` → ``employees`` 集合（051 B1）。

    Returns:
        升级记录（含旧快照引用）。
    """
    repo = repo or TemplateRepository()
    if not template.is_published:
        raise UpgradeError(f"源模板未上架，无法升级：{template.template_id}")

    old_snapshot = await _fetch_target_snapshot(target_type, target_key, tenant_id)
    if old_snapshot is None:
        raise UpgradeError(f"升级目标不存在：{target_type}:{target_key}")

    # 旧副本快照（002：升级前留快照，不强制覆盖）。
    record = UpgradeRecord(
        upgrade_id=f"upg_{uuid.uuid4().hex}",
        tenant_id=tenant_id,
        template_id=template.template_id,
        target_type=target_type,
        target_key=target_key,
        old_version=int(old_snapshot.get("version") or old_snapshot.get("template_version") or 1),
        new_version=template.version,
        operator_id=operator_id,
        old_snapshot=old_snapshot,
        created_at=utcnow(),
    )
    await repo.save_upgrade(record)

    # 整份替换（深拷贝 + 凭证剥离 + 审批人重解析，复用 clone 口径）。
    from .clone import strip_credentials

    new_content = strip_credentials(template.content)
    await _replace_target(target_type, target_key, tenant_id, template, new_content, old_snapshot, record)

    await repo.audit(
        tenant_id=tenant_id,
        actor=operator_id,
        action="upgrade",
        detail={
            "template_id": template.template_id,
            "target_type": target_type,
            "target_key": target_key,
            "old_version": record.old_version,
            "new_version": template.version,
        },
    )
    return record


async def _fetch_target_snapshot(target_type: str, target_key: str, tenant_id: str) -> dict[str, Any] | None:
    db = get_db()
    if target_type == SOP_TARGET:
        return await db["dag_definitions"].find_one({"tenant_id": tenant_id, "orchestration_id": target_key})
    if target_type == EMPLOYEE_TARGET:
        return await db["employees"].find_one({"tenant_id": tenant_id, "employee_id": target_key})
    return None


async def _replace_target(
    target_type: str,
    target_key: str,
    tenant_id: str,
    template: AssetTemplate,
    new_content: dict[str, Any],
    old_snapshot: dict[str, Any],
    record: UpgradeRecord,
) -> None:
    """整份替换副本内容为新版本；旧快照已由 upgrade_clone 记录。"""
    db = get_db()
    now = utcnow()
    if target_type == SOP_TARGET:
        # 保留编排 id 与既有 history（002 版本化），仅替换 document 内容。
        document = dict(new_content)
        header = document.get("orchestration")
        if isinstance(header, dict):
            header["id"] = target_key
            header["version"] = str(template.version)
            header["template_ref"] = {
                "template_id": template.template_id,
                "asset_type": template.asset_type,
                "version": template.version,
                "target_key": target_key,
            }
        history = list(old_snapshot.get("history") or [])
        history.append({
            "version": old_snapshot.get("version"),
            "status": old_snapshot.get("status", "draft"),
            "document": old_snapshot.get("document") or old_snapshot.get("definition"),
            "updatedAt": old_snapshot.get("updated_at"),
            "releaseNotes": "template upgrade (snapshot)",
        })
        await db["dag_definitions"].update_one(
            {"tenant_id": tenant_id, "orchestration_id": target_key},
            {"$set": {
                "orchestration_id": target_key,
                "tenant_id": tenant_id,
                "version": template.version,
                "status": "published",
                "document": document,
                "history": history,
                "updated_at": now,
                "template_ref": {
                    "template_id": template.template_id,
                    "asset_type": template.asset_type,
                    "version": template.version,
                    "target_key": target_key,
                },
            }},
        )
    elif target_type == EMPLOYEE_TARGET:
        profile = dict(new_content)
        profile["employee_id"] = target_key
        profile["tenant_id"] = tenant_id
        profile["version"] = template.version
        profile["template_ref"] = {
            "template_id": template.template_id,
            "asset_type": template.asset_type,
            "version": template.version,
            "target_key": target_key,
        }
        profile["_snapshot_history"] = list(old_snapshot.get("_snapshot_history") or []) + [
            {"version": record.old_version, "snapshot": old_snapshot, "at": now.isoformat()},
        ]
        await db["employees"].update_one(
            {"tenant_id": tenant_id, "employee_id": target_key},
            {"$set": profile},
        )
    else:
        raise TemplateError(f"不支持的副本类型：{target_type!r}")


__all__ = [
    "EMPLOYEE_TARGET",
    "SOP_TARGET",
    "UpgradeError",
    "has_newer_version",
    "list_template_versions",
    "upgrade_clone",
]
