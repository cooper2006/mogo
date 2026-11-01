# 014 Business Semantic Index — Quickstart

## Module (chat-api `app/services/business_semantic_index.py`)

索引**仅指针**（从不写业务库 — 014 Non-Goal），语义检索**复用 005 检索
客户端**，命中带来源/引用锚点（US1 验收 2）。

## 1. 实体入索引

```python
from app.services.business_semantic_index import BusinessSemanticIndex, EntityRecord

index = BusinessSemanticIndex(db=None)
index.index_entities([
    EntityRecord(entity_id="c1", entity_type="customer", tenant_id="t1", title="Acme"),
    EntityRecord(entity_id="o1", entity_type="order", tenant_id="t1", title="Order-1"),
])
```

## 2. 语义检索（复用 005 + 引用锚点）

```python
hits = await index.semantic_search(
    "acme policy",
    tenant_id="t1",
    client=my_005_retrieval_client,
    top_n=8,
)
hit = hits[0].with_anchor()
# {entity_id, entity_type, title, score, source_ref, chunk,
#  citation: "document:doc-1#chunk-9"}
```

## T999 审计接入

`entity.indexed` / `entity.searched` 事件经
`app/services/feature_audit.py::record_feature_event("014", ...)` 进 001
审计落点。
