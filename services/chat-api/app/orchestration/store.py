"""Persistent store for orchestration definitions (010 FR-8).

The declarative graph for ``competitor_deep_dive`` ships as a YAML file under
``enterprise_capabilities/research/orchestrations/``. FR-8 requires definitions
to be versioned and registered in the ``dag_definitions`` collection so operators
can view / bump versions without editing source files.

This module is the single seam between the on-disk YAML (the repo's source of
truth during development) and the ``dag_definitions`` collection (the runtime
source of truth once registered). On first use it lazily registers the YAML into
the collection; afterwards the collection wins. If the DB is unavailable, the
YAML is used directly and no record is silently fabricated.
"""

from __future__ import annotations
from app.infrastructure.observability.config import log_print

from pathlib import Path
from typing import Any

from .loader import (
    LoadedOrchestration,
    load_orchestration_document,
    load_orchestration_file,
)

DAG_DEFINITIONS_COLLECTION = "dag_definitions"


async def load_orchestration_persisted(
    orchestration_id: str,
    *,
    yaml_path: str | Path,
) -> LoadedOrchestration:
    """Load an orchestration, preferring the ``dag_definitions`` collection.

    Resolution order:
    1. If the DB is bound and a document with ``orchestration_id`` exists, parse
       its ``document`` field (or fall back to the legacy ``definition`` field).
    2. Otherwise load the bundled YAML and, if the DB is bound, register it so
       subsequent reads are collection-backed.

    Either way a valid ``LoadedOrchestration`` is returned; a DB or parse failure
    degrades to the YAML rather than dropping the call.
    """
    doc: dict[str, Any] | None = None
    try:
        from app.core.db import get_db

        db = get_db()
        if db is not None:
            doc = await db[DAG_DEFINITIONS_COLLECTION].find_one(
                {"orchestration_id": orchestration_id}
            )
    except Exception as exc:  # noqa: BLE001 - never block a run on audit/DB noise
        log_print(f"[orchestration.store.load_orchestration_persisted] suppressed {type(exc).__name__}: {exc}", flush=True)
        doc = None

    if doc is not None:
        for key in ("document", "definition"):
            raw = doc.get(key)
            if isinstance(raw, dict):
                return load_orchestration_document(raw)
        # Unknown shape: fall through to YAML (and re-register below).

    loaded = load_orchestration_file(yaml_path)

    # Best-effort registration so the collection becomes the source of truth.
    try:
        from app.core.db import get_db

        db = get_db()
        if db is not None:
            await db[DAG_DEFINITIONS_COLLECTION].update_one(
                {"orchestration_id": orchestration_id},
                {
                    "$set": {
                        "orchestration_id": orchestration_id,
                        "version": str(loaded.definition.version),
                        "document": _document_shape(loaded),
                    },
                    "$setOnInsert": {"created_at": _utcnow()},
                },
                upsert=True,
            )
    except Exception as exc:
        log_print(f"[orchestration/store] save failed: {exc}", flush=True)

    return loaded


def _document_shape(loaded: LoadedOrchestration) -> dict[str, Any]:
    shape: dict[str, Any] = {
        "orchestration": {
            # ``OrchestrationDefinition`` carries ``orchestration_id``; the old
            # ``.id`` raised AttributeError on every registration, so the
            # ``dag_definitions`` upsert silently never happened (R3 audit).
            "id": loaded.definition.orchestration_id,
            "version": str(loaded.definition.version),
            "mode": loaded.definition.mode,
        },
        "nodes": loaded.definition.nodes,
        "edges": loaded.definition.edges,
    }
    # 特性 039：layout 是画布投影元数据（可丢失），但权威 YAML 若带 layout，
    # 经集合往返时应透传，避免手工 YAML 进画布后位置信息被静默丢弃（FR-12）。
    raw_layout = loaded.raw.get("layout") if isinstance(loaded.raw, dict) else None
    if isinstance(raw_layout, dict):
        shape["layout"] = raw_layout
    return shape


def _utcnow() -> Any:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 053-plaza-template-distribution：SOP 模板克隆消费侧（T016）
# ---------------------------------------------------------------------------
#
# SOP 模板经 admin-api 克隆后副本落 ``dag_definitions``（克隆者名下，010 集合）。
# 本模块提供两个消费侧辅助：
#
# * ``register_cloned_definition`` —— 将克隆副本文档写入 dag_definitions（克隆者
#   名下），保持"副本即普通实体"（plan Structure Decision），后续走一切编排既有路径；
# * ``reparse_approver_for_tenant`` —— 050 联动点：含 ``human_approval`` 节点的
#   SOP 克隆后审批人按克隆者租户重新解析（原审批人引用不跨租户携带）。

NODE_TYPE_HUMAN_APPROVAL = "human_approval"


def reparse_approver_for_tenant(node_payload: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
    """050 联动：human_approval 节点审批人按克隆者租户重解析.

    原审批人引用不跨租户携带；克隆侧改挂克隆者租户并打 ``approver_pending``
    标记（副本保存时由克隆者租户显式指定，fail-closed 不静默沿用跨租户审批人）。
    """
    if not isinstance(node_payload, dict):
        return node_payload
    if str(node_payload.get("type") or "") != NODE_TYPE_HUMAN_APPROVAL:
        return node_payload
    result = dict(node_payload)
    result.pop("approver", None)
    result["approver_tenant_id"] = str(tenant_id)
    result["approver_pending"] = True
    return result


async def register_cloned_definition(
    *,
    orchestration_id: str,
    tenant_id: str,
    user_id: str,
    document: dict[str, Any],
    template_ref: dict[str, Any] | None = None,
) -> None:
    """将克隆 SOP 副本写入 dag_definitions（克隆者名下，010 集合）。

    ``document`` 为克隆后的权威定义（引擎可装载）；``template_ref`` 记录模板
    坐标 + 版本（053 已定决策 #2）。
    """
    from app.core.db import get_db

    db = get_db()
    if db is None:
        return
    header = document.get("orchestration") if isinstance(document, dict) else None
    if isinstance(header, dict):
        header = dict(header)
        header["id"] = orchestration_id
        header["version"] = str(header.get("version") or "1")
        if template_ref is not None:
            header["template_ref"] = dict(template_ref)
        document = {**document, "orchestration": header}
    now = _utcnow()
    await db[DAG_DEFINITIONS_COLLECTION].update_one(
        {"tenant_id": tenant_id, "orchestration_id": orchestration_id},
        {
            "$set": {
                "orchestration_id": orchestration_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "version": str(header.get("version") or "1") if isinstance(header, dict) else "1",
                "status": "published",
                "document": document,
                "template_ref": dict(template_ref or {}),
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
