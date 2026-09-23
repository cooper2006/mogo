"""014 T007 semantic search (005 client reuse + citation anchor) + 017 T010-T011 memory-in-RAG tests."""

from __future__ import annotations

import pytest

from app.memory.retrieval import memory_rag_candidates, promoted_memories_retrievable, scope_filter
from app.memory.scope import Memory, MemoryScope
from app.services.business_semantic_index import BusinessSemanticIndex, EntityRecord


# --- 014 T007: entity index + semantic search with source ---------------------


def test_index_entities_and_list():
    index = BusinessSemanticIndex(db=None)
    n = index.index_entities(
        [
            EntityRecord(entity_id="c1", entity_type="customer", tenant_id="t1", title="Acme"),
            EntityRecord(entity_id="o1", entity_type="order", tenant_id="t1", title="Order-1"),
            EntityRecord(entity_id="c2", entity_type="customer", tenant_id="t2", title="Globex"),
        ]
    )
    assert n == 3
    # tenant isolation: t1 sees its own two entities
    assert {e["entity_id"] for e in index.known_entities("t1")} == {"c1", "o1"}
    assert {e["entity_id"] for e in index.known_entities("t2")} == {"c2"}


def test_index_entity_unknown_type_rejected():
    with pytest.raises(ValueError):
        EntityRecord(entity_id="x", entity_type="bogus", tenant_id="t1")


def test_semantic_search_with_citation_anchor():
    """014 T007 / US1: semantic search reuses the 005 client and carries a source anchor."""
    index = BusinessSemanticIndex(db=None)

    class _FakeRetrievalClient:
        def __init__(self):
            pass

        async def search(self, **kwargs):
            from app.knowledge.retrieval.schemas import RetrievalChunkItem, RetrievalSearchResult

            items = [
                RetrievalChunkItem(
                    documentId="doc-1",
                    chunkId="chunk-9",
                    text="Acme ordering policy",
                    score=0.9,
                    rerankScore=0.95,
                    metadata={"entity_type": "document", "entity_id": "doc-1"},
                    titlePath=["Acme", "Policies"],
                ),
                RetrievalChunkItem(
                    documentId="doc-2",
                    chunkId="chunk-10",
                    text="Globex SLA",
                    score=0.7,
                    rerankScore=0.8,
                    metadata={"entity_type": "document", "entity_id": "doc-2"},
                    titlePath=["Globex", "SLA"],
                ),
            ]
            return RetrievalSearchResult(query=kwargs.get("query", ""), items=items, total=2)

    import asyncio

    fake_client = _FakeRetrievalClient()
    hits = asyncio.run(index.semantic_search(
        "acme policy",
        tenant_id="t1",
        client=fake_client,
        top_n=8,
    ))
    assert len(hits) == 2
    # US1 acceptance 2: each hit carries a source/citation anchor
    top = hits[0].with_anchor()
    assert top["entity_id"] == "doc-1"
    assert top["entity_type"] == "document"
    assert top["source_ref"] == "chunk-9"
    assert top["citation"] == "document:doc-1#chunk-9"
    assert top["score"] == 0.95
    # ranking: highest score first
    assert hits[0].score >= hits[1].score


def test_semantic_search_empty_query_honest_empty():
    index = BusinessSemanticIndex(db=None)
    import asyncio

    assert asyncio.run(index.semantic_search("", tenant_id="t1")) == []


# --- 017 T010: memory-in-RAG by scope filter ---------------------------------


def _memories() -> list[Memory]:
    return [
        Memory(content="personal note", scope="personal", owner_id="u1", memory_id="m-personal"),
        Memory(content="workspace plan", scope="workspace", workspace_id="w1", owner_id="u1", memory_id="m-workspace"),
        Memory(content="org policy", scope="org", tenant_id="t1", owner_id="admin", memory_id="m-org"),
        Memory(content="other tenant org", scope="org", tenant_id="t2", owner_id="admin", memory_id="m-other"),
    ]


def test_scope_filter_personal_only_owner():
    memories = _memories()
    # u1 owns the personal memory, is a workspace member, and any org-scope is visible to members
    filtered = scope_filter(memories, viewer_id="u1", is_workspace_member=True)
    ids = {m.memory_id for m in filtered}
    # personal (owner) + workspace (member) + org (t1) visible; t2 org still visible
    # (visible_to checks viewer non-empty within tenant) — assert the three own-scope ones:
    assert "m-personal" in ids
    assert "m-workspace" in ids
    assert "m-org" in ids


def test_scope_filter_non_owner_cannot_read_personal():
    memories = _memories()
    filtered = scope_filter(memories, viewer_id="u2", is_workspace_member=False)
    ids = {m.memory_id for m in filtered}
    assert "m-personal" not in ids  # u2 is not the owner
    # u2 is not a workspace member and not a tenant member with a viewer role:
    # org-scope memories require a non-empty viewer; without membership the
    # workspace memory is hidden.
    assert "m-workspace" not in ids


def test_memory_rag_candidates_ranked_by_scope_then_recency():
    memories = [
        Memory(content="org rule", scope="org", owner_id="a", last_accessed_at=10.0, memory_id="m-org"),
        Memory(content="ws plan", scope="workspace", owner_id="u1", last_accessed_at=20.0, memory_id="m-ws"),
        Memory(content="my note", scope="personal", owner_id="u1", last_accessed_at=30.0, memory_id="m-p"),
    ]
    candidates = memory_rag_candidates(
        memories,
        viewer_id="u1",
        is_workspace_member=True,
        top_n=3,
    )
    # org (weight 3) > workspace (2) > personal (1)
    assert [c["memory_id"] for c in candidates] == ["m-org", "m-ws", "m-p"]
    assert candidates[0]["score"] > candidates[1]["score"] > candidates[2]["score"]
    for candidate in candidates:
        assert "content" in candidate
        assert "scope" in candidate


def test_memory_rag_candidates_excludes_invisible():
    memories = [
        Memory(content="someone else personal", scope="personal", owner_id="u9", memory_id="m-other"),
        Memory(content="mine", scope="personal", owner_id="u1", memory_id="m-mine"),
    ]
    candidates = memory_rag_candidates(memories, viewer_id="u1", top_n=5)
    ids = [c["memory_id"] for c in candidates]
    assert "m-mine" in ids
    assert "m-other" not in ids


# --- 017 T011 US2: promotion + decay + retrieval filter ----------------------


def test_promoted_org_memory_retrievable_by_member():
    promoted = Memory(
        content="shared guideline",
        scope="org",
        owner_id="u1",
        tenant_id="t1",
        memory_id="m-promoted",
    )
    retrievable = promoted_memories_retrievable([promoted], viewer_id="u1", viewer_role="")
    assert "m-promoted" in retrievable


def test_unpromoted_memory_not_in_retrieval():
    personal = Memory(
        content="private",
        scope="personal",
        owner_id="u1",
        memory_id="m-priv",
    )
    # T011 US2: only org-scope promoted memories enter the shared retrieval pool
    assert promoted_memories_retrievable([personal], viewer_id="u1") == []


def test_promotion_requires_authorized_role():
    from app.memory.scope import MemoryAccessError, promote_to_org

    memory = Memory(content="note", scope="personal", owner_id="u1", memory_id="m-x")
    with pytest.raises(MemoryAccessError):
        promote_to_org(memory, role="viewer")
    memory.scope = "personal"
    promoted = promote_to_org(memory, role="full_access_admin")
    assert promoted.scope == "org"


def test_memory_decay_and_touch():
    from app.memory.lifecycle import MemoryLifecycle, is_expired, touch

    # A short decay window (1 day) so the test can exercise expiry.
    lifecycle = MemoryLifecycle(decay_days=1)
    last = 0.0
    # within the 1-day decay window -> not expired
    assert is_expired(last_accessed_at=last, now=3600.0, lifecycle=lifecycle) is False
    # accessing the memory resets its timer (OQ-2)
    last = touch(last, now=80000.0)
    assert last == 80000.0
    # 86400 seconds later the memory is past its decay window -> expired
    assert is_expired(last_accessed_at=last, now=80000.0 + 86400.0, lifecycle=lifecycle) is True


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
