"""053-plaza-template-distribution：模板 / 版本 / 克隆 数据模型.

模板类型（asset_type 扩展，FR-001 / 已定决策 #1）：
* ``employee_template`` —— 员工模板（定义载体 = 051 ``employees`` 档案，B1 未落地时仅建坐标）；
* ``sop_template`` —— SOP 模板（定义载体 = 010 ``dag_definitions`` 编排定义）。

**模板是定义，员工/编排是实例**：与 051 的 ``employee`` 运行时实体区分。

版本序列（已定决策 #3 / FR-005）：模板发新版本**不强制覆盖副本**；副本侧提示 +
手动升级（整份替换 + 旧副本快照，002 版本化口径）。

凭证（已定决策 #2 / FR-004）：模板 MUST NOT 含凭证明文（034 口径），克隆不复制凭证。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

#: 资产类型扩展（045 坐标 + 四徽标沿用）。与 051 的 ``employee``（运行时实体）区分。
EMPLOYEE_TEMPLATE = "employee_template"
SOP_TEMPLATE = "sop_template"

TEMPLATE_ASSET_TYPES: tuple[str, ...] = (EMPLOYEE_TEMPLATE, SOP_TEMPLATE)

#: 模板上架状态（FR-006）。
TEMPLATE_STATES: tuple[str, ...] = ("draft", "published", "offline")

#: 模板可见性——租户内广场可见（FR-008，跨租户 fail-closed）。


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _digest(document: Any) -> str:
    """Canonical content digest（排序键 JSON），用于原件不变性哈希断言（SC-001）。"""
    if isinstance(document, (dict, list)):
        return hashlib.sha256(
            json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
    return hashlib.sha256(str(document).encode()).hexdigest()


def make_template_id() -> str:
    return f"tpl_{uuid.uuid4().hex}"


def make_clone_id() -> str:
    return f"clone_{uuid.uuid4().hex}"


@dataclass
class AssetTemplate:
    """模板（类型 employee_template/sop_template、定义内容引用、版本序列、上架状态、上架者）。"""

    template_id: str
    tenant_id: str
    name: str
    asset_type: str
    #: 定义内容（SOP = dag_definitions 文档；员工 = employees 档案字段）。
    content: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    state: str = "draft"
    owner_id: str = ""
    description: str = ""
    category: str = ""
    #: 032 评估门禁报告引用（SOP 上架前置，FR-002）。
    gate_report: dict[str, Any] = field(default_factory=dict)
    #: 版本序列（002 版本化口径）：{version, content_snapshot, published_at, gate_report?}。
    versions: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if not str(self.template_id or "").strip():
            raise TemplateError("template_id must not be empty")
        if self.asset_type not in TEMPLATE_ASSET_TYPES:
            raise TemplateError(
                f"unsupported asset_type: {self.asset_type!r} (expected one of {TEMPLATE_ASSET_TYPES})"
            )
        if self.state not in TEMPLATE_STATES:
            raise TemplateError(f"unknown template state: {self.state!r}")

    @property
    def is_published(self) -> bool:
        return self.state == "published"

    @property
    def is_readonly(self) -> bool:
        """原件只读：非草稿即只读（副本可改、原件只读，已定决策 #2 / FR-003）。"""
        return self.state != "draft"

    def publish(self, *, gate_report: dict[str, Any] | None = None) -> int:
        """上架（前置门禁由 publish.py 完成）：记录版本快照 + 标记 published。

        返回当前版本号。
        """
        self.versions.append({
            "version": self.version,
            "content_snapshot": dict(self.content),
            "published_at": utcnow().isoformat(),
            "gate_report": dict(gate_report or self.gate_report or {}),
        })
        self.gate_report = dict(gate_report or self.gate_report or {})
        self.state = "published"
        self.updated_at = utcnow()
        return self.version

    def unpublish(self) -> None:
        self.state = "offline"
        self.updated_at = utcnow()

    def add_version(self, *, content: dict[str, Any], gate_report: dict[str, Any] | None = None) -> int:
        """发布新版本：归档当前版本快照、替换内容、bump 版本（002 口径，FR-005）。"""
        self.versions.append({
            "version": self.version,
            "content_snapshot": dict(self.content),
            "published_at": utcnow().isoformat(),
            "gate_report": dict(self.gate_report or {}),
        })
        self.content = dict(content)
        self.gate_report = dict(gate_report or self.gate_report or {})
        self.version += 1
        self.state = "published"
        self.updated_at = utcnow()
        return self.version

    def digest(self) -> str:
        return _digest(self.content)

    def as_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "template_id": self.template_id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "asset_type": self.asset_type,
            "version": self.version,
            "state": self.state,
            "owner_id": self.owner_id,
            "description": self.description,
            "category": self.category,
            "gate_report": dict(self.gate_report),
            "versions": list(self.versions),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "digest": self.digest(),
            "readonly": self.is_readonly,
        }
        if include_content:
            data["content"] = self.content
        return data


@dataclass
class TemplateClone:
    """克隆记录（副本实体坐标、克隆者、template_ref、克隆时刻）。"""

    clone_id: str
    tenant_id: str
    template_id: str
    template_type: str
    template_version: int
    cloner_id: str
    #: 副本落点：SOP → dag_definitions（orchestration_id）；员工 → employees（employee_id）。
    target_type: str
    target_key: str
    #: template_ref = 模板坐标 + 版本（已定决策 #2 / FR-003）。
    template_ref: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if not str(self.clone_id or "").strip():
            raise TemplateError("clone_id must not be empty")
        if not str(self.target_key or "").strip():
            raise TemplateError("target_key must not be empty")

    @property
    def ref(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "asset_type": self.template_type,
            "version": self.template_version,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "clone_id": self.clone_id,
            "tenant_id": self.tenant_id,
            "template_id": self.template_id,
            "template_type": self.template_type,
            "template_version": self.template_version,
            "cloner_id": self.cloner_id,
            "target_type": self.target_type,
            "target_key": self.target_key,
            "template_ref": dict(self.template_ref or self.ref),
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class UpgradeRecord:
    """副本升级记录（旧快照引用 / 新版本 / 操作者 / 时刻）。"""

    upgrade_id: str
    tenant_id: str
    template_id: str
    target_type: str
    target_key: str
    old_version: int
    new_version: int
    operator_id: str
    #: 旧副本快照（002 版本化：升级前留快照，不强制覆盖）。
    old_snapshot: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)

    def as_dict(self) -> dict[str, Any]:
        return {
            "upgrade_id": self.upgrade_id,
            "tenant_id": self.tenant_id,
            "template_id": self.template_id,
            "target_type": self.target_type,
            "target_key": self.target_key,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "operator_id": self.operator_id,
            "created_at": self.created_at.isoformat(),
        }


class TemplateError(ValueError):
    """Raised for an invalid template operation."""


__all__ = [
    "EMPLOYEE_TEMPLATE",
    "SOP_TEMPLATE",
    "TEMPLATE_ASSET_TYPES",
    "TEMPLATE_STATES",
    "AssetTemplate",
    "TemplateClone",
    "TemplateError",
    "UpgradeRecord",
    "make_clone_id",
    "make_template_id",
    "utcnow",
]
