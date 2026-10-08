"""Business semantic index endpoints (014).

Exposes the business-entity index as a real API so the feature is no longer
"implemented but unreachable":
  * ``POST /api/business-index/search`` — semantic search with source/citation
    attribution (reuses the 005 retrieval client; honest empty result when no
    query or client).
  * ``POST /api/business-index/index`` — index one business entity into the
    MongoDB ``business_entity_index`` collection (FR-9 audit wired in the model).
  * ``POST /api/business-index/align`` — cross-system alignment of staged entities
    (FR-5/FR-6; unaligned/missing systems are reported, never refused).

Read-only by design: MOVO never writes back to source business systems.
"""

from __future__ import annotations
from app.infrastructure.observability.config import log_print

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.principal import ApiPrincipal, require_end_user_principal
from app.business_index.alignment import align_entities, join_cross_system
from app.business_index.entities import BizEntity, ENTITY_TYPES
from app.services.business_semantic_index import BusinessSemanticIndex, EntityRecord

router = APIRouter(prefix="/api/business-index", dependencies=[Depends(require_end_user_principal)])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    top_n: int = Field(default=8, ge=1, le=50)


class IndexRequest(BaseModel):
    entity_id: str = Field(min_length=1, max_length=128)
    entity_type: str = Field(min_length=1, max_length=40)
    title: str = Field(default="", max_length=256)
    source_ref: str = Field(default="", max_length=256)
    fields: dict[str, Any] = Field(default_factory=dict)


class AlignRequest(BaseModel):
    entities: list[dict[str, Any]] = Field(min_length=1, max_length=200)
    expected_systems: list[str] = Field(default_factory=list)


@router.post("/search")
async def search(
    payload: SearchRequest,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, Any]:
    from app.core.db import get_db

    index = BusinessSemanticIndex(db=get_db())
    hits = await index.semantic_search(
        payload.query,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        top_n=payload.top_n,
    )
    return {"hits": [hit.with_anchor() for hit in hits]}


@router.post("/index")
async def index_entity(
    payload: IndexRequest,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, Any]:
    if payload.entity_type not in ENTITY_TYPES:
        raise HTTPException(status_code=400, detail=f"unknown entity_type: {payload.entity_type!r}")
    from app.core.db import get_db

    index = BusinessSemanticIndex(db=get_db())
    record = EntityRecord(
        entity_id=payload.entity_id,
        entity_type=payload.entity_type,
        tenant_id=principal.tenant_id,
        title=payload.title,
        source_ref=payload.source_ref,
        fields=payload.fields,
    )
    doc = index.index_entity(record)
    return {"indexed": True, "document": doc}


@router.post("/align")
async def align(
    payload: AlignRequest,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, Any]:
    entities: list[BizEntity] = []
    for raw in payload.entities:
        try:
            entities.append(
                BizEntity(
                    entity_type=str(raw.get("entity_type") or ""),
                    source_system=str(raw.get("source_system") or ""),
                    record_id=str(raw.get("record_id") or ""),
                    fields=dict(raw.get("fields") or {}),
                    tenant_id=principal.tenant_id,
                )
            )
        except Exception as exc:  # noqa: BLE001 - skip malformed, keep the rest
            log_print(f"[api.endpoints.business_index.align] suppressed {type(exc).__name__}: {exc}", flush=True)
            continue
    report = align_entities(entities)
    joined = join_cross_system(report, expected_systems=payload.expected_systems)
    return {
        "groups": joined,
        "unaligned": [
            {"source_system": e.source_system, "entity_type": e.entity_type, "record_id": e.record_id}
            for e in report.unaligned
        ],
    }
