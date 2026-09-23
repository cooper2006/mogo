"""Tests for the DAG orchestration core (feature 010): graph / topo / conditions."""

from __future__ import annotations

import pytest

from app.orchestration.conditions import ConditionError, evaluate_condition
from app.orchestration.graph import Edge, Graph, GraphError, Node
from app.orchestration.topo import CycleError, topological_order


def _graph(edges: list[tuple[str, str]], nodes: list[str] | None = None) -> Graph:
    ids = nodes or sorted({item for edge in edges for item in edge})
    g = Graph(nodes=[Node(id=name) for name in ids])
    for source, target in edges:
        g.add_edge(Edge(source, target))
    return g


# --- graph model -------------------------------------------------------------

def test_node_requires_id() -> None:
    with pytest.raises(GraphError):
        Node(id="")


def test_duplicate_node_rejected() -> None:
    g = Graph(nodes=[Node(id="a")])
    with pytest.raises(GraphError):
        g.add_node(Node(id="a"))


def test_edge_requires_existing_nodes() -> None:
    g = Graph(nodes=[Node(id="a")])
    with pytest.raises(GraphError):
        g.add_edge(Edge("a", "ghost"))


def test_self_loop_rejected() -> None:
    g = Graph(nodes=[Node(id="a")])
    with pytest.raises(GraphError):
        g.add_edge(Edge("a", "a"))


def test_downstream_closure_is_transitive() -> None:
    g = _graph([("a", "b"), ("b", "c"), ("c", "d")])
    assert g.downstream_closure("a") == {"b", "c", "d"}


def test_roots_are_nodes_without_dependencies() -> None:
    g = _graph([("a", "b"), ("c", "b")])
    assert set(g.roots()) == {"a", "c"}


# --- topological order -------------------------------------------------------

def test_topological_order_respects_dependencies() -> None:
    g = _graph([("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])
    order = topological_order(g)
    assert order.index("a") < order.index("b") < order.index("d")
    assert order.index("a") < order.index("c") < order.index("d")


def test_topological_order_is_deterministic() -> None:
    g = _graph([("a", "c"), ("b", "c")])
    assert topological_order(g) == topological_order(g)


def test_cycle_detection_reports_node_sequence() -> None:
    g = _graph([("a", "b"), ("b", "c"), ("c", "a")])
    with pytest.raises(CycleError) as excinfo:
        topological_order(g)
    cycle = excinfo.value.cycle
    assert cycle[0] == cycle[-1]              # closed path A -> ... -> A
    assert set(cycle) == {"a", "b", "c"}


def test_two_node_cycle_detected() -> None:
    g = _graph([("x", "y"), ("y", "x")])
    with pytest.raises(CycleError):
        topological_order(g)


def test_acyclic_graph_does_not_raise() -> None:
    g = _graph([("a", "b"), ("b", "c")])
    assert topological_order(g) == ["a", "b", "c"]


# --- conditions --------------------------------------------------------------

def test_no_condition_is_true() -> None:
    assert evaluate_condition(None) is True


def test_equality_condition() -> None:
    assert evaluate_condition({"op": "==", "left": 1, "right": 1}) is True
    assert evaluate_condition({"op": "==", "left": 1, "right": 2}) is False


def test_ordering_conditions() -> None:
    assert evaluate_condition({"op": ">", "left": 5, "right": 3}) is True
    assert evaluate_condition({"op": "<=", "left": 5, "right": 3}) is False


def test_in_and_has_conditions() -> None:
    assert evaluate_condition({"op": "in", "left": "b", "right": ["a", "b"]}) is True
    assert evaluate_condition({"op": "has", "left": {"k": 1}, "right": "k"}) is True


def test_var_reference_resolves_from_context() -> None:
    condition = {"op": "==", "left": {"var": "status"}, "right": "ok"}
    assert evaluate_condition(condition, {"status": "ok"}) is True


def test_nested_var_reference() -> None:
    condition = {"op": ">", "left": {"var": "metrics.calls"}, "right": 10}
    assert evaluate_condition(condition, {"metrics": {"calls": 20}}) is True


def test_unresolved_variable_raises() -> None:
    with pytest.raises(ConditionError):
        evaluate_condition({"op": "==", "left": {"var": "missing"}, "right": 1}, {})


def test_logical_and_or_not() -> None:
    ctx = {"n": 5}
    cond_and = {"op": "and", "operands": [{"op": ">", "left": {"var": "n"}, "right": 1}, {"op": "<", "left": {"var": "n"}, "right": 10}]}
    assert evaluate_condition(cond_and, ctx) is True
    cond_or = {"op": "or", "operands": [{"op": ">", "left": {"var": "n"}, "right": 99}, {"op": "==", "left": {"var": "n"}, "right": 5}]}
    assert evaluate_condition(cond_or, ctx) is True
    cond_not = {"op": "not", "operand": {"op": "==", "left": {"var": "n"}, "right": 5}}
    assert evaluate_condition(cond_not, ctx) is False


def test_unknown_operator_raises() -> None:
    with pytest.raises(ConditionError):
        evaluate_condition({"op": "eval", "left": 1, "right": 2})


def test_missing_comparison_operands_raises() -> None:
    with pytest.raises(ConditionError):
        evaluate_condition({"op": "==", "left": 1})


def test_malformed_logical_operands_raise() -> None:
    with pytest.raises(ConditionError):
        evaluate_condition({"op": "and", "operands": "not-a-list"})


def test_no_arbitrary_code_execution() -> None:
    # An operator that would run code is simply unknown -> fail closed.
    with pytest.raises(ConditionError):
        evaluate_condition({"op": "__import__", "left": "os", "right": "system"})
