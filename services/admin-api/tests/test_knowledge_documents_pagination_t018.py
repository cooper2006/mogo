"""025 FR-6 (T018) — knowledge_documents 分页路由整改行为测试。

验证 `app/api/routes/knowledge_documents.py` 两个分页端点已统一到 T017 schema：
- 入参改用 `PageParams`（`page` / `page_size` / `cursor`）
- 出参为 `PageResponse`（`data/total/page/page_size/has_next/next_cursor`，snake_case）

用内存假 Mongo + dependency_overrides 走真实路由，避免依赖真实 DB。
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from fastapi.testclient import TestClient


class _FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs
        self._skip = 0
        self._limit = len(docs)

    def sort(self, *args: Any, **kwargs: Any) -> "_FakeCursor":
        return self

    def skip(self, n: int) -> "_FakeCursor":
        self._skip = n
        return self

    def limit(self, n: int) -> "_FakeCursor":
        self._limit = n
        return self

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        async def _gen() -> AsyncIterator[dict[str, Any]]:
            for doc in self._docs[self._skip : self._skip + self._limit]:
                yield doc

        return _gen()


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    async def count_documents(self, query: dict[str, Any]) -> int:
        return len(self._docs)

    def find(self, query: dict[str, Any]) -> _FakeCursor:
        return _FakeCursor(self._docs)

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        # 仅用于「文档存在性」检查（chunks 端点），返回首条即可
        return self._docs[0] if self._docs else None


class _FakeDB:
    def __init__(self, collection: str, docs: list[dict[str, Any]]) -> None:
        self._collection = collection
        self._docs = docs

    def __getitem__(self, name: str) -> _FakeCollection:
        return _FakeCollection(self._docs)


def _serialize_doc(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc["_id"],
        "name": doc.get("name") or f"doc-{doc['_id']}",
        "updatedAt": doc.get("updated_at") or "2026-01-01T00:00:00Z",
    }


def _serialize_chunk(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc["_id"],
        "ordinal": doc.get("ordinal", 0),
        "text": doc.get("text", ""),
    }


def _make_app(docs: list[dict[str, Any]], monkeypatch: Any) -> Any:
    """构造只挂载 knowledge_documents 路由的最小 app，避免触发 main app 启动。

    注意：路由函数体内是**直接调用** `get_db()`（非 Depends 注入），
    故必须 monkeypatch 路由模块里的 `get_db` 符号，`dependency_overrides` 无效。
    """
    from fastapi import FastAPI

    from app.api.deps import get_current_admin_user
    from app.api.routes import knowledge_documents

    monkeypatch.setattr(knowledge_documents, "get_db", lambda: _FakeDB("ignored", docs))

    app = FastAPI()
    app.dependency_overrides[get_current_admin_user] = lambda: {"tenant_id": "t1", "user_id": "u1"}
    app.include_router(knowledge_documents.router, prefix="/knowledge/documents")
    return app


class TestListDocumentsPagination:
    def test_returns_page_response_shape(self, monkeypatch: Any) -> None:
        docs = [{"_id": f"d{i}", "name": f"n{i}", "updated_at": f"2026-01-0{i+1}T00:00:00Z"} for i in range(1, 6)]
        client = TestClient(_make_app(docs, monkeypatch))
        response = client.get(
            "/knowledge/documents",
            params={"page": 2, "page_size": 2},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # 统一 schema：5 个分页字段 + data，且不含 camelCase
        assert set(body.keys()) == {"data", "total", "page", "page_size", "has_next", "next_cursor"}
        assert body["total"] == 5
        assert body["page"] == 2
        assert body["page_size"] == 2
        assert body["has_next"] is True
        assert body["next_cursor"] is not None

    def test_last_page_has_no_next_cursor(self, monkeypatch: Any) -> None:
        docs = [{"_id": f"d{i}", "name": f"n{i}"} for i in range(1, 5)]
        client = TestClient(_make_app(docs, monkeypatch))
        response = client.get("/knowledge/documents", params={"page": 2, "page_size": 2})
        assert response.status_code == 200
        body = response.json()
        assert body["has_next"] is False
        assert body["next_cursor"] is None

    def test_cursor_preferred_over_page(self, monkeypatch: Any) -> None:
        from app.api.pagination import encode_cursor

        docs = [{"_id": f"d{i}", "name": f"n{i}"} for i in range(1, 10)]
        client = TestClient(_make_app(docs, monkeypatch))
        cursor = encode_cursor(3, 3)
        response = client.get("/knowledge/documents", params={"page": 1, "page_size": 3, "cursor": cursor})
        assert response.status_code == 200
        assert response.json()["page"] == 3

    def test_invalid_cursor_falls_back_to_page(self, monkeypatch: Any) -> None:
        docs = [{"_id": "d1"}]
        client = TestClient(_make_app(docs, monkeypatch))
        response = client.get("/knowledge/documents", params={"page": 1, "cursor": "!!!invalid"})
        assert response.status_code == 200
        assert response.json()["page"] == 1

    def test_page_size_invalid_returns_422(self, monkeypatch: Any) -> None:
        client = TestClient(_make_app([{"_id": "d1"}], monkeypatch))
        response = client.get("/knowledge/documents", params={"page_size": 0})
        assert response.status_code == 422


class TestListDocumentChunksPagination:
    def test_returns_page_response_shape(self, monkeypatch: Any) -> None:
        docs = [{"_id": f"c{i}", "ordinal": i, "text": f"t{i}"} for i in range(1, 6)]
        client = TestClient(_make_app(docs, monkeypatch))
        response = client.get("/knowledge/documents/doc1/chunks", params={"page": 2, "page_size": 2})
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body.keys()) == {"data", "total", "page", "page_size", "has_next", "next_cursor"}
        assert body["total"] == 5
        assert body["page"] == 2
        assert body["has_next"] is True

    def test_last_page_has_no_next_cursor(self, monkeypatch: Any) -> None:
        docs = [{"_id": f"c{i}", "ordinal": i, "text": f"t{i}"} for i in range(1, 5)]
        client = TestClient(_make_app(docs, monkeypatch))
        response = client.get("/knowledge/documents/doc1/chunks", params={"page": 2, "page_size": 2})
        assert response.status_code == 200
        body = response.json()
        assert body["has_next"] is False
        assert body["next_cursor"] is None