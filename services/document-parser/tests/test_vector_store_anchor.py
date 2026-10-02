"""003 anchor channel regression (audit 2026-10-03).

The document-ingestion producer (``document_parsing_service``) writes
``metadata.sourceAnchor`` (page bbox / table context) onto Mongo chunks,
but the Weaviate vector store had no schema field, upsert channel, or
GraphQL read-back for it — so the consumer ``citation_resolver``
(``_source_anchor`` reading ``chunk.metadata.sourceAnchor``) always got
an empty anchor. This test pins the fixed channel: the anchor is
serialized into the ``anchorJson`` property on upsert and parsed back
into ``metadata.sourceAnchor`` on search.
"""

from app.services import vector_store


def test_anchor_json_roundtrip_from_chunk_metadata():
    chunk = {
        "main_id": "m-1",
        "document_id": "d-1",
        "chunk_id": "chunk_000001",
        "text": "hello",
        "metadata": {
            "sourceAnchor": {
                "page": 3,
                "bbox": [0.1, 0.2, 0.5, 0.6],
                "tableContext": "row 2",
            },
        },
    }
    serialized = vector_store._anchor_json(chunk)
    assert serialized, "the producer's sourceAnchor must serialize into the store"
    restored = vector_store._parse_anchor_json(serialized)
    assert restored == chunk["metadata"]["sourceAnchor"]


def test_anchor_json_is_empty_when_no_anchor():
    chunk = {"main_id": "m-1", "document_id": "d-1", "chunk_id": "c", "text": "x"}
    assert vector_store._anchor_json(chunk) == ""
    # A chunk with an explicitly empty metadata block also has no anchor.
    assert vector_store._anchor_json({**chunk, "metadata": {}}) == ""


def test_parse_anchor_json_never_fabricates():
    assert vector_store._parse_anchor_json("") == {}
    assert vector_store._parse_anchor_json(None) == {}
    assert vector_store._parse_anchor_json("not-json") == {}
    assert vector_store._parse_anchor_json('"a-string"') == {}  # non-dict -> {}
    assert vector_store._parse_anchor_json('{"page": 1}') == {"page": 1}


def test_schema_includes_anchor_json_property():
    """The schema creation must include the anchorJson property so the
    channel exists end-to-end (003 audit: schema/upsert/GraphQL all had
    zero anchor fields before the fix)."""
    import json
    from unittest.mock import patch

    created_body = {}

    def fake_request(method, path, body=None, *, allow_404=False):
        if method == "POST" and path == "/v1/schema":
            created_body.update(body)
            return {}
        return None  # GET /v1/schema/{class} -> falsy means "create it"

    store = vector_store.WeaviateVectorStore({})
    with patch.object(store, "_request_json", side_effect=fake_request):
        store.ensure_schema()

    property_names = [p["name"] for p in created_body.get("properties", [])]
    assert "anchorJson" in property_names, "anchor channel must be in the Weaviate schema"
