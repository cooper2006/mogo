"""本体数据权限 —— 对业务系统的内部接口（设计 §5.8）。

```text
GET /admin-api/api/internal/ontology-permissions?tenantId=<t>&userId=<u>
→ { "ontologies": [ { "ontologyId": "material", "sourceEntity": "md_material",
                      "keyField": "material_code" } ] }
```

闭环：**MOGO 侧授权 → 业务系统侧过滤**。

鉴权：服务凭证（``X-MOGO-Service-Token``），与 ``personal_knowledge_internal.py`` 同一机制
（``settings.backend_service_token``，``hmac.compare_digest`` 常量时间比较）。

部署注意（设计 §6 约束 6）：``/internal/*`` **默认不在网关路由表内**，需显式加
``location`` 并限制来源网段。
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Query
from app.security.service_token import ServiceTokenHeader

from app.core.config import settings
from app.ontology_permission.service import OntologyPermissionService

router = APIRouter()


def _require_service(token: str) -> None:
    expected = str(settings.backend_service_token or "")
    if not token or not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="invalid_service_token")


@router.get("")
async def ontology_permissions_for_user(
    tenantId: str = Query(...),
    userId: str = Query(...),
    service_token: ServiceTokenHeader = "",
) -> dict[str, object]:
    """按 ``(tenantId, userId)`` 返回该用户可见的本体清单（含来源实体提示）。"""
    _require_service(service_token)
    resolved = await OntologyPermissionService().resolve_for_user(tenantId, userId)
    catalog = {
        str(item.get("ontologyId") or ""): item
        for item in await OntologyPermissionService().list_catalog(tenantId)
    }
    ontologies = []
    for ontology_id in resolved["ontologies"]:
        item = catalog.get(ontology_id) or {}
        ontologies.append(
            {
                "ontologyId": ontology_id,
                # 来源实体 / 主键字段来自业务系统清单副本（设计 §5.4）。
                # MOGO 侧当前只有索引聚合，故此处为空串，接入业务系统后填充。
                "sourceEntity": str(item.get("sourceEntity") or ""),
                "keyField": str(item.get("keyField") or ""),
                "entityTypes": list(item.get("entityTypes") or []),
            }
        )
    return {
        "tenantId": resolved["tenantId"],
        "userId": resolved["userId"],
        "count": resolved["count"],
        "ontologies": ontologies,
    }
