# 015 Knowledge Graph Layer — Quickstart

## Modules (chat-api `app/knowledge_graph/`)

| Module | Concern |
| --- | --- |
| `schema.py` | `KgNode` / `KgEdge` dataclasses |
| `store.py` | `KgStore` — add/merge nodes+edges, neighbours, confidence floor |
| `query.py` | `traverse` multi-hop + `CycleGuard` + `MultiHopResult` |
| `consistency.py` | T999 冲突检测 + 一致性修复 |

## 1. Build the graph

```python
from app.knowledge_graph.store import KgStore
from app.knowledge_graph.schema import KgNode, KgEdge

store = KgStore(confidence_floor=0.6)
store.add_node(KgNode(node_id="n1", label="Customer", confidence=0.9))
store.add_edge(KgEdge(source="n1", target="n2", relation="ordered", confidence=0.8))
```

## 2. Multi-hop traversal

```python
from app.knowledge_graph.query import traverse

result = traverse(store, start="n1", relations=["ordered", "paid"], max_hops=3)
if result.broken:
    print(result.describe_break())
```

## T999 审计接入

`kg.mutated` / `kg.conflict.resolved` / `kg.audited` 事件经
`app/services/feature_audit.py::record_feature_event("015", ...)` 进 001
审计落点。
