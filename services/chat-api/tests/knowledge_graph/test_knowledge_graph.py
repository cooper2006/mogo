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
