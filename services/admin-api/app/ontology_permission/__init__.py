"""本体数据权限（ontology data-scope permission）—— admin-api 侧。

* ``constants``  ：表/集合名、枚举、复合键拼接
* ``repository`` ：原生双后端数据访问（mongo motor / PanWeiDB 原生 SQL）
* ``service``    ：配置、清单、可见集解析、授权写入侧（含审计与 rev 递增）

设计来源：``docs/ontology-permission-merge-plan.md``（合并方案）与
``docs/MOGO-Web应用集成方案.md`` §5.4-§5.9（接口 / 前端设计）。
"""

from __future__ import annotations

from .repository import OntologyPermissionRepository
from .service import OntologyPermissionService, resolve_visible_ontologies

__all__ = [
    "OntologyPermissionRepository",
    "OntologyPermissionService",
    "resolve_visible_ontologies",
]
