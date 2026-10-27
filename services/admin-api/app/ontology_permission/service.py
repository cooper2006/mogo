"""本体数据权限 —— 服务层（admin-api）。

职责：
1. **配置**：读写 ``sys_config['ontology-permission']``（``enforce`` 开关 + ``rev`` 版本号）。
2. **清单**：聚合 MOGO 侧只读本体清单（来源：业务实体索引）。
3. **可见集**：给定 ``(tenant_id, user_id)`` 解析可见本体（判权算法与 chat-api 运行时同源）。
4. **授权写入侧**：批量授予 / 撤销 ``mesc_ontology_grant``（``subject_type='user'``），
   同步写 ``mesc_ontology_perm_audit`` 并递增 ``rev``。

判权算法说明：``resolve_visible_ontologies`` 是 chat-api
``app/services/ontology_permission.py`` 中同名纯函数的**镜像**（两服务各自独立部署，
无法互相 import）。改动任一处必须同步另一处，测试见
``services/admin-api/tests/test_ontology_permission_service.py``。
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping, Sequence

from fastapi import HTTPException, status

from .constants import (
    ACCESS_MODES,
    DEFAULT_SYS_CONFIG,
    DETAIL_ACCESS_MODES,
    SYS_CONFIG_KEY,
    detail_key,
    enabled_flag,
    grant_key,
)
from .repository import OntologyPermissionRepository, utcnow
from .subjects import SubjectExpander

logger = logging.getLogger(__name__)

#: 视为「可见」的 access_mode。
VISIBLE_ACCESS_MODES = frozenset({"read", "write"})

#: 同优先级冲突时取 rank 更小者（none < read < write）= 更严格，fail-closed。
_MODE_RANK = {"none": 0, "read": 1, "write": 2}


def resolve_visible_ontologies(
    subjects: Iterable[tuple[str, str]],
    grant_rows: Iterable[Mapping[str, Any]],
) -> frozenset[str]:
    """按 priority 合并授权行，返回可见的本体标识集合（fail-closed）。

    - 仅保留命中主体集合、且 ``enabled`` 为真的行（``enabled`` 在 mongo 是 bool、
      在 PanWeiDB 是 SMALLINT 1/0，统一经 ``enabled_flag`` 归一化）。
    - 同一 ``ontology_uri`` 取 ``priority`` 最大者；同优先级取更严格的 ``access_mode``。
    - 最终仅保留 ``access_mode ∈ {read, write}`` 的本体。
    """
    subject_keys = {(str(st), str(sid)) for st, sid in subjects}
    best: dict[str, tuple[int, str]] = {}
    for row in grant_rows:
        key = (str(row.get("subject_type") or ""), str(row.get("subject_id") or ""))
        if key not in subject_keys:
            continue
        if not enabled_flag(row.get("enabled")):
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


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            return str(value)
    return str(value)


class OntologyPermissionService:
    def __init__(self, repository: OntologyPermissionRepository | None = None) -> None:
        self.repo = repository or OntologyPermissionRepository()

    # ------------------------------------------------------------------ 配置

    async def get_config(self) -> dict[str, Any]:
        value = await self.repo.get_sys_config(SYS_CONFIG_KEY)
        return {
            "enforce": bool(value.get("enforce", False)),
            # enforce=true 时缺省判定固定为 deny（决策③）；defaultMode 仅作预演口径展示。
            "defaultMode": str(value.get("defaultMode") or DEFAULT_SYS_CONFIG["defaultMode"]),
            "rev": int(value.get("rev") or 0),
            "effectiveDefault": "deny" if value.get("enforce") else str(
                value.get("defaultMode") or DEFAULT_SYS_CONFIG["defaultMode"]
            ),
        }

    async def set_enforce(
        self, *, tenant_id: str, actor: str, enforce: bool, default_mode: str | None = None
    ) -> dict[str, Any]:
        if default_mode is not None and default_mode not in {"allow", "deny"}:
            raise HTTPException(status_code=422, detail="invalid_default_mode")
        current = await self.repo.get_sys_config(SYS_CONFIG_KEY)
        payload = {
            "enforce": bool(enforce),
            "defaultMode": str(default_mode or current.get("defaultMode") or "allow"),
            "rev": int(current.get("rev") or 0) + 1,
        }
        await self.repo.set_sys_config(payload, SYS_CONFIG_KEY)
        await self._audit(
            tenant_id=tenant_id,
            actor=actor,
            action="enforce_toggle",
            target_kind="config",
            target_key=SYS_CONFIG_KEY,
            detail={"enforce": payload["enforce"], "defaultMode": payload["defaultMode"]},
        )
        return await self.get_config()

    # ------------------------------------------------------------------ 清单

    async def list_catalog(self, tenant_id: str) -> list[dict[str, Any]]:
        """只读本体清单：索引中出现的 ``ontology_id`` + 已配置授权数（对外 camelCase）。"""
        catalog = await self.repo.list_catalog(tenant_id)
        grants = await self.repo.list_grants(tenant_id)
        granted: dict[str, int] = {}
        for row in grants:
            uri = str(row.get("ontology_uri") or "")
            if uri:
                granted[uri] = granted.get(uri, 0) + 1
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in catalog:
            ontology_id = str(entry.get("ontology_id") or "")
            if not ontology_id or ontology_id in seen:
                continue
            seen.add(ontology_id)
            items.append(
                {
                    "ontologyId": ontology_id,
                    "entityCount": int(entry.get("entity_count") or 0),
                    "entityTypes": [str(t) for t in (entry.get("entity_types") or [])],
                    "grantCount": int(granted.get(ontology_id, 0)),
                }
            )
        # 已授权但索引里还没出现的本体也要展示（否则授权页看不到目标）。
        for uri, count in granted.items():
            if uri in seen:
                continue
            seen.add(uri)
            items.append(
                {"ontologyId": uri, "entityCount": 0, "entityTypes": [], "grantCount": int(count)}
            )
        items.sort(key=lambda item: str(item["ontologyId"]))
        return items

    async def visible_ontologies(self, tenant_id: str, user_id: str) -> dict[str, Any]:
        """当前账号可见的本体（展示用）。主体集合 = tenant 兜底 + 该账号自身。"""
        tenant_id = str(tenant_id or "")
        user_id = str(user_id or "")
        if not tenant_id or not user_id:
            return {"ontologies": [], "count": 0, "tenantId": tenant_id, "userId": user_id}
        subjects = [("tenant", tenant_id), ("user", user_id)]
        rows = await self.repo.list_grants_for_subjects(tenant_id, subjects)
        visible = resolve_visible_ontologies(subjects, rows)
        return {
            "tenantId": tenant_id,
            "userId": user_id,
            "ontologies": sorted(visible),
            "count": len(visible),
        }

    async def resolve_for_user(
        self, tenant_id: str, user_id: str, *, expander: "SubjectExpander | None" = None
    ) -> dict[str, Any]:
        """解析**端用户**可见的本体（四态主体展开：tenant + org(含下级) + role + user）。

        与 chat-api 运行时解析同源，供 §5.8 内部接口（业务系统侧过滤）使用。
        fail-closed：空 ``tenant_id`` / ``user_id`` 返回空集。
        """
        tenant_id = str(tenant_id or "")
        user_id = str(user_id or "")
        if not tenant_id or not user_id:
            return {"tenantId": tenant_id, "userId": user_id, "ontologies": [], "count": 0}
        expander = expander or SubjectExpander()
        subjects = await expander.expand(tenant_id, user_id)
        subject_pairs = subjects.subjects()
        rows = await self.repo.list_grants_for_subjects(tenant_id, subject_pairs)
        visible = resolve_visible_ontologies(subject_pairs, rows)
        return {
            "tenantId": tenant_id,
            "userId": user_id,
            "ontologies": sorted(visible),
            "count": len(visible),
            "orgIds": sorted(subjects.org_ids),
            "roleIds": sorted(subjects.role_ids),
        }

    # ------------------------------------------------------------------ 授权

    async def list_user_grant_summary(self, tenant_id: str) -> list[dict[str, Any]]:
        """按用户汇总本体授权（admin-web「用户本体授权」视图）。

        口径：租户内所有 ``subject_type='user'`` 的授权行，按 ``subject_id`` 分组，
        每组给出「每本体一条」的合并结果（同 ``resolve_visible_ontologies``：
        priority 大者胜、同优先级取更严格模式），另附该用户已停用的授权条数。

        ``tenant`` 兜底行**不计入**任何用户（它是租户级配置，在清单页单独呈现），
        因此某用户此处为空 = 只继承租户兜底，不代表「看不到任何本体」。
        """
        tenant_id = str(tenant_id or "")
        if not tenant_id:
            return []
        rows = await self.repo.list_grants(tenant_id, subject_type="user")
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            subject_id = str(row.get("subject_id") or "")
            if not subject_id:
                continue
            grouped.setdefault(subject_id, []).append(row)

        items: list[dict[str, Any]] = []
        for subject_id in sorted(grouped):
            grants, disabled = self._merge_user_grants(subject_id, grouped[subject_id])
            items.append(
                {
                    "userId": subject_id,
                    "grants": grants,
                    "grantCount": len(grants),
                    "visibleCount": sum(1 for item in grants if item["visible"]),
                    "disabledCount": disabled,
                }
            )
        return items

    @staticmethod
    def _merge_user_grants(
        subject_id: str, rows: Iterable[Mapping[str, Any]]
    ) -> tuple[list[dict[str, Any]], int]:
        """把某用户的授权行合并成「每本体一条」（``enabled`` 为假视为不存在）。"""
        best: dict[str, dict[str, Any]] = {}
        disabled = 0
        for row in rows:
            uri = str(row.get("ontology_uri") or "")
            if not uri:
                continue
            if not enabled_flag(row.get("enabled")):
                disabled += 1
                continue
            mode = str(row.get("access_mode") or "")
            try:
                priority = int(row.get("priority")) if row.get("priority") is not None else 100
            except (TypeError, ValueError):
                priority = 100
            current = best.get(uri)
            if current is None or priority > int(current["priority"]) or (
                priority == int(current["priority"])
                and _MODE_RANK.get(mode, 0) < _MODE_RANK.get(str(current["accessMode"]), 0)
            ):
                best[uri] = {
                    "ontologyId": uri,
                    "subjectId": subject_id,
                    "accessMode": mode,
                    "priority": priority,
                    "visible": mode in VISIBLE_ACCESS_MODES,
                    "remark": str(row.get("remark") or ""),
                    "updatedAt": row.get("updated_at"),
                }
        grants = sorted(best.values(), key=lambda item: str(item["ontologyId"]))
        return grants, disabled

    async def list_subject_grants(
        self, tenant_id: str, subject_type: str, subject_id: str
    ) -> dict[str, Any]:
        grants = await self.repo.list_grants(
            tenant_id, subject_type=subject_type, subject_id=subject_id
        )
        details = await self.repo.list_details(
            tenant_id, subject_type=subject_type, subject_id=subject_id
        )
        return {
            "subjectType": subject_type,
            "subjectId": subject_id,
            "grants": [self._serialize_grant(row) for row in grants],
            "details": [self._serialize_detail(row) for row in details],
        }

    async def batch_grant(
        self,
        *,
        tenant_id: str,
        actor: str,
        subject_type: str,
        subject_id: str,
        ontology_ids: Sequence[str],
        access_mode: str = "read",
        priority: int = 100,
        remark: str = "",
    ) -> dict[str, Any]:
        if access_mode not in ACCESS_MODES:
            raise HTTPException(status_code=422, detail="invalid_access_mode")
        normalized = sorted({str(item).strip() for item in ontology_ids if str(item).strip()})
        if not normalized:
            raise HTTPException(status_code=422, detail="empty_ontology_ids")
        for uri in normalized:
            await self.repo.upsert_grant(
                {
                    "tenant_id": tenant_id,
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "ontology_uri": uri,
                    "access_mode": access_mode,
                    "priority": int(priority),
                    "enabled": True,
                    "remark": remark or None,
                }
            )
        await self._audit(
            tenant_id=tenant_id,
            actor=actor,
            action="grant_save",
            target_kind="grant",
            target_key=f"{subject_type}/{subject_id}",
            detail={
                "ontologyIds": normalized,
                "accessMode": access_mode,
                "priority": int(priority),
            },
        )
        return {"granted": len(normalized), "ontologyIds": normalized}

    async def revoke(
        self, *, tenant_id: str, actor: str, subject_type: str, subject_id: str, ontology_uri: str
    ) -> dict[str, Any]:
        deleted = await self.repo.delete_grant(tenant_id, subject_type, subject_id, ontology_uri)
        # 明细随授权一并撤销，避免留下「孤儿明细」压过已删的授权。
        detail_rows = await self.repo.list_details(
            tenant_id, subject_type=subject_type, subject_id=subject_id, ontology_uri=ontology_uri
        )
        for row in detail_rows:
            await self.repo.delete_detail(
                tenant_id,
                subject_type,
                subject_id,
                ontology_uri,
                str(row.get("class_name") or ""),
            )
        await self._audit(
            tenant_id=tenant_id,
            actor=actor,
            action="grant_delete",
            target_kind="grant",
            target_key=f"{subject_type}/{subject_id}/{ontology_uri}",
            detail={"deleted": deleted, "detailsDeleted": len(detail_rows)},
        )
        return {"deleted": deleted, "detailsDeleted": len(detail_rows)}

    async def list_audit(self, tenant_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self.repo.list_audit(tenant_id, limit=limit)
        return [self._serialize_audit(row) for row in rows]

    # ------------------------------------------------------------------ 序列化

    @staticmethod
    def _serialize_grant(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row.get("_id") or grant_key(
                str(row.get("tenant_id") or ""),
                str(row.get("subject_type") or ""),
                str(row.get("subject_id") or ""),
                str(row.get("ontology_uri") or ""),
            )),
            "subjectType": str(row.get("subject_type") or ""),
            "subjectId": str(row.get("subject_id") or ""),
            "ontologyId": str(row.get("ontology_uri") or ""),
            "accessMode": str(row.get("access_mode") or ""),
            "priority": int(row.get("priority") or 100),
            # 与 repository.upsert_* 同一语义：None 一律按「启用」（DB 值缺失/历史脏数据）。
            "enabled": enabled_flag(row.get("enabled")),
            "remark": str(row.get("remark") or ""),
            "updatedAt": _iso(row.get("updated_at")),
        }

    @staticmethod
    def _serialize_detail(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row.get("_id") or detail_key(
                str(row.get("tenant_id") or ""),
                str(row.get("subject_type") or ""),
                str(row.get("subject_id") or ""),
                str(row.get("ontology_uri") or ""),
                str(row.get("class_name") or ""),
            )),
            "subjectType": str(row.get("subject_type") or ""),
            "subjectId": str(row.get("subject_id") or ""),
            "ontologyId": str(row.get("ontology_uri") or ""),
            "className": str(row.get("class_name") or ""),
            "accessMode": str(row.get("access_mode") or ""),
            "columnMode": str(row.get("column_mode") or ""),
            "columnList": [str(item) for item in (row.get("column_list") or [])],
            "rowCondition": row.get("row_condition"),
            "priority": int(row.get("priority") or 100),
            # 与 repository.upsert_* 同一语义：None 一律按「启用」（DB 值缺失/历史脏数据）。
            "enabled": enabled_flag(row.get("enabled")),
            "remark": str(row.get("remark") or ""),
            "updatedAt": _iso(row.get("updated_at")),
        }

    @staticmethod
    def _serialize_audit(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row.get("id") or row.get("_id") or ""),
            "ts": _iso(row.get("ts")),
            "actor": str(row.get("actor") or ""),
            "action": str(row.get("action") or ""),
            "targetKind": str(row.get("target_kind") or ""),
            "targetKey": str(row.get("target_key") or ""),
            "detail": row.get("detail"),
        }

    # ------------------------------------------------------------------ 内部

    async def _audit(
        self,
        *,
        tenant_id: str,
        actor: str,
        action: str,
        target_kind: str,
        target_key: str,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        try:
            await self.repo.write_audit(
                tenant_id=tenant_id,
                actor=actor,
                action=action,
                target_kind=target_kind,
                target_key=target_key,
                detail=detail,
            )
        except Exception as exc:  # noqa: BLE001 - 审计失败不应回滚配置变更
            logger.warning("本体权限变更审计写入失败：%s", exc)

    async def bump_revision(self, tenant_id: str, actor: str) -> int:
        """递增 ``rev``：供其他进程/组件观察配置是否变化（跨进程缓存的可见信号）。

        注意：chat-api 运行时解析用的是**进程内 60s TTL 缓存**，本方法不直接清它的缓存；
        它保证变更可被审计、并在重启或 TTL 过期后立刻生效。跨进程传播窗口见
        ``docs/ontology-permission-merge-plan.md`` §6「权限缓存一致性」。
        """
        current = await self.repo.get_sys_config(SYS_CONFIG_KEY)
        rev = int(current.get("rev") or 0) + 1
        payload = {
            "enforce": bool(current.get("enforce", False)),
            "defaultMode": str(current.get("defaultMode") or "allow"),
            "rev": rev,
        }
        await self.repo.set_sys_config(payload, SYS_CONFIG_KEY)
        return rev


__all__ = [
    "DETAIL_ACCESS_MODES",
    "OntologyPermissionService",
    "VISIBLE_ACCESS_MODES",
    "resolve_visible_ontologies",
    "utcnow",
]
