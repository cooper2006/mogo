"""053-plaza-template-distribution：广场模板分发服务.

* :mod:`model`      —— 数据模型（AssetTemplate / TemplateClone / UpgradeRecord）；
* :mod:`repository` —— 持久化（027 门面，asset_templates / template_clones / template_upgrades）；
* :mod:`publish`    —— 上架门禁（032 SOP / 员工引用校验）+ 001 审批接线；
* :mod:`clone`      —— 深拷贝 + template_ref + 凭证剥离 + 050 审批人重解析；
* :mod:`upgrade`    —— 版本提示 + 手动升级（整份替换 + 旧快照）。
"""

from __future__ import annotations

from .model import (
    EMPLOYEE_TEMPLATE,
    SOP_TEMPLATE,
    TEMPLATE_ASSET_TYPES,
    TEMPLATE_STATES,
    AssetTemplate,
    TemplateClone,
    TemplateError,
    UpgradeRecord,
)
from .repository import TemplateRepository
from .publish import PublishBlocked, publish_template, run_publish_gate, unpublish_template
from .clone import CloneError, clone_template, strip_credentials
from .upgrade import UpgradeError, has_newer_version, list_template_versions, upgrade_clone

__all__ = [
    "EMPLOYEE_TEMPLATE",
    "SOP_TEMPLATE",
    "TEMPLATE_ASSET_TYPES",
    "TEMPLATE_STATES",
    "AssetTemplate",
    "TemplateClone",
    "TemplateError",
    "TemplateRepository",
    "UpgradeRecord",
    "PublishBlocked",
    "publish_template",
    "run_publish_gate",
    "unpublish_template",
    "CloneError",
    "clone_template",
    "strip_credentials",
    "UpgradeError",
    "has_newer_version",
    "list_template_versions",
    "upgrade_clone",
]
