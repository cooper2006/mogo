"""本体清单与个人本体授权 —— 终端用户侧接口（admin-web 本体页的 user-web 迁移）。

设计来源：``specs/030-ontology-data-permission`` FR-025（admin-web 侧已有对应页面），
以及用户侧「查看个人用户的可见本体授权」诉求。

与 admin-api ``/api/ontologies/*`` 的分工：

* **本模块（chat-api，端用户身份）**：只回答「我」能看什么 —— ``GET /api/ontology-grants/mine``。
  主体集合 = tenant 兜底 + 用户自身（与 admin-api ``visible_ontologies`` 同源口径），
  不展开 org/role：端用户页只做自我告知，判权热路径在
  ``app/services/ontology_permission.py`` 的 ``visible_ontology_ids``（四态展开）。
* **admin-api（管理员身份）**：全量清单、开关、按用户/四态主体的授权读写与审计。

只读设计：本模块**不提供任何写操作**（本体授权是管理端职责，与设计 FR-024「本体清单只做展示」
同源）。写入口仍走 admin-api。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.principal import ApiPrincipal, require_end_user_principal
from app.core.db import get_db, is_panweidb_backend
from app.core.config import get_settings
from app.services import ontology_permission as ontology_permission_runtime

router = APIRouter(prefix="/api/ontology-grants", dependencies=[Depends(require_end_user_principal)])

#: 授权表（与运行时解析、admin-api 侧同表）。
GRANT_TABLE = ontology_permission_runtime.GRANT_COLLECTION

#: 视为「可见」的 access_mode（与 admin-api 同口径）。
VISIBLE_ACCESS_MODES = ontology_permission_runtime.VISIBLE_ACCESS_MODES

#: 同优先级冲突时取 rank 更小者（none < read < write）= 更严格，fail-closed。
_MODE_RANK = {"none": 0, "read": 1, "write": 2}


def _mode_rank(mode: str) -> int:
    return _MODE_RANK.get(mode, 0)


async def _fetch_subject_grant_rows(tenant_id: str, user_id: str) -> list[dict[str, Any]]:
    """取命中 ``tenant`` 兜底与 ``user`` 自身的授权行（双后端：mongo motor / PanWeiDB 原生 SQL）。"""
    subjects: list[tuple[str, str]] = [("tenant", tenant_id), ("user", user_id)]
    if is_panweidb_backend():
        from app.core import pg as pg_mod

        pool = pg_mod.get_async_pool()
        if pool is None:
            raise RuntimeError("PanWeiDB 连接池尚未初始化")
        schema = get_settings().effective_panweidb_schema
        clauses = ["(subject_type = %s AND subject_id = %s)"] * len(subjects)
        params: list[Any] = [tenant_id]
        for st, sid in subjects:
            params.extend([st, sid])
        sql = (
            "SELECT subject_type, subject_id, ontology_uri, access_mode, priority, enabled, remark, updated_at "
            f'FROM "{schema}"."{GRANT_TABLE}" '
            f"WHERE tenant_id = %s AND ({' OR '.join(clauses)})"
        )
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                rows = await cur.fetchall()
                columns = [desc.name for desc in (cur.description or [])]
        return [dict(zip(columns, row)) for row in rows]

    db = get_db()
    if db is None:
        raise RuntimeError("数据后端未初始化")
    cursor = db[GRANT_TABLE].find(
        {
            "tenant_id": tenant_id,
            "$or": [{"subject_type": st, "subject_id": sid} for st, sid in subjects],
        }
    )
    return [doc async for doc in cursor]


def _merge_subject_grants(
    tenant_id: str,
    user_id: str,
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """把命中主体的授权行合并成「每本体一条」的结果。

    - 命中主体：``tenant`` 兜底 + 该用户自身（不含 org/role，见模块 docstring）。
    - 同一本体取 ``priority`` 最大者；同优先级取更严格的 ``access_mode``。
    - ``enabled is False`` 的行视为不存在，只计入 ``disabled`` 计数（供前端提示）。
    """
    subject_keys = {("tenant", str(tenant_id)), ("user", str(user_id))}
    best: dict[str, dict[str, Any]] = {}
    disabled = 0
    for row in rows:
        key = (str(row.get("subject_type") or ""), str(row.get("subject_id") or ""))
        if key not in subject_keys:
            continue
        uri = str(row.get("ontology_uri") or "")
        if not uri:
            continue
        if row.get("enabled") is False:
            disabled += 1
            continue
        mode = str(row.get("access_mode") or "")
        try:
            priority = int(row.get("priority")) if row.get("priority") is not None else 100
        except (TypeError, ValueError):
            priority = 100
        current = best.get(uri)
        candidate = {
            "ontologyId": uri,
            "accessMode": mode,
            "priority": priority,
            "subjectType": key[0],
            "remark": str(row.get("remark") or ""),
            "updatedAt": row.get("updated_at"),
        }
        if current is None:
            best[uri] = candidate
            continue
        if priority > int(current["priority"]) or (
            priority == int(current["priority"]) and _mode_rank(mode) < _mode_rank(str(current["accessMode"]))
        ):
            best[uri] = candidate

    items = [
        {**item, "visible": str(item["accessMode"]) in VISIBLE_ACCESS_MODES}
        for item in sorted(best.values(), key=lambda item: str(item["ontologyId"]))
    ]
    return items, disabled


@router.get("/mine")
async def list_my_ontology_grants(
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, Any]:
    """当前登录用户可见的本体授权（tenant 兜底 + 用户自身）。

    查询失败时返回空清单与 ``degraded=true``：本页只做自我告知，不阻断用户其它操作，
    与运行时解析的 fail-closed（判权路径，``visible_ontology_ids``）语义不同。
    """
    tenant_id = str(principal.tenant_id or "")
    user_id = str(principal.user_id or "")
    empty = {
        "tenantId": tenant_id,
        "userId": user_id,
        "ontologies": [],
        "count": 0,
        "visibleCount": 0,
        "disabledCount": 0,
        "degraded": False,
    }
    if not tenant_id or not user_id:
        return empty

    try:
        rows = await _fetch_subject_grant_rows(tenant_id, user_id)
    except Exception:  # noqa: BLE001 - 展示页降级，不得影响用户其它操作
        empty["degraded"] = True
        return empty

    merged, disabled = _merge_subject_grants(tenant_id, user_id, rows)
    return {
        "tenantId": tenant_id,
        "userId": user_id,
        "ontologies": merged,
        "count": len(merged),
        "visibleCount": sum(1 for item in merged if item["visible"]),
        "disabledCount": disabled,
        "degraded": False,
    }
