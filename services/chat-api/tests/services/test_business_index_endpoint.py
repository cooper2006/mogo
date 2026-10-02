"""014 business-index endpoint smoke (search/index/align) with in-memory store."""

from __future__ import annotations

import pytest

from app.api.endpoints.business_index import router
from app.business_index.entities import BizEntity
from app.business_index.alignment import align_entities, join_cross_system
from app.services.business_semantic_index import BusinessSemanticIndex, EntityRecord


@pytest.mark.asyncio
async def test_index_and_search_in_memory():
    index = BusinessSemanticIndex(db=None)
    rec = EntityRecord(
        entity_id="c1", entity_type="customer", tenant_id="t1",
        title="Acme", source_ref="crm/1", fields={"code": "A1"},
    )
    doc = index.index_entity(rec)
    assert doc["entity_id"] == "c1"
    assert index.known_entities("t1")[0]["entity_id"] == "c1"


@pytest.mark.asyncio
async def test_align_groups_and_missing_systems():
    entities = [
        BizEntity(entity_type="customer", source_system="crm", record_id="1", fields={"customer_code": "A1"}, tenant_id="t1"),
        BizEntity(entity_type="customer", source_system="finance", record_id="9", fields={"customer_code": "A1"}, tenant_id="t1"),
    ]
    report = align_entities(entities)
    joined = join_cross_system(report, expected_systems=["crm", "finance", "procurement"])
    assert joined[0]["crossSystem"] is True
    assert "procurement" in joined[0]["missingSystems"]


def test_router_registered():
    paths = {r.path for r in router.routes}
    assert "/api/business-index/search" in paths
    assert "/api/business-index/index" in paths
    assert "/api/business-index/align" in paths
