"""053-plaza-template-distribution：模板 / 克隆 / 升级 持久化（027 门面）.

经 ``app.core.db`` 门面访问数据后端（Mongo / PanWeiDB 兼容门面），
不直接 import 具体驱动。集合：

* ``asset_templates``  —— 模板本体（含版本序列内容快照）；
* ``template_clones``  —— 克隆记录（template_ref）；
* ``template_upgrades`` —— 副本升级记录（旧快照引用）。

双后端经 027 门面（``get_db()``），不另建存储通道。
"""

from __future__ import annotations

from typing import Any, Optional

from app.core.db import get_db

from .model import AssetTemplate, TemplateClone, TemplateError, UpgradeRecord, utcnow

TEMPLATES_COLLECTION = "asset_templates"
CLONES_COLLECTION = "template_clones"
UPGRADES_COLLECTION = "template_upgrades"


def _template_to_row(template: AssetTemplate) -> dict[str, Any]:
    return {
        "template_id": template.template_id,
        "tenant_id": template.tenant_id,
        "name": template.name,
        "asset_type": template.asset_type,
        "content": dict(template.content),
        "version": template.version,
        "state": template.state,
        "owner_id": template.owner_id,
        "description": template.description,
        "category": template.category,
        "gate_report": dict(template.gate_report),
        "versions": list(template.versions),
        "created_at": template.created_at,
        "updated_at": template.updated_at,
        "digest": template.digest(),
    }


def _row_to_template(row: dict[str, Any]) -> AssetTemplate:
    return AssetTemplate(
        template_id=str(row.get("template_id") or ""),
        tenant_id=str(row.get("tenant_id") or "default"),
        name=str(row.get("name") or ""),
        asset_type=str(row.get("asset_type") or ""),
        content=dict(row.get("content") or {}),
        version=int(row.get("version") or 1),
        state=str(row.get("state") or "draft"),
        owner_id=str(row.get("owner_id") or ""),
        description=str(row.get("description") or ""),
        category=str(row.get("category") or ""),
        gate_report=dict(row.get("gate_report") or {}),
        versions=list(row.get("versions") or []),
        created_at=row.get("created_at") or utcnow(),
        updated_at=row.get("updated_at") or utcnow(),
    )


def _clone_to_row(clone: TemplateClone) -> dict[str, Any]:
    return {
        "clone_id": clone.clone_id,
        "tenant_id": clone.tenant_id,
        "template_id": clone.template_id,
        "template_type": clone.template_type,
        "template_version": clone.template_version,
        "cloner_id": clone.cloner_id,
        "target_type": clone.target_type,
        "target_key": clone.target_key,
        "template_ref": dict(clone.template_ref or clone.ref),
        "created_at": clone.created_at,
    }


def _row_to_clone(row: dict[str, Any]) -> TemplateClone:
    return TemplateClone(
        clone_id=str(row.get("clone_id") or ""),
        tenant_id=str(row.get("tenant_id") or "default"),
        template_id=str(row.get("template_id") or ""),
        template_type=str(row.get("template_type") or ""),
        template_version=int(row.get("template_version") or 1),
        cloner_id=str(row.get("cloner_id") or ""),
        target_type=str(row.get("target_type") or ""),
        target_key=str(row.get("target_key") or ""),
        template_ref=dict(row.get("template_ref") or {}),
        created_at=row.get("created_at") or utcnow(),
    )


def _upgrade_to_row(record: UpgradeRecord) -> dict[str, Any]:
    return {
        "upgrade_id": record.upgrade_id,
        "tenant_id": record.tenant_id,
        "template_id": record.template_id,
        "target_type": record.target_type,
        "target_key": record.target_key,
        "old_version": record.old_version,
        "new_version": record.new_version,
        "operator_id": record.operator_id,
        "old_snapshot": dict(record.old_snapshot),
        "created_at": record.created_at,
    }


def _row_to_upgrade(row: dict[str, Any]) -> UpgradeRecord:
    return UpgradeRecord(
        upgrade_id=str(row.get("upgrade_id") or ""),
        tenant_id=str(row.get("tenant_id") or "default"),
        template_id=str(row.get("template_id") or ""),
        target_type=str(row.get("target_type") or ""),
        target_key=str(row.get("target_key") or ""),
        old_version=int(row.get("old_version") or 1),
        new_version=int(row.get("new_version") or 1),
        operator_id=str(row.get("operator_id") or ""),
        old_snapshot=dict(row.get("old_snapshot") or {}),
        created_at=row.get("created_at") or utcnow(),
    )


class TemplateRepository:
    """模板 / 克隆 / 升级 持久化仓库（027 门面，双后端）。"""

    async def save_template(self, template: AssetTemplate) -> None:
        db = get_db()
        await db[TEMPLATES_COLLECTION].replace_one(
            {"template_id": template.template_id, "tenant_id": template.tenant_id},
            _template_to_row(template),
            upsert=True,
        )

    async def get_template(self, template_id: str, *, tenant_id: str | None = None) -> Optional[AssetTemplate]:
        db = get_db()
        query: dict[str, Any] = {"template_id": template_id}
        if tenant_id is not None:
            query["tenant_id"] = tenant_id
        row = await db[TEMPLATES_COLLECTION].find_one(query)
        return _row_to_template(row) if row else None

    async def list_templates(
        self,
        *,
        tenant_id: str,
        asset_type: str | None = None,
        state: str | None = None,
    ) -> list[AssetTemplate]:
        db = get_db()
        query: dict[str, Any] = {"tenant_id": tenant_id}
        if asset_type:
            query["asset_type"] = asset_type
        if state:
            query["state"] = state
        rows = await db[TEMPLATES_COLLECTION].find(query).sort("created_at", -1).to_list(length=500)
        return [_row_to_template(r) for r in rows]

    async def save_clone(self, clone: TemplateClone) -> None:
        db = get_db()
        await db[CLONES_COLLECTION].replace_one(
            {"clone_id": clone.clone_id, "tenant_id": clone.tenant_id},
            _clone_to_row(clone),
            upsert=True,
        )

    async def get_clone(self, clone_id: str, *, tenant_id: str | None = None) -> Optional[TemplateClone]:
        db = get_db()
        query: dict[str, Any] = {"clone_id": clone_id}
        if tenant_id is not None:
            query["tenant_id"] = tenant_id
        row = await db[CLONES_COLLECTION].find_one(query)
        return _row_to_clone(row) if row else None

    async def list_clones(
        self,
        *,
        tenant_id: str,
        template_id: str | None = None,
        cloner_id: str | None = None,
    ) -> list[TemplateClone]:
        db = get_db()
        query: dict[str, Any] = {"tenant_id": tenant_id}
        if template_id:
            query["template_id"] = template_id
        if cloner_id:
            query["cloner_id"] = cloner_id
        rows = await db[CLONES_COLLECTION].find(query).sort("created_at", -1).to_list(length=500)
        return [_row_to_clone(r) for r in rows]

    async def save_upgrade(self, record: UpgradeRecord) -> None:
        db = get_db()
        await db[UPGRADES_COLLECTION].replace_one(
            {"upgrade_id": record.upgrade_id, "tenant_id": record.tenant_id},
            _upgrade_to_row(record),
            upsert=True,
        )

    async def list_upgrades(
        self,
        *,
        tenant_id: str,
        template_id: str | None = None,
        target_key: str | None = None,
    ) -> list[UpgradeRecord]:
        db = get_db()
        query: dict[str, Any] = {"tenant_id": tenant_id}
        if template_id:
            query["template_id"] = template_id
        if target_key:
            query["target_key"] = target_key
        rows = await db[UPGRADES_COLLECTION].find(query).sort("created_at", -1).to_list(length=500)
        return [_row_to_upgrade(r) for r in rows]

    # --- audit（001 单一审计汇同 schema，失败不阻断主流程）-------------------

    async def audit(self, *, tenant_id: str, actor: str, action: str, detail: dict[str, Any]) -> None:
        import uuid

        try:
            db = get_db()
            await db["gate_events"].insert_one({
                "event_id": uuid.uuid4().hex,
                "occurred_at": utcnow(),
                "tenant_id": tenant_id,
                "user_id": actor,
                "roles": [],
                "tool": f"template.{action}",
                "risk_level": "",
                "autonomy_level": "",
                "decision": "allow",
                "layer": "template",
                "reason": f"template {action}",
                "detail": dict(detail),
            })
        except Exception as exc:  # pragma: no cover - defensive
            import logging

            logging.getLogger(__name__).warning(
                "template audit write failed (%s): %s", action, exc,
            )


__all__ = [
    "CLONES_COLLECTION",
    "TEMPLATES_COLLECTION",
    "UPGRADES_COLLECTION",
    "TemplateRepository",
]
