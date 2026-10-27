"""T030 真实 Mongo 端到端：画布文档 → 落库 → 运行时装载 → 引擎执行 → 发布 → 版本回看。

与同目录 `test_orchestration_canvas_api.py` 的进程内用例互补：那边用 `_Database`
假集合验证端点逻辑，这边直接连真 Mongo，验证 motor 真实写入/读取（`update_one` upsert、
`find_one` 过滤、`history` 嵌套文档）以及运行时入口 `store.load_orchestration_persisted`
的"集合优先于 YAML"语义。

Mongo 不可达时整文件 skip，不影响无 Mongo 的 CI：

    MOGO_E2E_MONGO_URI=mongodb://127.0.0.1:27017 \\
      PYTHONPATH=services/chat-api pytest tests/orchestration/test_orchestration_canvas_mongo_e2e.py
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from app.api.endpoints import orchestrations
from app.api.principal import ApiPrincipal
from app.orchestration import store
from app.orchestration.engine import DagEngine
from app.orchestration.loader import load_orchestration_document

MONGO_URI = os.getenv("MOGO_E2E_MONGO_URI", "mongodb://127.0.0.1:27017")
COLLECTION = "dag_definitions"
PRINCIPAL = ApiPrincipal(kind="end_user", tenant_id="t-e2e", user_id="u-e2e")


def _mongo_available() -> bool:
    try:
        import pymongo
    except Exception:  # pragma: no cover - driver 缺失等同不可用
        return False
    try:
        pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=800).admin.command("ping")
        return True
    except Exception:  # pragma: no cover - 无 Mongo 的环境
        return False


pytestmark = pytest.mark.skipif(
    not _mongo_available(),
    reason=f"Mongo 不可达（{MONGO_URI}）；设置 MOGO_E2E_MONGO_URI 后重跑",
)


def _canvas_document(orchestration_id: str = "canvas-e2e") -> dict:
    """与前端 `canvasToEngineDocument` 产出同构（payload + x_canvas + depends_on + edges）。"""

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


class _TempDatabase:
    """每次测试一个独立库，用完 drop，避免污染本机 Mongo。"""

    def __init__(self) -> None:
        self.name = f"mogo_e2e_{uuid.uuid4().hex[:10]}"

    async def __aenter__(self):
        from motor.motor_asyncio import AsyncIOMotorClient

        self.client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        self.db = self.client[self.name]
        return self.db

    async def __aexit__(self, *_exc) -> None:
        await self.client.drop_database(self.name)
        self.client.close()


def test_canvas_document_survives_real_mongo_and_runs(monkeypatch) -> None:
    async def scenario() -> None:
        async with _TempDatabase() as db:
            monkeypatch.setattr(orchestrations, "get_db", lambda: db)

            await orchestrations.save_orchestration_draft(
                "canvas-e2e",
                orchestrations.OrchestrationDocumentPayload(
                    document=_canvas_document(), layout={"research": {"x": 40, "y": 60}}
                ),
                principal=PRINCIPAL,
            )

            # 直读真 Mongo：确认写入的是引擎文档而不是画布投影。
            raw = await db[COLLECTION].find_one({"orchestration_id": "canvas-e2e"})
            assert raw is not None
            assert raw["version"] == 1
            assert raw["status"] == "draft"
            assert raw["tenant_id"] == "t-e2e"
            assert raw["document"]["nodes"][1]["depends_on"] == ["research"]
            assert raw["document"]["nodes"][0]["payload"]["skill"] == "researcher"
            assert raw["layout"]["research"] == {"x": 40.0, "y": 60.0}

            # 运行时入口：集合优先于 YAML（yaml_path 故意给不存在的路径）。
            monkeypatch.setattr("app.core.db.get_db", lambda: db, raising=False)
            loaded = await store.load_orchestration_persisted(
                "canvas-e2e", yaml_path="/nonexistent/never_read.yaml"
            )

            order: list[str] = []

            async def runner(node, context):
                order.append(node.id)
                if node.id == "write":
                    return f"drafted from {context.get('research')}"
                return "findings"

            result = await DagEngine().run_graph(loaded.definition.to_graph(), runner)
            assert result.succeeded
            assert order == ["research", "write"]
            assert result.context["write"] == "drafted from findings"

    asyncio.run(scenario())


def test_publish_persists_history_in_real_mongo(monkeypatch) -> None:
    async def allowed(_tenant: str, _user: str) -> bool:
        return True

    async def scenario() -> None:
        async with _TempDatabase() as db:
            monkeypatch.setattr(orchestrations, "get_db", lambda: db)
            monkeypatch.setattr(orchestrations, "can_publish_orchestration", allowed)

            await orchestrations.save_orchestration_draft(
                "canvas-e2e",
                orchestrations.OrchestrationDocumentPayload(document=_canvas_document()),
                principal=PRINCIPAL,
            )
            stored = await db[COLLECTION].find_one({"orchestration_id": "canvas-e2e"})

            published = await orchestrations.publish_orchestration(
                "canvas-e2e",
                orchestrations.PublishPayload(
                    document=stored["document"], layout=stored["layout"], release_notes="first release"
                ),
                principal=PRINCIPAL,
            )
            assert published.data["version"] == 2
            assert published.data["status"] == "published"

            # 真 Mongo 里的终态：版本 2、history 保留版本 1 的完整文档。
            row = await db[COLLECTION].find_one({"orchestration_id": "canvas-e2e"})
            assert row["version"] == 2
            assert row["status"] == "published"
            assert len(row["history"]) == 1
            assert row["history"][0]["version"] == 1
            assert row["history"][0]["document"]["nodes"][0]["id"] == "research"

            # 发布后的文档仍然可被同一 loader 装载（校验不因发布放宽）。
            load_orchestration_document(row["document"])

    asyncio.run(scenario())


def test_real_mongo_enforces_tenant_isolation(monkeypatch) -> None:
    async def scenario() -> None:
        async with _TempDatabase() as db:
            monkeypatch.setattr(orchestrations, "get_db", lambda: db)

            await orchestrations.save_orchestration_draft(
                "canvas-e2e",
                orchestrations.OrchestrationDocumentPayload(document=_canvas_document()),
                principal=PRINCIPAL,
            )

            other = ApiPrincipal(kind="end_user", tenant_id="t-other", user_id="u-other")
            with pytest.raises(Exception) as info:
                await orchestrations.get_orchestration("canvas-e2e", principal=other)
            assert getattr(info.value, "status_code", None) == 404

            # 另一个租户写入同名编排不会覆盖别人的文档（scope 里带 tenant_id）。
            await orchestrations.save_orchestration_draft(
                "canvas-e2e",
                orchestrations.OrchestrationDocumentPayload(document=_canvas_document()),
                principal=other,
            )
            rows = await db[COLLECTION].find({"orchestration_id": "canvas-e2e"}).to_list(length=10)
            assert {row["tenant_id"] for row in rows} == {"t-e2e", "t-other"}

    asyncio.run(scenario())
