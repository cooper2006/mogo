"""本体数据权限 —— 原生 repository（决策 A：结构化列，不经 ``pg_compat`` 门面）。

两种后端同形实现：

* ``mongo``   → motor，集合名与 PG 表名一致，``_id`` 由复合键确定性拼接。
* ``panweidb``→ psycopg3 异步池 + 原生 SQL（``app/core/pg.py::get_async_pool``）。

**为什么不用 ``get_db()`` 门面**：``app/core/pg_compat.py`` 假定每张表都是通用壳
``(id TEXT PK, tenant_id TEXT, doc JSONB, created_at, updated_at)``；``mesc_*`` 与
``sys_config`` 都是**结构化列**（复合主键、CHECK、jsonb 子列），门面无法表达。
见 ``docs/ontology-permission-merge-plan.md`` §3.8。

PanWeiDB（openGauss 内核 / ``sql_compatibility=A``）实测约束，本文件已规避：

* ``''`` 等价于 NULL —— 空串比较会静默变 NULL，故**不写** ``<> ''`` 这类判断。
* ``ON CONFLICT ... DO UPDATE`` 兼容性不稳 —— upsert 统一走 **先 UPDATE、rowcount=0 再 INSERT**
  （INSERT 撞唯一键时退化为 UPDATE 重试）。
* 占位符 ``%s`` 按位置绑定 —— 参数追加顺序必须与 SQL 文本出现顺序一致。
* jsonb 路径必须用 ``#>`` / ``#>>``（``->`` / ``->>`` 右遇 ``{a,b}`` 字面量会静默取 NULL）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from app.core.config import settings
from app.core.db import get_db, is_panweidb_backend

from .constants import (
    AUDIT_TABLE,
    DEFAULT_SYS_CONFIG,
    DETAIL_TABLE,
    ENTITY_INDEX_TABLE,
    GRANT_TABLE,
    SYS_CONFIG_KEY,
    SYS_CONFIG_TABLE,
    detail_key,
    grant_key,
)

logger = logging.getLogger(__name__)

#: 允许写入的结构化列（白名单，防注入与误写）。
_GRANT_COLUMNS = (
    "tenant_id",
    "subject_type",
    "subject_id",
    "ontology_uri",
    "access_mode",
    "priority",
    "enabled",
    "remark",
)
_DETAIL_COLUMNS = (
    "tenant_id",
    "subject_type",
    "subject_id",
    "ontology_uri",
    "class_name",
    "access_mode",
    "column_mode",
    "column_list",
    "row_condition",
    "priority",
    "enabled",
    "remark",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _schema() -> str:
    return settings.effective_panweidb_schema


def _jsonb(value: Any) -> Any:
    """把 dict/list 包成 psycopg 的 ``Jsonb``（否则报 cannot adapt type 'dict'）。

    psycopg3 **不会**自动把 Python dict/list 适配到 jsonb 占位符，必须显式包装；
    读取侧（``jsonb`` → Python）则是自动的。``None`` 保持 NULL（``row_condition`` 语义）。
    """
    if value is None:
        return None
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _tbl(name: str) -> str:
    return f'"{_schema()}"."{name}"'


async def _pool() -> Any:
    from app.core import pg as pg_mod

    pool = pg_mod.get_async_pool()
    if pool is None:
        # 惰性兜底：异步池未初始化时按需建立（正常路径由启动钩子建好）。
        pool = await pg_mod.init_async_pg()
    if pool is None:
        raise RuntimeError("PanWeiDB 连接池尚未初始化")
    return pool


class OntologyPermissionRepository:
    """本体授权 / 类明细 / 变更审计 / 全局开关 / 清单 的统一数据访问。"""

    def __init__(self, db: Any | None = None) -> None:
        self._db_override = db

    # ------------------------------------------------------------------ 基础

    def _db(self) -> Any:
        db = self._db_override if self._db_override is not None else get_db()
        if db is None:
            raise RuntimeError("数据后端未初始化")
        return db

    def _pg(self) -> bool:
        return is_panweidb_backend() if self._db_override is None else False

    # ------------------------------------------------------------------ 授权行

    async def list_grants(
        self,
        tenant_id: str,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        ontology_uri: str | None = None,
        enabled_only: bool = False,
    ) -> list[dict[str, Any]]:
        """按可选条件列出授权行（按主体与本体排序，结果稳定）。"""
        if self._pg():
            return await self._pg_list_grants(
                tenant_id,
                subject_type=subject_type,
                subject_id=subject_id,
                ontology_uri=ontology_uri,
                enabled_only=enabled_only,
            )
        query: dict[str, Any] = {"tenant_id": str(tenant_id)}
        if subject_type:
            query["subject_type"] = str(subject_type)
        if subject_id:
            query["subject_id"] = str(subject_id)
        if ontology_uri:
            query["ontology_uri"] = str(ontology_uri)
        if enabled_only:
            query["enabled"] = {"$ne": False}
        cursor = self._db()[GRANT_TABLE].find(query).sort(
            [("subject_type", 1), ("subject_id", 1), ("ontology_uri", 1)]
        )
        return [doc async for doc in cursor]

    async def list_grants_for_subjects(
        self, tenant_id: str, subjects: Sequence[tuple[str, str]]
    ) -> list[dict[str, Any]]:
        """批量取某用户展开出的主体集合命中的授权行（判权热路径）。"""
        pairs = [(str(st), str(sid)) for st, sid in subjects]
        if not pairs:
            return []
        if self._pg():
            clauses: list[str] = []
            params: list[Any] = [str(tenant_id)]
            for st, sid in pairs:
                clauses.append("(subject_type = %s AND subject_id = %s)")
                params.extend([st, sid])
            where = " OR ".join(clauses)
            sql = (
                "SELECT tenant_id, subject_type, subject_id, ontology_uri, access_mode, "
                "priority, enabled, remark, created_at, updated_at "
                f"FROM {_tbl(GRANT_TABLE)} "
                f"WHERE tenant_id = %s AND enabled = true AND ({where})"
            )
            return await self._fetch(sql, params)
        query = {
            "tenant_id": str(tenant_id),
            "enabled": {"$ne": False},
            "$or": [{"subject_type": st, "subject_id": sid} for st, sid in pairs],
        }
        cursor = self._db()[GRANT_TABLE].find(query)
        return [doc async for doc in cursor]

    async def upsert_grant(self, row: Mapping[str, Any]) -> dict[str, Any]:
        payload = {key: row.get(key) for key in _GRANT_COLUMNS}
        payload["tenant_id"] = str(payload.get("tenant_id") or "")
        payload["subject_type"] = str(payload.get("subject_type") or "")
        payload["subject_id"] = str(payload.get("subject_id") or "")
        payload["ontology_uri"] = str(payload.get("ontology_uri") or "")
        payload["access_mode"] = str(payload.get("access_mode") or "none")
        payload["priority"] = int(payload.get("priority") or 100)
        # ⚠ 不能用 `payload.get("enabled", True)`：上游 dict **含** "enabled" 键且值为 None 时
        # （调用方省略该字段的常见形态），.get 返回 None 而非 True，bool(None)=False 会把
        # 授权静默写成「已禁用」，随后被 enabled = true / {$ne: False} 全部滤掉 ——
        # mongo 后端等价冒烟正是这样抓到本 bug 的。None 一律按「启用」处理。
        raw_enabled = row.get("enabled")
        payload["enabled"] = True if raw_enabled is None else bool(raw_enabled)
        if payload.get("remark") is None:
            payload["remark"] = None

        if self._pg():
            key_cols = ("tenant_id", "subject_type", "subject_id", "ontology_uri")
            set_cols = ("access_mode", "priority", "enabled", "remark")
            # ⚠ 占位符纪律：参数顺序必须与 SQL 文本出现顺序一致 ——
            # 文本是 `SET <set_cols> ... WHERE <key_cols>`，故先 set 再 key。
            update_params: list[Any] = [payload[col] for col in set_cols]
            update_params += [payload[col] for col in key_cols]
            update_sql = (
                f"UPDATE {_tbl(GRANT_TABLE)} SET "
                + ", ".join(f"{col} = %s" for col in set_cols)
                + ", updated_at = now() WHERE "
                + " AND ".join(f"{col} = %s" for col in key_cols)
            )
            insert_cols = list(_GRANT_COLUMNS)
            insert_sql = (
                f"INSERT INTO {_tbl(GRANT_TABLE)} ("
                + ", ".join(insert_cols)
                + ") VALUES ("
                + ", ".join("%s" for _ in insert_cols)
                + ")"
            )
            pool = await _pool()
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(update_sql, update_params)
                    if cur.rowcount == 0:
                        await cur.execute(insert_sql, [payload[col] for col in insert_cols])
            return payload

        doc = dict(payload)
        doc["_id"] = grant_key(
            payload["tenant_id"],
            payload["subject_type"],
            payload["subject_id"],
            payload["ontology_uri"],
        )
        now = utcnow()
        await self._db()[GRANT_TABLE].replace_one(
            {"_id": doc["_id"]},
            {**doc, "created_at": now, "updated_at": now},
            upsert=True,
        )
        return doc

    async def delete_grant(
        self, tenant_id: str, subject_type: str, subject_id: str, ontology_uri: str
    ) -> int:
        if self._pg():
            sql = (
                f"DELETE FROM {_tbl(GRANT_TABLE)} "
                "WHERE tenant_id = %s AND subject_type = %s AND subject_id = %s "
                "AND ontology_uri = %s"
            )
            pool = await _pool()
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, [tenant_id, subject_type, subject_id, ontology_uri])
                    return int(cur.rowcount or 0)
        result = await self._db()[GRANT_TABLE].delete_one(
            {
                "_id": grant_key(tenant_id, subject_type, subject_id, ontology_uri),
                "tenant_id": str(tenant_id),
            }
        )
        return int(getattr(result, "deleted_count", 0) or 0)

    async def _pg_list_grants(
        self,
        tenant_id: str,
        *,
        subject_type: str | None,
        subject_id: str | None,
        ontology_uri: str | None,
        enabled_only: bool,
    ) -> list[dict[str, Any]]:
        clauses = ["tenant_id = %s"]
        params: list[Any] = [str(tenant_id)]
        if subject_type:
            clauses.append("subject_type = %s")
            params.append(str(subject_type))
        if subject_id:
            clauses.append("subject_id = %s")
            params.append(str(subject_id))
        if ontology_uri:
            clauses.append("ontology_uri = %s")
            params.append(str(ontology_uri))
        if enabled_only:
            clauses.append("enabled = true")
        sql = (
            "SELECT tenant_id, subject_type, subject_id, ontology_uri, access_mode, "
            "priority, enabled, remark, created_at, updated_at "
            f"FROM {_tbl(GRANT_TABLE)} WHERE " + " AND ".join(clauses)
            + " ORDER BY subject_type, subject_id, ontology_uri"
        )
        return await self._fetch(sql, params)

    # ------------------------------------------------------------------ 类明细

    async def list_details(
        self,
        tenant_id: str,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        ontology_uri: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._pg():
            clauses = ["tenant_id = %s"]
            params: list[Any] = [str(tenant_id)]
            if subject_type:
                clauses.append("subject_type = %s")
                params.append(str(subject_type))
            if subject_id:
                clauses.append("subject_id = %s")
                params.append(str(subject_id))
            if ontology_uri:
                clauses.append("ontology_uri = %s")
                params.append(str(ontology_uri))
            sql = (
                "SELECT tenant_id, subject_type, subject_id, ontology_uri, class_name, "
                "access_mode, column_mode, column_list, row_condition, priority, enabled, "
                "remark, created_at, updated_at "
                f"FROM {_tbl(DETAIL_TABLE)} WHERE " + " AND ".join(clauses)
                + " ORDER BY subject_type, subject_id, ontology_uri, class_name"
            )
            return await self._fetch(sql, params)
        query: dict[str, Any] = {"tenant_id": str(tenant_id)}
        if subject_type:
            query["subject_type"] = str(subject_type)
        if subject_id:
            query["subject_id"] = str(subject_id)
        if ontology_uri:
            query["ontology_uri"] = str(ontology_uri)
        cursor = self._db()[DETAIL_TABLE].find(query).sort(
            [("subject_type", 1), ("subject_id", 1), ("ontology_uri", 1), ("class_name", 1)]
        )
        return [doc async for doc in cursor]

    async def upsert_detail(self, row: Mapping[str, Any]) -> dict[str, Any]:
        payload = {key: row.get(key) for key in _DETAIL_COLUMNS}
        for col in ("tenant_id", "subject_type", "subject_id", "ontology_uri", "class_name"):
            payload[col] = str(payload.get(col) or "")
        payload["access_mode"] = str(payload.get("access_mode") or "inherit")
        payload["column_mode"] = str(payload.get("column_mode") or "all")
        payload["column_list"] = list(payload.get("column_list") or [])
        payload["priority"] = int(payload.get("priority") or 100)
        # 同 upsert_grant：None 一律按「启用」，避免省略该字段时被静默禁用。
        raw_enabled = row.get("enabled")
        payload["enabled"] = True if raw_enabled is None else bool(raw_enabled)

        if self._pg():
            key_cols = ("tenant_id", "subject_type", "subject_id", "ontology_uri", "class_name")
            set_cols = (
                "access_mode",
                "column_mode",
                "column_list",
                "row_condition",
                "priority",
                "enabled",
                "remark",
            )
            # ⚠ 占位符纪律：文本是 `SET <set_cols> ... WHERE <key_cols>`，故先 set 再 key。
            # ⚠ jsonb 列（column_list / row_condition）必须包 Jsonb。
            update_params: list[Any] = [
                _jsonb(payload[col]) if col in ("column_list", "row_condition") else payload[col]
                for col in set_cols
            ]
            update_params += [payload[col] for col in key_cols]
            update_sql = (
                f"UPDATE {_tbl(DETAIL_TABLE)} SET "
                + ", ".join(f"{col} = %s" for col in set_cols)
                + ", updated_at = now() WHERE "
                + " AND ".join(f"{col} = %s" for col in key_cols)
            )
            insert_cols = list(_DETAIL_COLUMNS)
            insert_sql = (
                f"INSERT INTO {_tbl(DETAIL_TABLE)} ("
                + ", ".join(insert_cols)
                + ") VALUES ("
                + ", ".join("%s" for _ in insert_cols)
                + ")"
            )
            pool = await _pool()
            async with pool.connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(update_sql, update_params)
                    if cursor.rowcount == 0:
                        await cursor.execute(
                            insert_sql,
                            [
                                _jsonb(payload[col])
                                if col in ("column_list", "row_condition")
                                else payload[col]
                                for col in insert_cols
                            ],
                        )
            return payload

        doc = dict(payload)
        doc["_id"] = detail_key(
            payload["tenant_id"],
            payload["subject_type"],
            payload["subject_id"],
            payload["ontology_uri"],
            payload["class_name"],
        )
        now = utcnow()
        await self._db()[DETAIL_TABLE].replace_one(
            {"_id": doc["_id"]},
            {**doc, "created_at": now, "updated_at": now},
            upsert=True,
        )
        return doc

    async def delete_detail(
        self,
        tenant_id: str,
        subject_type: str,
        subject_id: str,
        ontology_uri: str,
        class_name: str,
    ) -> int:
        if self._pg():
            sql = (
                f"DELETE FROM {_tbl(DETAIL_TABLE)} "
                "WHERE tenant_id = %s AND subject_type = %s AND subject_id = %s "
                "AND ontology_uri = %s AND class_name = %s"
            )
            pool = await _pool()
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        sql, [tenant_id, subject_type, subject_id, ontology_uri, class_name]
                    )
                    return int(cur.rowcount or 0)
        result = await self._db()[DETAIL_TABLE].delete_one(
            {
                "_id": detail_key(tenant_id, subject_type, subject_id, ontology_uri, class_name),
                "tenant_id": str(tenant_id),
            }
        )
        return int(getattr(result, "deleted_count", 0) or 0)

    # ------------------------------------------------------------------ 审计

    async def write_audit(
        self,
        *,
        tenant_id: str,
        actor: str,
        action: str,
        target_kind: str,
        target_key: str,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        """配置变更审计（运行时判定仍落 ``gate_events``，不双写 —— merge-plan §3.6）。"""
        if self._pg():
            sql = (
                f"INSERT INTO {_tbl(AUDIT_TABLE)} "
                "(tenant_id, actor, action, target_kind, target_key, detail) "
                "VALUES (%s, %s, %s, %s, %s, %s)"
            )
            pool = await _pool()
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        sql,
                        [
                            tenant_id or None,
                            actor or None,
                            action,
                            target_kind,
                            target_key or None,
                            _jsonb(dict(detail)) if detail else None,
                        ],
                    )
            return
        await self._db()[AUDIT_TABLE].insert_one(
            {
                "ts": utcnow(),
                "tenant_id": tenant_id or None,
                "actor": actor or None,
                "action": action,
                "target_kind": target_kind,
                "target_key": target_key or None,
                "detail": dict(detail) if detail else None,
            }
        )

    async def list_audit(self, tenant_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        if self._pg():
            sql = (
                "SELECT id, ts, tenant_id, actor, action, target_kind, target_key, detail "
                f"FROM {_tbl(AUDIT_TABLE)} WHERE tenant_id = %s ORDER BY ts DESC LIMIT %s"
            )
            return await self._fetch(sql, [str(tenant_id), int(limit)])
        cursor = (
            self._db()[AUDIT_TABLE]
            .find({"tenant_id": str(tenant_id)})
            .sort([("ts", -1)])
            .limit(int(limit))
        )
        return [doc async for doc in cursor]

    # ------------------------------------------------------------------ 全局开关

    async def get_sys_config(self, key: str = SYS_CONFIG_KEY) -> dict[str, Any]:
        """读配置；缺行时返回缺省值（不落库）。"""
        if self._pg():
            rows = await self._fetch(
                f"SELECT value FROM {_tbl(SYS_CONFIG_TABLE)} WHERE key = %s", [str(key)]
            )
            value = rows[0].get("value") if rows else None
        else:
            doc = await self._db()[SYS_CONFIG_TABLE].find_one({"_id": str(key)})
            value = (doc or {}).get("value")
        merged = dict(DEFAULT_SYS_CONFIG)
        if isinstance(value, Mapping):
            merged.update({str(k): v for k, v in value.items()})
        return merged

    async def set_sys_config(self, value: Mapping[str, Any], key: str = SYS_CONFIG_KEY) -> dict[str, Any]:
        """整体覆盖配置值（先 UPDATE、rowcount=0 再 INSERT）。"""
        payload = dict(value)
        if self._pg():
            pool = await _pool()
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        f"UPDATE {_tbl(SYS_CONFIG_TABLE)} SET value = %s, updated_at = now() "
                        "WHERE key = %s",
                        [_jsonb(payload), str(key)],
                    )
                    if cur.rowcount == 0:
                        await cur.execute(
                            f"INSERT INTO {_tbl(SYS_CONFIG_TABLE)} (key, value) VALUES (%s, %s)",
                            [str(key), _jsonb(payload)],
                        )
            return payload
        now = utcnow()
        await self._db()[SYS_CONFIG_TABLE].replace_one(
            {"_id": str(key)},
            {"_id": str(key), "value": payload, "created_at": now, "updated_at": now},
            upsert=True,
        )
        return payload

    # ------------------------------------------------------------------ 本体清单

    async def list_catalog(self, tenant_id: str) -> list[dict[str, Any]]:
        """聚合既有业务实体索引里的 ``ontology_id``，形成 MOGO 侧只读本体清单。

        设计 §5.4：本体定义与数据都在业务系统，MOGO 只做展示。当前唯一可用的
        MOGO 侧来源是 ``business_entity_index``（通用壳表，字段在 ``doc`` 里）。
        """
        if self._pg():
            # A 模式：jsonb 路径必须 #>>；空串等价 NULL，故只需 IS NOT NULL。
            sql = (
                "SELECT doc #>> '{ontology_id}' AS ontology_id, "
                "count(*) AS entity_count, "
                "array_agg(DISTINCT doc #>> '{entity_type}') AS entity_types "
                f"FROM {_tbl(ENTITY_INDEX_TABLE)} "
                "WHERE tenant_id = %s AND (doc #>> '{ontology_id}') IS NOT NULL "
                "GROUP BY doc #>> '{ontology_id}' ORDER BY 1"
            )
            rows = await self._fetch(sql, [str(tenant_id)])
            return [
                {
                    "ontology_id": str(row.get("ontology_id") or ""),
                    "entity_count": int(row.get("entity_count") or 0),
                    "entity_types": sorted(str(t) for t in (row.get("entity_types") or []) if t),
                }
                for row in rows
            ]
        pipeline = [
            {"$match": {"tenant_id": str(tenant_id), "ontology_id": {"$nin": [None, ""]}}},
            {
                "$group": {
                    "_id": "$ontology_id",
                    "entity_count": {"$sum": 1},
                    "entity_types": {"$addToSet": "$entity_type"},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        cursor = self._db()[ENTITY_INDEX_TABLE].aggregate(pipeline)
        rows = [doc async for doc in cursor]
        return [
            {
                "ontology_id": str(row.get("_id") or ""),
                "entity_count": int(row.get("entity_count") or 0),
                "entity_types": sorted(str(t) for t in (row.get("entity_types") or []) if t),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------ 通用查询

    async def _fetch(self, sql: str, params: Iterable[Any]) -> list[dict[str, Any]]:
        pool = await _pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, list(params))
                rows = await cur.fetchall()
                columns = [desc.name for desc in (cur.description or [])]
        return [dict(zip(columns, row)) for row in rows]


__all__ = ["OntologyPermissionRepository", "utcnow"]
