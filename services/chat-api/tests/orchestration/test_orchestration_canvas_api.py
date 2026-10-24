"""Tests for the visual-orchestration canvas API (feature 039).

Covers the two seams introduced by 039:
* ``store._document_shape`` now passes ``layout`` through (投影元数据不静默丢失)；
* the canvas endpoints ``/api/orchestrations`` — draft save / publish gate / validation /
  tenant isolation — all validated against the SAME loader the 010 engine uses.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api.endpoints import orchestrations
from app.api.principal import ApiPrincipal
from app.orchestration import store


# --- store: layout passthrough -----------------------------------------------

def test_document_shape_passes_layout_through() -> None:
    """权威 YAML 带 layout 时，集合往返不应静默丢弃位置信息（FR-12）。"""

    class _Def:
        orchestration_id = "demo"
        version = 3
        mode = "graph"
        nodes = [{"id": "a"}]
        edges = []

    class _Loaded:
        definition = _Def()
        raw = {"layout": {"a": {"x": 10, "y": 20}}, "audit": {"x": 1}}

    shape = store._document_shape(_Loaded())  # type: ignore[arg-type]
    assert shape["layout"] == {"a": {"x": 10, "y": 20}}
    assert shape["orchestration"]["id"] == "demo"


def test_document_shape_ignores_non_dict_layout() -> None:
    class _Def:
        orchestration_id = "demo"
        version = 1
        mode = "graph"
        nodes = []
        edges = []

    class _Loaded:
        definition = _Def()
        raw = {"layout": "broken"}

    shape = store._document_shape(_Loaded())  # type: ignore[arg-type]
    assert "layout" not in shape


# --- endpoint fixtures -------------------------------------------------------

class _Cursor:
    def __init__(self, documents: list[dict]) -> None:
        self._documents = documents

    def sort(self, _field: str, _direction: int):
        return self

    def __aiter__(self):
        self._iterator = iter(self._documents)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _Collection:
    def __init__(self) -> None:
        self.documents: list[dict] = []

    async def find_one(self, scope: dict):
        return next(
            (item for item in self.documents if all(item.get(k) == v for k, v in scope.items())),
            None,
        )

    def find(self, scope: dict) -> _Cursor:
        return _Cursor(
            [item for item in self.documents if all(item.get(k) == v for k, v in scope.items())]
        )

    async def update_one(self, scope: dict, update: dict, upsert: bool = False) -> None:
        document = next(
            (
                item
                for item in self.documents
                if all(item.get(k) == v for k, v in scope.items())
            ),
            None,
        )
        if document is None:
            assert upsert
            document = dict(scope)
            document.update(update.get("$setOnInsert", {}))
            self.documents.append(document)
        document.update(update.get("$set", {}))


class _Database:
    def __init__(self) -> None:
        self.dag_definitions = _Collection()
        self.end_users = _Collection()

    def __getitem__(self, name: str) -> _Collection:
        return getattr(self, name)

    def __getitem__(self, name: str) -> _Collection:
        return getattr(self, name)


PRINCIPAL = ApiPrincipal(kind="end_user", tenant_id="t1", user_id="u1")


def _valid_document(orchestration_id: str = "demo") -> dict:
    return {
        "orchestration": {"id": orchestration_id, "version": "1", "mode": "graph"},
        "nodes": [{"id": "a"}, {"id": "b"}],
        "edges": [{"source": "a", "target": "b"}],
        "layout": {"a": {"x": 1, "y": 2}, "b": {"x": 3, "y": 4}},
    }


# --- draft / publish ---------------------------------------------------------

def test_draft_save_and_read_roundtrip(monkeypatch) -> None:
    database = _Database()
    monkeypatch.setattr(orchestrations, "get_db", lambda: database)

    async def scenario() -> None:
        await orchestrations.save_orchestration_draft(
            "demo",
            orchestrations.OrchestrationDocumentPayload(
                document=_valid_document(), layout={"a": {"x": 1, "y": 2}}
            ),
            principal=PRINCIPAL,
        )
        result = await orchestrations.get_orchestration("demo", principal=PRINCIPAL)
        data = result.data
        assert data["status"] == "draft"
        assert data["version"] == 1
        assert data["layout"]["a"] == {"x": 1, "y": 2}
        assert data["document"]["orchestration"]["id"] == "demo"

    asyncio.run(scenario())


def test_draft_version_bumps_on_resave(monkeypatch) -> None:
    database = _Database()
    monkeypatch.setattr(orchestrations, "get_db", lambda: database)

    async def scenario() -> None:
        for _ in range(2):
            await orchestrations.save_orchestration_draft(
                "demo",
                orchestrations.OrchestrationDocumentPayload(document=_valid_document()),
                principal=PRINCIPAL,
            )
        result = await orchestrations.get_orchestration("demo", principal=PRINCIPAL)
        assert result.data["version"] == 2

    asyncio.run(scenario())


def test_publish_requires_permission_code(monkeypatch) -> None:
    database = _Database()

    async def denied(_tenant: str, _user: str) -> bool:
        return False

    monkeypatch.setattr(orchestrations, "get_db", lambda: database)
    monkeypatch.setattr(orchestrations, "can_publish_orchestration", denied)

    async def scenario() -> None:
        with pytest.raises(HTTPException) as info:
            await orchestrations.publish_orchestration(
                "demo",
                orchestrations.PublishPayload(document=_valid_document()),
                principal=PRINCIPAL,
            )
        assert info.value.status_code == 403
        assert "orchestration:publish" in info.value.detail

    asyncio.run(scenario())


def test_publish_granted_bumps_version_and_sets_status(monkeypatch) -> None:
    database = _Database()

    async def allowed(_tenant: str, _user: str) -> bool:
        return True

    async def denied(_tenant: str, _user: str) -> bool:
        return False

    monkeypatch.setattr(orchestrations, "get_db", lambda: database)

    async def scenario() -> None:
        # draft first (version 1)
        monkeypatch.setattr(orchestrations, "can_publish_orchestration", denied)
        await orchestrations.save_orchestration_draft(
            "demo",
            orchestrations.OrchestrationDocumentPayload(document=_valid_document()),
            principal=PRINCIPAL,
        )
        # publish (version 2)
        monkeypatch.setattr(orchestrations, "can_publish_orchestration", allowed)
        result = await orchestrations.publish_orchestration(
            "demo",
            orchestrations.PublishPayload(document=_valid_document(), releaseNotes="v2"),
            principal=PRINCIPAL,
        )
        assert result.data["status"] == "published"
        assert result.data["version"] == 2

        read = await orchestrations.get_orchestration("demo", principal=PRINCIPAL)
        assert read.data["status"] == "published"
        assert len(read.data["history"]) == 1
        assert read.data["history"][0]["version"] == 1

    asyncio.run(scenario())


def test_cycle_is_rejected_with_engine_consistent_error(monkeypatch) -> None:
    database = _Database()
    monkeypatch.setattr(orchestrations, "get_db", lambda: database)
    cyclic = _valid_document()
    cyclic["edges"] = [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]

    async def scenario() -> None:
        with pytest.raises(HTTPException) as info:
            await orchestrations.save_orchestration_draft(
                "demo",
                orchestrations.OrchestrationDocumentPayload(document=cyclic),
                principal=PRINCIPAL,
            )
        assert info.value.status_code == 422
        assert "cycle detected" in info.value.detail

    asyncio.run(scenario())


def test_self_loop_is_rejected(monkeypatch) -> None:
    database = _Database()
    monkeypatch.setattr(orchestrations, "get_db", lambda: database)
    doc = _valid_document()
    doc["edges"] = [{"source": "a", "target": "a"}]

    async def scenario() -> None:
        with pytest.raises(HTTPException) as info:
            await orchestrations.save_orchestration_draft(
                "demo",
                orchestrations.OrchestrationDocumentPayload(document=doc),
                principal=PRINCIPAL,
            )
        assert info.value.status_code == 422

    asyncio.run(scenario())


def test_id_mismatch_rejected(monkeypatch) -> None:
    database = _Database()
    monkeypatch.setattr(orchestrations, "get_db", lambda: database)
    doc = _valid_document("other")

    async def scenario() -> None:
        with pytest.raises(HTTPException) as info:
            await orchestrations.save_orchestration_draft(
                "demo",
                orchestrations.OrchestrationDocumentPayload(document=doc),
                principal=PRINCIPAL,
            )
        assert info.value.status_code == 422

    asyncio.run(scenario())


def test_tenant_isolation_on_read(monkeypatch) -> None:
    database = _Database()

    async def scenario() -> None:
        await orchestrations.save_orchestration_draft(
            "demo",
            orchestrations.OrchestrationDocumentPayload(document=_valid_document()),
            principal=ApiPrincipal(kind="end_user", tenant_id="t1", user_id="u1"),
        )
        with pytest.raises(HTTPException) as info:
            await orchestrations.get_orchestration(
                "demo",
                principal=ApiPrincipal(kind="end_user", tenant_id="t2", user_id="u2"),
            )
        assert info.value.status_code == 404

    monkeypatch.setattr(orchestrations, "get_db", lambda: database)
    asyncio.run(scenario())


def test_corrupt_layout_is_dropped(monkeypatch) -> None:
    database = _Database()
    monkeypatch.setattr(orchestrations, "get_db", lambda: database)

    async def scenario() -> None:
        await orchestrations.save_orchestration_draft(
            "demo",
            orchestrations.OrchestrationDocumentPayload(
                document=_valid_document(),
                layout={"a": {"x": "bad", "y": 2}, "b": {"x": float("nan"), "y": 4}},
            ),
            principal=PRINCIPAL,
        )
        result = await orchestrations.get_orchestration("demo", principal=PRINCIPAL)
        assert result.data["layout"] == {}

    asyncio.run(scenario())