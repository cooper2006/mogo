from __future__ import annotations

from app.services import retrieval_service


class _Store:
    def __init__(self):
        self.pages = []

    def search(self, **kwargs):
        limit = kwargs["limit"]
        offset = kwargs["offset"]
        self.pages.append((offset, limit))
        return [{"documentId": f"doc-{index}"} for index in range(offset, offset + limit)]


class _Policy:
    def filter_candidates(self, items, *, main_id, user_id):
        assert main_id == "tenant"
        assert user_id == "user"
        return [item for item in items if int(item["documentId"].split("-")[1]) >= 70]


def test_expands_tenant_recall_when_authorized_results_are_too_sparse(monkeypatch):
    store = _Store()
    monkeypatch.setattr(retrieval_service, "knowledge_retrieval_access_policy", _Policy())

    results = retrieval_service._search_authorized_candidates(
        store=store,
        query_vector=[0.1],
        query="query",
        main_id="tenant",
        user_id="user",
        knowledge_base_id="",
        mode="vector",
        top_n=5,
        candidate_top_k=50,
        max_candidate_scan=10_000,
        score_threshold=0,
    )

    assert store.pages == [(0, 50), (50, 50), (100, 50)]
    assert [item["documentId"] for item in results[:2]] == ["doc-70", "doc-71"]
