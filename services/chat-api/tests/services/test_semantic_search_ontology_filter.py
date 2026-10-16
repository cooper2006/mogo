"""``semantic_search`` 的可见本体过滤（设计四 §5.6.2 生效点）。

权限键 = ``ontology_id``；``entity_type`` 只是类型标签，不参与判定。
用假 retrieval client，不依赖真实检索后端。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.business_semantic_index import BusinessSemanticIndex


def _item(*, ontology_id: str, entity_type: str, entity_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        titlePath=["t"],
        metadata={"ontology_id": ontology_id, "entity_type": entity_type, "entity_id": entity_id},
        documentId=entity_id,
        rerankScore=1.0,
        score=1.0,
        chunkId=f"{entity_id}#0",
        text="x",
    )


class _FakeRetrievalClient:
    def __init__(self, items: list[SimpleNamespace]) -> None:
        self._items = items

    async def search(self, **_kwargs) -> SimpleNamespace:
        return SimpleNamespace(items=self._items)


async def test_no_filter_returns_all_hits():
    index = BusinessSemanticIndex()
    client = _FakeRetrievalClient([
        _item(ontology_id="material", entity_type="product", entity_id="p1"),
        _item(ontology_id="order", entity_type="order", entity_id="o1"),
    ])
    hits = await index.semantic_search("q", tenant_id="t1", user_id="u1", client=client)
    assert {h.ontology_id for h in hits} == {"material", "order"}


async def test_filter_keeps_only_visible_ontology():
    index = BusinessSemanticIndex()
    client = _FakeRetrievalClient([
        _item(ontology_id="material", entity_type="product", entity_id="p1"),
        _item(ontology_id="order", entity_type="order", entity_id="o1"),
    ])
    hits = await index.semantic_search(
        "q", tenant_id="t1", user_id="u1", client=client, visible_ontology_ids=frozenset({"material"})
    )
    assert [h.ontology_id for h in hits] == ["material"]


async def test_entity_type_alone_does_not_grant_visibility():
    # entity_type == 可见集里的字符串，但 ontology_id 不在其中 → 仍不可见。
    index = BusinessSemanticIndex()
    client = _FakeRetrievalClient([_item(ontology_id="other", entity_type="material", entity_id="x1")])
    hits = await index.semantic_search(
        "q", tenant_id="t1", user_id="u1", client=client, visible_ontology_ids=frozenset({"material"})
    )
    assert hits == []


async def test_hit_without_ontology_id_is_hidden_when_filtering():
    index = BusinessSemanticIndex()
    client = _FakeRetrievalClient([
        SimpleNamespace(
            titlePath=["t"], metadata={"entity_type": "customer", "entity_id": "c1"},
            documentId="c1", rerankScore=1.0, score=1.0, chunkId="c1#0", text="x",
        )
    ])
    hits = await index.semantic_search(
        "q", tenant_id="t1", user_id="u1", client=client, visible_ontology_ids=frozenset({"customer"})
    )
    assert hits == []


async def test_empty_visible_set_is_fail_closed():
    index = BusinessSemanticIndex()
    client = _FakeRetrievalClient([_item(ontology_id="material", entity_type="product", entity_id="p1")])
    hits = await index.semantic_search(
        "q", tenant_id="t1", user_id="u1", client=client, visible_ontology_ids=frozenset()
    )
    assert hits == []


def test_entity_record_carries_ontology_id_into_document():
    from app.services.business_semantic_index import EntityRecord

    index = BusinessSemanticIndex()
    rec = EntityRecord(
        entity_id="c1", entity_type="customer", tenant_id="t1", ontology_id="material"
    )
    doc = index.index_entity(rec)
    assert doc["ontology_id"] == "material"
    assert index.known_entities("t1")[0]["ontology_id"] == "material"
