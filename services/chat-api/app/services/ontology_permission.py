"""本体数据权限 —— 运行时解析（设计四 §5.6.1）。

按 **mesc_* 方案**（`deploy/pg/ontology_permission.sql` + `deploy/mongo/ontology_permission.js`）
实现：给定 ``(tenant_id, user_id)``，解析出该用户**可见的本体清单**。

判定模型（对齐 mesc_* 表）：
- 主体四态 ``tenant / org / role / user``，由用户上下文展开：
  ``tenant_id`` + 该用户的组织（含下级，按 ``org_units.path_ids`` 展开）+ 该用户的岗位角色
  （``end_user_position_roles``）+ ``user_id`` 自身。
- 取命中的 ``mesc_ontology_grant`` 行，按 ``priority`` 大者胜（同优先级取**更严格**的
  ``access_mode``，fail-closed 偏置）；``access_mode ∈ {read, write}`` 即「可见」，
  ``none`` 即「不可见」。

边界（fail-closed）：
- 空 ``tenant_id`` / ``user_id`` → 返回**空集**（不查库）。
- 解析过程任何异常（DB 不可达、表不存在等）→ 返回**空集**，且**不写缓存**
  （避免把瞬时故障锁定 60s）；异常路径仍落一条审计。
- 进程内短 TTL 缓存（默认 60s），授权变更后按 ``(tenant_id, user_id)`` 失效。

数据访问（决策 A：原生 repository，不经 ``pg_compat`` 门面）：
- ``mesc_*`` 是**结构化表**（非通用壳），故原生访问：mongo 走 motor、PanWeiDB 走原生 SQL。
- 主体侧表（``end_user_org_relations`` / ``end_user_position_roles`` / ``org_units``）是
  通用壳表，走既有 ``get_db()`` 门面即可（两种后端都支持）。

审计：每次**实际解析**（缓存未命中）落一条 ``gate_events`` 事件，便于与业务系统对账。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Protocol

from app.core.config import get_settings
from app.core.db import get_db, is_panweidb_backend

logger = logging.getLogger(__name__)

# --- 集合 / 表名 ------------------------------------------------------------
GRANT_COLLECTION = "mesc_ontology_grant"
DETAIL_COLLECTION = "mesc_ontology_class_detail"
SYS_CONFIG_COLLECTION = "sys_config"
USER_ORG_REL_COLLECTION = "end_user_org_relations"
USER_ROLE_COLLECTION = "end_user_position_roles"
ORG_UNIT_COLLECTION = "org_units"
GATE_EVENTS_COLLECTION = "gate_events"

DEFAULT_CACHE_TTL_SECONDS = 60.0

#: 视为「可见」的 access_mode。
VISIBLE_ACCESS_MODES = frozenset({"read", "write"})

#: 同优先级冲突时的偏置：取 rank 更小者（none < read < write）= 更严格，fail-closed。
_MODE_RANK = {"none": 0, "read": 1, "write": 2}


@dataclass(frozen=True)
class SubjectSet:
    """一个用户展开后的主体集合（对应 mesc_* 的 subject_type/subject_id）。"""

    tenant_id: str
    user_id: str
    org_ids: frozenset[str] = frozenset()
    role_ids: frozenset[str] = frozenset()

    def subjects(self) -> tuple[tuple[str, str], ...]:
        rows: list[tuple[str, str]] = [("tenant", self.tenant_id)]
        rows += [("org", org_id) for org_id in sorted(self.org_ids)]
        rows += [("role", role_id) for role_id in sorted(self.role_ids)]
        rows += [("user", self.user_id)]
        return tuple(rows)


# ---------------------------------------------------------------------------
# 纯解析：主体集合 × 授权行 → 可见本体集合（可单测，无 DB）
# ---------------------------------------------------------------------------


def resolve_visible_ontologies(
    subjects: SubjectSet,
    grant_rows: Iterable[Mapping[str, Any]],
) -> frozenset[str]:
    """按 priority 合并授权行，返回可见的本体标识集合。

    - 仅保留命中该用户主体集合、且 ``enabled != False`` 的行。
    - 同一 ``ontology_uri`` 取 ``priority`` 最大者；同优先级取更严格的 ``access_mode``。
    - 最终仅保留 ``access_mode ∈ {read, write}`` 的本体。
    """
    subject_keys = set(subjects.subjects())
    best: dict[str, tuple[int, str]] = {}
    for row in grant_rows:
        key = (str(row.get("subject_type") or ""), str(row.get("subject_id") or ""))
        if key not in subject_keys:
            continue
        if row.get("enabled") is False:
            continue
        uri = str(row.get("ontology_uri") or "")
        if not uri:
            continue
        mode = str(row.get("access_mode") or "")
        try:
            priority = int(row.get("priority")) if row.get("priority") is not None else 100
        except (TypeError, ValueError):
            priority = 100
        current = best.get(uri)
        if current is None:
            best[uri] = (priority, mode)
            continue
        cur_priority, cur_mode = current
        if priority > cur_priority or (
            priority == cur_priority and _MODE_RANK.get(mode, 0) < _MODE_RANK.get(cur_mode, 0)
        ):
            best[uri] = (priority, mode)
    return frozenset(uri for uri, (_p, mode) in best.items() if mode in VISIBLE_ACCESS_MODES)


# ---------------------------------------------------------------------------
# 数据访问（可注入，便于单测）
# ---------------------------------------------------------------------------


class SubjectProvider(Protocol):
    async def load(self, tenant_id: str, user_id: str) -> SubjectSet: ...


class GrantStore(Protocol):
    async def fetch_grants(self, subjects: SubjectSet) -> list[Mapping[str, Any]]: ...


class AuditSink(Protocol):
    async def emit(self, event: Mapping[str, Any]) -> None: ...


class NativeSubjectProvider:
    """从通用壳表读取用户的组织（含下级）与岗位角色。"""

    async def load(self, tenant_id: str, user_id: str) -> SubjectSet:
        db = get_db()
        if db is None:
            raise RuntimeError("数据后端未初始化")
        org_ids: set[str] = set()
        org_rows = await db[USER_ORG_REL_COLLECTION].find(
            {"tenant_id": tenant_id, "user_id": user_id, "status": "active"}
        ).to_list(length=500)
        for row in org_rows:
            org_id = str(row.get("org_id") or "")
            if org_id:
                org_ids.add(org_id)
        if org_ids:
            # 组织含下级：org_units.path_ids 为祖先链，凡路径经过用户组织的即为其后代。
            unit_rows = await db[ORG_UNIT_COLLECTION].find(
                {"tenant_id": tenant_id, "status": "active"}
            ).to_list(length=2000)
            for unit in unit_rows:
                path = [str(item) for item in (unit.get("path_ids") or [])]
                if any(item in org_ids for item in path):
                    org_ids.add(str(unit.get("_id")))
        role_rows = await db[USER_ROLE_COLLECTION].find(
            {"tenant_id": tenant_id, "user_id": user_id, "status": "active"}
        ).to_list(length=500)
        role_ids = {
            str(row.get("role_id") or row.get("position_id"))
            for row in role_rows
            if (row.get("role_id") or row.get("position_id"))
        }
        return SubjectSet(
            tenant_id=tenant_id,
            user_id=user_id,
            org_ids=frozenset(org_ids),
            role_ids=frozenset(role_ids),
        )


class NativeGrantStore:
    """``mesc_ontology_grant`` 的原生访问（决策 A）：mongo motor / PanWeiDB 原生 SQL。"""

    async def fetch_grants(self, subjects: SubjectSet) -> list[Mapping[str, Any]]:
        if is_panweidb_backend():
            return await self._fetch_panweidb(subjects)
        return await self._fetch_mongo(subjects)

    async def _fetch_mongo(self, subjects: SubjectSet) -> list[Mapping[str, Any]]:
        db = get_db()
        if db is None:
            raise RuntimeError("数据后端未初始化")
        pairs = [
            {"subject_type": st, "subject_id": sid} for st, sid in subjects.subjects()
        ]
        if not pairs:
            return []
        query = {
            "tenant_id": subjects.tenant_id,
            "enabled": {"$ne": False},
            "$or": pairs,
        }
        return [doc async for doc in db[GRANT_COLLECTION].find(query)]

    async def _fetch_panweidb(self, subjects: SubjectSet) -> list[Mapping[str, Any]]:
        from app.core import pg as pg_mod

        pool = pg_mod.get_async_pool()
        if pool is None:
            raise RuntimeError("PanWeiDB 连接池尚未初始化")
        schema = get_settings().effective_panweidb_schema
        clauses: list[str] = []
        # 占位符顺序必须与文本出现顺序一致：tenant_id 先，随后逐主体对。
        params: list[Any] = [subjects.tenant_id]
        for st, sid in subjects.subjects():
            clauses.append("(subject_type = %s AND subject_id = %s)")
            params.extend([st, sid])
        where = " OR ".join(clauses) if clauses else "false"
        sql = (
            "SELECT subject_type, subject_id, ontology_uri, access_mode, priority "
            f'FROM "{schema}"."{GRANT_COLLECTION}" '
            f"WHERE tenant_id = %s AND enabled = true AND ({where})"
        )
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                rows = await cur.fetchall()
                columns = [desc.name for desc in (cur.description or [])]
        return [dict(zip(columns, row)) for row in rows]


class GateEventsAuditSink:
    """把解析事件写入 ``gate_events``（与既有门禁审计统一）。"""

    async def emit(self, event: Mapping[str, Any]) -> None:
        try:
            db = get_db()
            if db is None:
                return
            await db[GATE_EVENTS_COLLECTION].insert_one(dict(event))
        except Exception:  # noqa: BLE001 - 审计失败不得影响判权
            logger.debug("本体权限审计写入失败", exc_info=True)


# 可注入的默认实现（单测用 configure() 覆盖）。
_subject_provider: SubjectProvider = NativeSubjectProvider()
_grant_store: GrantStore = NativeGrantStore()
_audit_sink: AuditSink = GateEventsAuditSink()


def configure(
    *,
    subject_provider: SubjectProvider | None = None,
    grant_store: GrantStore | None = None,
    audit_sink: AuditSink | None = None,
) -> None:
    """覆盖默认实现（仅用于测试/嵌入式装配）。"""
    global _subject_provider, _grant_store, _audit_sink
    if subject_provider is not None:
        _subject_provider = subject_provider
    if grant_store is not None:
        _grant_store = grant_store
    if audit_sink is not None:
        _audit_sink = audit_sink


# ---------------------------------------------------------------------------
# 进程内 TTL 缓存
# ---------------------------------------------------------------------------

_cache: dict[tuple[str, str], tuple[float, frozenset[str]]] = {}
_cache_ttl: float = DEFAULT_CACHE_TTL_SECONDS


def _cache_get(key: tuple[str, str]) -> frozenset[str] | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    stamped_at, value = entry
    if time.monotonic() - stamped_at > _cache_ttl:
        _cache.pop(key, None)
        return None
    return value


def _cache_put(key: tuple[str, str], value: frozenset[str]) -> None:
    _cache[key] = (time.monotonic(), value)


def invalidate(tenant_id: str, user_id: str | None = None) -> None:
    """授权变更后失效缓存：给 ``user_id`` 只清该用户，否则清整个租户。"""
    tenant_id = str(tenant_id or "")
    if user_id is None:
        for key in [k for k in _cache if k[0] == tenant_id]:
            _cache.pop(key, None)
        return
    _cache.pop((tenant_id, str(user_id or "")), None)


def clear_cache() -> None:
    _cache.clear()


def set_cache_ttl(seconds: float) -> None:
    """调整 TTL（测试用）。"""
    global _cache_ttl
    _cache_ttl = float(seconds)


# ---------------------------------------------------------------------------
# 公开 API（设计四 §5.6.1）
# ---------------------------------------------------------------------------


async def visible_ontology_ids(
    tenant_id: str,
    user_id: str,
    *,
    use_cache: bool = True,
) -> frozenset[str]:
    """按 userId 取可见本体清单；fail-closed：查询失败返回空集。"""
    tenant_id = str(tenant_id or "")
    user_id = str(user_id or "")
    if not tenant_id or not user_id:
        return frozenset()

    key = (tenant_id, user_id)
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    try:
        subjects = await _subject_provider.load(tenant_id, user_id)
        rows = await _grant_store.fetch_grants(subjects)
        visible = resolve_visible_ontologies(subjects, rows)
    except Exception as exc:  # noqa: BLE001 - fail-closed：任何异常都退化为空集
        logger.warning("本体权限解析失败，按 fail-closed 返回空集：%s", exc)
        await _emit_audit(tenant_id, user_id, frozenset(), error=True)
        return frozenset()

    _cache_put(key, visible)
    await _emit_audit(tenant_id, user_id, visible)
    return visible


async def ontology_scope_snapshot(tenant_id: str, user_id: str) -> dict[str, Any]:
    """给审计/上下文用的快照。"""
    tenant_id = str(tenant_id or "")
    user_id = str(user_id or "")
    visible = await visible_ontology_ids(tenant_id, user_id)
    return {
        "tenantId": tenant_id,
        "userId": user_id,
        "ontologies": sorted(visible),
        "count": len(visible),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


async def _emit_audit(
    tenant_id: str,
    user_id: str,
    visible: frozenset[str],
    *,
    error: bool = False,
) -> None:
    event = {
        "event_id": uuid.uuid4().hex,
        "occurred_at": datetime.now(timezone.utc),
        "tenant_id": tenant_id,
        "user_id": user_id,
        "roles": [],
        "tool": "ontology.permission.resolve",
        "risk_level": "",
        "autonomy_level": "",
        "decision": "deny" if error else "allow",
        "layer": "ontology_permission",
        "reason": (
            "resolve failed (fail-closed)"
            if error
            else f"{len(visible)} ontologies visible"
        ),
        "detail": {"ontologies": sorted(visible), "count": len(visible), "error": error},
    }
    await _audit_sink.emit(event)


__all__ = [
    "DEFAULT_CACHE_TTL_SECONDS",
    "GRANT_COLLECTION",
    "SubjectSet",
    "VISIBLE_ACCESS_MODES",
    "clear_cache",
    "configure",
    "invalidate",
    "ontology_scope_snapshot",
    "resolve_visible_ontologies",
    "set_cache_ttl",
    "visible_ontology_ids",
]
