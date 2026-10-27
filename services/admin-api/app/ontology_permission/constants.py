"""本体数据权限 —— 常量（mesc_* 方案）。

配套：
- 建表段 ``deploy/pg/ontology_permission.sql``（PanWeiDB）
- 集合结构 ``deploy/mongo/ontology_permission.js``（MongoDB）
- 合并方案 ``docs/ontology-permission-merge-plan.md``（§3.8 决策 A：原生 repository）
- 接口设计 ``docs/MOGO-Web应用集成方案.md`` §5.7 / §5.8

注意：这些是**结构化表**，**不经** ``app/core/pg_compat.py`` 的通用壳门面，
因此走本模块的原生 repository（mongo motor / PanWeiDB 原生 SQL）。
"""

from __future__ import annotations

from typing import Any

# ── 集合 / 表名 ─────────────────────────────────────────────────────────────
GRANT_TABLE = "mesc_ontology_grant"
DETAIL_TABLE = "mesc_ontology_class_detail"
AUDIT_TABLE = "mesc_ontology_perm_audit"
SYS_CONFIG_TABLE = "sys_config"

#: 只读副本的现有来源：业务实体索引（``business_entity_index``，通用壳表）。
#: 设计 §5.4 建议的独立副本集合 ``ontologies`` 属阶段 4（业务系统对接）范畴，
#: 本阶段「本体清单」直接聚合既有索引里的 ``ontology_id``，不新增表。
ENTITY_INDEX_TABLE = "business_entity_index"

# ── 全局开关 ───────────────────────────────────────────────────────────────
SYS_CONFIG_KEY = "ontology-permission"

# ── 枚举（与 DDL 的 CHECK 约束一一对应）────────────────────────────────────
SUBJECT_TYPES: tuple[str, ...] = ("tenant", "org", "role", "user")
ACCESS_MODES: tuple[str, ...] = ("none", "read", "write")
DETAIL_ACCESS_MODES: tuple[str, ...] = ("inherit", "none", "read", "write")
COLUMN_MODES: tuple[str, ...] = ("all", "selected")

#: 审计动作（与 DDL 注释一致）。
AUDIT_ACTIONS: tuple[str, ...] = (
    "grant_save",
    "grant_delete",
    "detail_save",
    "detail_delete",
    "enforce_toggle",
)
AUDIT_TARGET_KINDS: tuple[str, ...] = ("grant", "detail", "config")

DEFAULT_PRIORITY = 100

#: ``sys_config['ontology-permission']`` 的缺省值（决策③：enforce=true 时实际缺省 deny，
#: ``defaultMode`` 仅用于 enforce=false 的展示/预演口径）。
DEFAULT_SYS_CONFIG: dict[str, object] = {
    "enforce": False,
    "defaultMode": "allow",
    "rev": 0,
}


def enabled_flag(value: Any) -> bool:
    """把 DB 读出的 ``enabled`` 归一化成 ``bool``。

    ``enabled`` 在两种后端上的物理形态不同，但语义一致：

    * mongo    → ``bool``（``$jsonSchema`` 里是 ``bsonType: "bool"``）；
    * PanWeiDB → ``SMALLINT`` 的 ``1`` / ``0``（A / B 两种兼容格式都用 smallint，
      见 ``deploy/pg/ontology_permission.sql`` 与目标库 ``public`` 的对齐）。

    因此判权与展示**不得**再用 ``row.get("enabled") is False`` —— 那只能识别 mongo 的
    ``False``，会把 PanWeiDB 的 ``0`` 当成「启用」而放行。``None``（字段缺失 / 历史脏数据）
    一律按「启用」处理，与 ``repository.upsert_*`` 的写入归一化同一语义。
    """
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    try:
        return int(value) != 0
    except (TypeError, ValueError):
        return bool(value)


def grant_key(tenant_id: str, subject_type: str, subject_id: str, ontology_uri: str) -> str:
    """mongo ``_id``：等价于 PG 的复合主键（确定性拼接，支持 upsert）。"""
    return "|".join([str(tenant_id), str(subject_type), str(subject_id), str(ontology_uri)])


def detail_key(
    tenant_id: str, subject_type: str, subject_id: str, ontology_uri: str, class_name: str
) -> str:
    return "|".join(
        [str(tenant_id), str(subject_type), str(subject_id), str(ontology_uri), str(class_name)]
    )


__all__ = [
    "ACCESS_MODES",
    "AUDIT_ACTIONS",
    "AUDIT_TABLE",
    "AUDIT_TARGET_KINDS",
    "COLUMN_MODES",
    "DEFAULT_PRIORITY",
    "DEFAULT_SYS_CONFIG",
    "DETAIL_ACCESS_MODES",
    "DETAIL_TABLE",
    "ENTITY_INDEX_TABLE",
    "GRANT_TABLE",
    "SYS_CONFIG_KEY",
    "SYS_CONFIG_TABLE",
    "SUBJECT_TYPES",
    "detail_key",
    "enabled_flag",
    "grant_key",
]
