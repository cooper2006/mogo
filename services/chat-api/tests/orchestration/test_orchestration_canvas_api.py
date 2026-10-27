"""Tests for the visual-orchestration canvas API (feature 039).

Covers the two seams introduced by 039:
* ``store._document_shape`` now passes ``layout`` through (投影元数据不静默丢失)；
* the canvas endpoints ``/api/orchestrations`` — draft save / publish gate / validation /
  tenant isolation — all validated against the SAME loader the 010 engine uses.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.endpoints import orchestrations
from app.api.principal import ApiPrincipal
from app.orchestration import store
from app.orchestration.engine import DagEngine
from app.orchestration.loader import load_orchestration_document


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


# --- T030：画布 → 保存 → 010 引擎真实执行 → 发布 → 版本回看（进程内 E2E） -----
#
# 这条覆盖 T030 的实质链路（缺的只有"真 Mongo"，集合行为由 _Database 等价模拟）：
# 前端 canvasToEngineDocument 产出的文档原样提交 → 落库 → 用同一个 loader 装载 →
# DagEngine 真实跑一遍 → 发布 → 旧版进 history。

def _canvas_document(orchestration_id: str = "canvas-e2e") -> dict:
    """模拟 `canvasToEngineDocument` 的产出（payload + x_canvas + depends_on + edges）。"""

    return {
        "orchestration": {"id": orchestration_id, "version": "1", "mode": "graph"},
        "nodes": [
            {
                "id": "research",
                "type": "llm",
                "payload": {
                    "skill": "researcher",
                    "output_key": "research_result",
                    "x_canvas": {"kind": "llm", "label": "研究"},
                },
            },
            {
                "id": "write",
                "type": "llm",
                "depends_on": ["research"],
                "payload": {
                    "skill": "writer",
                    "output_key": "draft",
                    "x_canvas": {"kind": "llm", "label": "写作"},
                },
            },
        ],
        "edges": [{"source": "research", "target": "write"}],
        "layout": {"research": {"x": 40, "y": 60}, "write": {"x": 280, "y": 60}},
    }


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "canvas_document.json"


def test_real_serializer_fixture_loads_and_runs() -> None:
    """前端 TS 序列化器的**真实产出**必须能被 010 loader 装载并执行。

    `fixtures/canvas_document.json` 由 `apps/user-web` 的 `canvasToEngineDocument`
    生成（不是手写近似），前端单测会断言该文件与当前序列化结果一致，两边一起漂移即报错。
    """

    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    loaded = load_orchestration_document(fixture)

    order: list[str] = []

    async def runner(node, context):
        order.append(node.id)
        if node.id == "write":
            return f"drafted from {context.get('research')}"
        return "findings"

    result = asyncio.run(DagEngine().run_graph(loaded.definition.to_graph(), runner))
    assert result.succeeded
    assert order == ["research", "write"]
    assert result.context["write"] == "drafted from findings"
    # 引擎只取 _PAYLOAD_KEYS（skill/tools/...），画布投影键 x_canvas 被丢弃——
    # 这是对的：投影只服务画布渲染，画布读的是**落库的文档**而不是 loader 的产物。
    assert loaded.definition.nodes[0]["payload"]["skill"] == "researcher"
    assert "x_canvas" not in loaded.definition.nodes[0]["payload"]
    assert fixture["nodes"][0]["payload"]["x_canvas"]["label"] == "研究"


def test_canvas_document_runs_on_the_real_engine(monkeypatch) -> None:
    database = _Database()
    monkeypatch.setattr(orchestrations, "get_db", lambda: database)

    async def scenario() -> None:
        await orchestrations.save_orchestration_draft(
            "canvas-e2e",
            orchestrations.OrchestrationDocumentPayload(
                document=_canvas_document(), layout={"research": {"x": 40, "y": 60}}
            ),
            principal=PRINCIPAL,
        )

        # 落库的必须是引擎文档：节点带 skill / depends_on，画布投影信息在 payload.x_canvas。
        stored = database.dag_definitions.documents[0]["document"]
        assert stored["nodes"][0]["payload"]["skill"] == "researcher"
        assert stored["nodes"][1]["depends_on"] == ["research"]

        loaded = load_orchestration_document(stored)
        order: list[str] = []

        async def runner(node, context):
            order.append(node.id)
            if node.id == "write":
                return f"drafted from {context.get('research')}"
            return "findings"

        result = await DagEngine().run_graph(loaded.definition.to_graph(), runner)

        assert result.succeeded
        assert order == ["research", "write"], "依赖顺序必须由 depends_on 决定"
        assert result.context["write"] == "drafted from findings", "下游必须读到上游产出"

    asyncio.run(scenario())


def test_canvas_publish_bumps_version_and_keeps_history(monkeypatch) -> None:
    database = _Database()
    monkeypatch.setattr(orchestrations, "get_db", lambda: database)

    async def allowed(_tenant: str, _user: str) -> bool:
        return True

    monkeypatch.setattr(orchestrations, "can_publish_orchestration", allowed)

    async def scenario() -> None:
        await orchestrations.save_orchestration_draft(
            "canvas-e2e",
            orchestrations.OrchestrationDocumentPayload(document=_canvas_document()),
            principal=PRINCIPAL,
        )
        stored = database.dag_definitions.documents[0]["document"]

        published = await orchestrations.publish_orchestration(
            "canvas-e2e",
            orchestrations.PublishPayload(
                document=stored, layout=stored.get("layout"), release_notes="first release"
            ),
            principal=PRINCIPAL,
        )
        assert published.data["version"] == 2
        assert published.data["status"] == "published"

        detail = await orchestrations.get_orchestration("canvas-e2e", principal=PRINCIPAL)
        assert detail.data["status"] == "published"
        assert detail.data["version"] == 2
        assert detail.data["history"][0]["version"] == 1, "上一版必须可回看"
        assert detail.data["history"][0]["document"]["nodes"][0]["id"] == "research"

        # 发布后仍是同一份引擎文档：再装载一次不应报错（fail-closed 校验不因发布而放宽）。
        load_orchestration_document(detail.data["document"])

    asyncio.run(scenario())