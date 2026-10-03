"""Tests for the knowledge graph core (feature 015): schema / store / query."""

from __future__ import annotations

import pytest

from app.knowledge_graph.query import CycleGuard, traverse
from app.knowledge_graph.schema import (
    DEFAULT_MAX_HOPS,
    ENTITY_TYPES,
    RELATION_TYPES,
    KgEdge,
    KgError,
    KgNode,
)
from app.knowledge_graph.store import KgStore, merge_nodes


def _store() -> KgStore:
    store = KgStore()
    for name in ("a", "b", "c", "d"):
        store.add_node(KgNode(node_id=name, entity_type="person", name=name.upper()))
    store.add_edge(KgEdge("a", "b", "membership"))
    store.add_edge(KgEdge("b", "c", "reference"))
    store.add_edge(KgEdge("c", "d", "association"))
    return store


# --- schema ------------------------------------------------------------------

def test_entity_and_relation_types_are_the_generic_set() -> None:
    assert ENTITY_TYPES == ("person", "organization", "product", "event")
    assert RELATION_TYPES == ("membership", "responsible", "reference", "association")


def test_node_requires_id_and_known_type() -> None:
    with pytest.raises(KgError):
        KgNode(node_id="")
    with pytest.raises(KgError):
        KgNode(node_id="n", entity_type="alien")


def test_edge_rejects_self_relation_and_unknown_type() -> None:
    with pytest.raises(KgError):
        KgEdge("a", "a")
    with pytest.raises(KgError):
        KgEdge("a", "b", "soulmate")


def test_default_max_hops_is_three() -> None:
    assert DEFAULT_MAX_HOPS == 3


# --- store / merge -----------------------------------------------------------

def test_low_confidence_node_is_rejected() -> None:
    store = KgStore(confidence_floor=0.5)
    assert store.add_node(KgNode(node_id="x", confidence=0.2)) is False
    assert len(store) == 0


def test_merge_keeps_conflicting_values_and_flags() -> None:
    existing = KgNode(node_id="n", name="N", attributes={"city": "Beijing"})
    incoming = KgNode(node_id="n", name="N", attributes={"city": "Shanghai"})
    merged = merge_nodes(existing, incoming)
    assert merged.attributes["city"] == ["Beijing", "Shanghai"]
    assert merged.conflicted is True


def test_merge_does_not_duplicate_equal_values() -> None:
    existing = KgNode(node_id="n", attributes={"city": "Beijing"})
    incoming = KgNode(node_id="n", attributes={"city": "Beijing"})
    merged = merge_nodes(existing, incoming)
    assert merged.attributes["city"] == "Beijing"
    assert merged.conflicted is False


def test_merge_preserves_source_ref() -> None:
    existing = KgNode(node_id="n")
    incoming = KgNode(node_id="n", source_ref="biz-1")
    assert merge_nodes(existing, incoming).source_ref == "biz-1"


def test_add_edge_requires_known_nodes() -> None:
    store = KgStore()
    store.add_node(KgNode(node_id="a"))
    assert store.add_edge(KgEdge("a", "ghost")) is False


def test_neighbours_filtered_by_relation() -> None:
    store = _store()
    assert store.neighbours("a") == ["b"]
    assert store.neighbours("a", relation="reference") == []


# --- traversal ---------------------------------------------------------------

def test_traverse_returns_paths() -> None:
    store = _store()
    result = traverse(store, "a", max_hops=3)
    assert ["a", "b", "c", "d"] in result.paths
    assert result.hops == 3


def test_traverse_respects_hop_limit() -> None:
    store = _store()
    result = traverse(store, "a", max_hops=1)
    assert ["a", "b"] in result.paths
    assert result.truncated is True


def test_traverse_breaks_at_missing_start() -> None:
    store = _store()
    result = traverse(store, "ghost")
    assert result.broken is True
    assert result.broken_at == 1
    assert "第 1 跳" in result.describe_break()


def test_traverse_dead_end_marks_no_further_paths() -> None:
    store = _store()
    result = traverse(store, "d")  # d has no outgoing edges
    assert result.broken_at == 1


def test_cycle_guard_prevents_revisit() -> None:
    guard = CycleGuard()
    assert guard.visit("a") is True
    assert guard.visit("a") is False


def test_traverse_handles_cycle_without_looping() -> None:
    store = KgStore()
    for name in ("a", "b"):
        store.add_node(KgNode(node_id=name))
    store.add_edge(KgEdge("a", "b"))
    store.add_edge(KgEdge("b", "a"))  # cycle
    result = traverse(store, "a", max_hops=5)
    # terminates; each path is simple except a possible trailing node that marks
    # the detected cycle (e.g. a -> b -> a).
    for path in result.paths:
        interior = path[:-1] if len(path) > 1 else path
        assert len(interior) == len(set(interior))


def test_traverse_relation_filter() -> None:
    store = _store()
    result = traverse(store, "a", relation="reference")
    # a -> b is membership, so filtering by reference yields no extension from a
    assert all(len(path) <= 2 for path in result.paths)


# --- consistency constraints (T008/T009) -------------------------------------

def _conflict_store():
    from app.knowledge_graph.schema import KgEdge, KgNode
    from app.knowledge_graph.store import KgStore

    store = KgStore()
    store.add_node(KgNode(node_id="n1", attributes={"status": ["active", "archived"]}))
    store.add_node(KgNode(node_id="n2", attributes={"status": "active"}))
    store.add_node(KgNode(node_id="a"))
    store.add_node(KgNode(node_id="b"))
    store.add_node(KgNode(node_id="c"))
    store.add_edge(KgEdge("a", "b", "reference"))
    store.add_edge(KgEdge("b", "c", "reference"))
    return store


def test_mutual_exclusion_detects_conflict() -> None:
    from app.knowledge_graph.consistency import MutualExclusion, check_mutual_exclusions
    from app.knowledge_graph.schema import KgError
    import pytest as _pytest

    store = _conflict_store()
    conflicts = check_mutual_exclusions(
        store, [MutualExclusion(attribute="status", conflicting_values=["active", "archived"])]
    )
    assert len(conflicts) == 1
    assert conflicts[0].subject == "n1"
    assert conflicts[0].kind == "mutual_exclusion"


def test_mutual_exclusion_rule_needs_two_values() -> None:
    from app.knowledge_graph.consistency import ConsistencyError, MutualExclusion
    import pytest as _pytest

    with _pytest.raises(ConsistencyError):
        MutualExclusion(attribute="status", conflicting_values=["only"])


def test_transitivity_detects_missing_implied_edge() -> None:
    from app.knowledge_graph.consistency import check_transitivity

    store = _conflict_store()
    gaps = check_transitivity(store, relation="reference")
    assert any(gap.kind == "transitivity" for gap in gaps)
    assert any("a -> c" in gap.detail for gap in gaps)


def test_transitivity_silent_when_edge_present() -> None:
    from app.knowledge_graph.consistency import check_transitivity
    from app.knowledge_graph.schema import KgEdge

    store = _conflict_store()
    store.add_edge(KgEdge("a", "c", "reference"))
    gaps = [gap for gap in check_transitivity(store, relation="reference") if gap.subject == "a"]
    assert gaps == []


def test_cardinality_min_violation() -> None:
    from app.knowledge_graph.consistency import CardinalityRule, check_cardinality

    store = _conflict_store()
    conflicts = check_cardinality(store, [CardinalityRule(relation="reference", min_count=1)])
    # c has no outgoing reference edge
    assert any(conflict.subject == "c" for conflict in conflicts)


def test_cardinality_max_violation() -> None:
    from app.knowledge_graph.consistency import CardinalityRule, check_cardinality
    from app.knowledge_graph.schema import KgEdge, KgNode

    store = _conflict_store()
    store.add_node(KgNode(node_id="d"))
    store.add_node(KgNode(node_id="e"))
    store.add_edge(KgEdge("a", "d", "membership"))
    store.add_edge(KgEdge("a", "e", "membership"))
    conflicts = check_cardinality(store, [CardinalityRule(relation="membership", max_count=1)])
    assert any(conflict.subject == "a" for conflict in conflicts)


def test_cardinality_rule_validates_bounds() -> None:
    from app.knowledge_graph.consistency import CardinalityRule, ConsistencyError
    import pytest as _pytest

    with _pytest.raises(ConsistencyError):
        CardinalityRule(relation="reference", min_count=5, max_count=2)


def test_check_all_and_mark_conflicts_keeps_queryable() -> None:
    from app.knowledge_graph.consistency import (
        ConstraintBundle,
        MutualExclusion,
        check_all,
        mark_conflicts,
    )

    store = _conflict_store()
    bundle = ConstraintBundle(
        mutual_exclusions=[MutualExclusion(attribute="status", conflicting_values=["active", "archived"])],
        transitive_relations=["reference"],
    )
    conflicts = check_all(store, bundle)
    assert conflicts
    mark_conflicts(store, conflicts)
    # the node is flagged but still present/queryable (FR-14)
    assert store.nodes["n1"].conflicted is True
    assert "n1" in store.nodes


def test_persisted_store_supports_constraint_checks(monkeypatch):
    """015 FR-8 residual: TenantKgStore exposes the KgStore interface
    (nodes / edges_of) so consistency.check_all can run against the
    MongoDB-backed store; DB failure degrades to an empty store."""
    import asyncio
    from app.knowledge_graph.persisted_store import TenantKgStore
    from app.knowledge_graph.schema import KgEdge, KgNode

    store = TenantKgStore(tenant_id="t-1")
    # No DB bound: ensure_loaded must not raise (degradation, not fabrication).
    monkeypatch.setattr("app.core.db.get_db", lambda: None)
    asyncio.run(store._ensure_loaded())
    store.add_node(KgNode(node_id="a", name="A", attributes={"status": "active"}))
    store.add_node(KgNode(node_id="b", name="B"))
    store.add_edge(KgEdge(source="a", target="b", relation="reference"))
    assert store.edges_of("a") == [KgEdge(source="a", target="b", relation="reference")]
    assert store.edges_of("a", relation="association") == []

    # The FR-8 checks now run against the persisted store (no-op bundle).
    from app.knowledge_graph.consistency import ConstraintBundle, check_all

    # Silence the 001 audit bridge (no app context in unit tests).
    monkeypatch.setattr("app.knowledge_graph.consistency._audit_kg_audited", lambda conflicts: None)
    assert check_all(store, ConstraintBundle()) == []


# --- 015 FR-1 extraction (续五十七) -----------------------------------------

from app.knowledge_graph.extract import (
    extract,
    extract_from_record,
    extract_from_text,
    apply_to_store,
    ExtractionResult,
)


def test_extract_from_record_structured() -> None:
    """A structured record with owner/department/product/responsible_for
    fields produces the expected typed nodes and edges."""
    result = extract_from_record({
        "owner": "Alice",
        "department": "Engineering",
        "product": "Mogo",
        "responsible_for": ["Mogo", "SlackBot"],
    })
    node_map = {n.node_id: n for n in result.nodes}
    # owner → person
    assert "rec:owner" in node_map and node_map["rec:owner"].entity_type == "person"
    assert node_map["rec:owner"].name == "Alice"
    # department → organization
    assert "rec:department" in node_map and node_map["rec:department"].entity_type == "organization"
    assert node_map["rec:department"].name == "Engineering"
    # product → product
    assert "rec:product" in node_map and node_map["rec:product"].entity_type == "product"
    # responsible_for edges
    edge_pairs = {(e.source, e.target, e.relation) for e in result.edges}
    assert ("rec:owner", "rec:mogo", "responsible") in edge_pairs
    assert ("rec:owner", "rec:slackbot", "responsible") in edge_pairs


def test_extract_from_record_source_ref_pointer() -> None:
    """When owner is a dict with an id, that id is used as source_ref (FR-13)."""
    result = extract_from_record({
        "owner": {"id": "biz-cust-123", "name": "Acme Corp"},
        "product": {"id": "prod-456", "name": "Widget"},
    })
    owner_node = next(n for n in result.nodes if n.node_id == "rec:owner")
    assert owner_node.source_ref == "biz-cust-123"
    assert owner_node.name == "Acme Corp"
    prod_node = next(n for n in result.nodes if n.node_id == "rec:product")
    assert prod_node.source_ref == "prod-456"


def test_extract_from_text_owner_company() -> None:
    """owner: Bob, company: ACME produces a person + organization node."""
    result = extract_from_text("owner: Bob, company: ACME")
    names = {n.name for n in result.nodes}
    types = {n.entity_type for n in result.nodes}
    assert "Bob" in names
    assert "ACME" in names
    assert "person" in types
    assert "organization" in types


def test_extract_from_text_no_match_returns_empty() -> None:
    result = extract_from_text("just some random text with no entity patterns here")
    assert result.nodes == []
    assert result.edges == []


def test_extract_dispatch_dict() -> None:
    result = extract({"owner": "X"})
    assert any(n.name == "X" for n in result.nodes)


def test_extract_dispatch_str() -> None:
    result = extract("owner: Y")
    assert any(n.name == "Y" for n in result.nodes)


def test_extract_unsupported_type_raises() -> None:
    import pytest
    with pytest.raises(TypeError):
        extract(42)


def test_apply_to_store_writes_nodes_and_edges() -> None:
    """apply_to_store writes to a KgStore and reports the counts."""
    from app.knowledge_graph import KgStore
    store = KgStore()
    counts = apply_to_store(store, {
        "owner": "Z",
        "product": "P1",
        "responsible_for": ["P1"],
    })
    assert counts["nodes_added"] >= 3  # owner + product + responsible target
    assert counts["edges_added"] >= 1
    assert "rec:owner" in store.nodes


# --- 015 FR-13 source_ref resolve endpoint ----------------------------------


def test_resolve_source_ref_no_ref(monkeypatch):
    """A node without source_ref returns resolved=False / no_source_ref."""
    import asyncio
    from fastapi import HTTPException

    import app.api.endpoints.knowledge_graph as kg_ep

    async def _fake_resolve(authorization=None):
        return {"main_id": "main-t", "user": {"_id": "u1"}, "user_id": "u1"}

    monkeypatch.setattr("app.services.end_user_session.resolve_session_user", _fake_resolve)

    # Patch TenantKgStore to return a node without source_ref.
    from app.knowledge_graph.persisted_store import TenantKgStore
    from app.knowledge_graph.schema import KgNode

    original_get_node = TenantKgStore.get_node

    def _fake_get_node(self, node_id):
        return KgNode(node_id=node_id, entity_type="person", name="NoRef", source_ref="")

    monkeypatch.setattr(TenantKgStore, "get_node", _fake_get_node)
    monkeypatch.setattr(TenantKgStore, "_ensure_loaded", lambda self: _coro())

    async def _coro(): pass

    result = asyncio.run(kg_ep.resolve_source_ref("node-1", authorization="Bearer x"))
    assert result["data"]["resolved"] is False
    assert result["data"]["reason"] == "no_source_ref"


def test_resolve_source_ref_with_ref_no_target(monkeypatch):
    """A node with source_ref but no matching biz_entities row returns
    resolved=False / pointer_target_missing."""
    import asyncio

    import app.api.endpoints.knowledge_graph as kg_ep
    from app.knowledge_graph.persisted_store import TenantKgStore
    from app.knowledge_graph.schema import KgNode
    from app.core.db import get_db

    async def _fake_resolve(authorization=None):
        return {"main_id": "main-t", "user": {"_id": "u1"}, "user_id": "u1"}

    monkeypatch.setattr("app.services.end_user_session.resolve_session_user", _fake_resolve)

    def _fake_get_node(self, node_id):
        return KgNode(node_id=node_id, entity_type="person", name="HasRef",
                       source_ref="biz-cust-999")

    monkeypatch.setattr(TenantKgStore, "get_node", _fake_get_node)

    async def _fake_load(self): pass
    monkeypatch.setattr(TenantKgStore, "_ensure_loaded", _fake_load)

    # Patch get_db to return a fake DB with no matching row.
    class _FakeColl:
        async def find_one(self, query):
            return None
    class _FakeDB:
        def __getitem__(self, name):
            assert name == "biz_entities"
            return _FakeColl()

    monkeypatch.setattr("app.core.db.get_db", lambda: _FakeDB())

    result = asyncio.run(kg_ep.resolve_source_ref("node-1", authorization="Bearer x"))
    assert result["data"]["resolved"] is False
    assert result["data"]["reason"] == "pointer_target_missing"


# --- 015 RAG candidates ------------------------------------------------------


def test_kg_rag_candidates_returns_entity_context(monkeypatch):
    """kg_rag_candidates finds a node by name and returns its context."""
    import asyncio

    from app.knowledge_graph.rag_candidates import kg_rag_candidates
    from app.knowledge_graph.persisted_store import TenantKgStore
    from app.knowledge_graph.schema import KgNode, KgEdge

    # Build a fake store with a pre-seeded node.
    async def _fake_load(self):
        self._nodes = {
            "n-1": KgNode(node_id="n-1", entity_type="product", name="Mogo", source_ref="biz-prod-1"),
            "n-2": KgNode(node_id="n-2", entity_type="person", name="Alice"),
        }
        self._edges = {"n-2": [KgEdge(source="n-2", target="n-1", relation="responsible")]}
        self._loaded = True

    monkeypatch.setattr(TenantKgStore, "_ensure_loaded", _fake_load)

    candidates = asyncio.run(kg_rag_candidates(
        tenant_id="main-t",
        entity_terms=["Mogo"],
        top_n=3,
    ))
    assert len(candidates) == 1
    assert candidates[0]["entity_type"] == "product"
    assert candidates[0]["source_ref"] == "biz-prod-1"
    assert "n-1" in candidates[0]["neighbours"] or len(candidates[0]["neighbours"]) == 0
    assert "Mogo" in candidates[0]["context_text"]


def test_kg_rag_candidates_unknown_term_returns_empty(monkeypatch):
    import asyncio
    from app.knowledge_graph.rag_candidates import kg_rag_candidates
    from app.knowledge_graph.persisted_store import TenantKgStore

    async def _fake_load(self):
        self._nodes = {}
        self._edges = {}
        self._loaded = True

    monkeypatch.setattr(TenantKgStore, "_ensure_loaded", _fake_load)

    candidates = asyncio.run(kg_rag_candidates(tenant_id="main-t", entity_terms=["unknown"]))
    assert candidates == []
