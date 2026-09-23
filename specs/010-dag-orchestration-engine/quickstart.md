# 010 DAG Orchestration Engine — Quickstart

## Modules (chat-api)

| Module | Concern |
| --- | --- |
| `app/orchestration/graph.py` | DAG node/edge model + topo order |
| `app/orchestration/conditions.py` | Restricted JSON condition evaluation (fail-closed) |
| `app/orchestration/engine.py` | DAG/sequential execution + skip + transition events |
| `app/services/dag/skip.py` | Conditional skip primitive + skip traceability (T013-T015) |
| `app/services/dag/retry.py` | Node-level exponential-backoff retry (T016-T017) |
| `app/services/dag/builder_migrate.py` | Content-builder dual-track migration + equivalence guard (T018-T019) |

## 1. Build a DAG

```python
from app.orchestration.graph import Graph, Node, Edge

graph = Graph(
    nodes=[
        Node("fetch", condition={"op": "==", "left": {"var": "total"}, "right": 0}),
        Node("plan"),
        Node("merge"),
    ],
    edges=[Edge("fetch", "plan"), Edge("plan", "merge")],
)
```

## 2. Conditional skip (US3 — T013-T015)

```python
from app.services.dag.skip import evaluate_skip, DownstreamPolicy, skip_trace_document

decision = evaluate_skip(graph, "fetch", context={"total": 0},
                         downstream_policy=DownstreamPolicy.PROPAGATE)
# condition true -> skipped, downstream marked
trace = skip_trace_document(decision)
# {node_id, skipped, reason, result, error, affected_downstream}
```

Three outcomes: condition true → skip (+ optional downstream handling),
false → run, syntax error → fail-closed skip (error recorded, US3 acceptance 3).

## 3. Node retry with backoff (US4 — T016-T017)

```python
from app.services.dag.retry import RetryPolicy, run_node_with_retry, policy_from_node

policy = RetryPolicy(max_attempts=3, base_seconds=2.0, factor=2.0, cap_seconds=60.0)
result = run_node_with_retry("plan", my_node_coro, policy=policy, sleep=sleep_fn)
# Layering: delegate_model_backoff=True -> model-level backoff owned by 007
```

## 4. Dual-track content-builder migration (T018-T019)

```python
from app.services.dag.builder_migrate import (
    BuilderPath, content_plan_dag, run_content_plan_dag, builder_equivalent,
)

dag = content_plan_dag({...})
result = await run_content_plan_dag(dag, semantic=..., structured=..., fallback=..., merge=..., context={})
# Regression guard: legacy and DAG paths must be equivalent
assert builder_equivalent(legacy_plan, result) is True
```

## 5. Four modes + versioning (T021)

Modes: `sequential` / `supervisor` / `hybrid` / `graph` (VALID_MODES).
Orchestration definitions are versioned; the latest is active, older
versions remain browsable (T021: 契约版本递增，旧版可回看).

## 6. Concurrency budget (T020 / FR-12)

Parallel DAGs respect the 007 LLM-gateway concurrency budget; over-limit
requests queue with backoff rather than exceeding the gateway.
