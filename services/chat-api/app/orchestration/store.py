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

from pathlib import Path
from typing import Any

from .loader import LoadedOrchestration, load_orchestration_file

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
    except Exception:  # noqa: BLE001 - never block a run on audit/DB noise
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
    return {
        "orchestration": {
            "id": loaded.definition.id,
            "version": str(loaded.definition.version),
            "mode": loaded.definition.mode,
        },
        "nodes": loaded.definition.nodes,
        "edges": loaded.definition.edges,
    }


def _utcnow() -> Any:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
