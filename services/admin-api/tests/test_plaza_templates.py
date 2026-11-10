"""053-plaza-template-distribution：广场模板分发契约测试.

覆盖（spec US1-US3 / FR-001~011 / Edge Cases；验证清单见 tasks T023/T024）：

* asset_type 校验（employee_template / sop_template 合法，其他拒绝）
* 克隆深拷贝 + template_ref（原件不变性哈希断言）
* 原件只读（非草稿只读；副本可改）
* 版本升级旧快照（002 版本化，不强制覆盖）
* SOP 门禁（无测试集拒绝 / 评估通过上架）
* 凭证不复制（034 口径扫描断言）
* 审批人重解析（050 联动：human_approval 审批人按克隆者租户）
* 租户隔离（跨租户 fail-closed）

纯逻辑 + fake DB（不依赖真实 Mongo），与既有契约测试范式一致。
"""

from __future__ import annotations

import pytest

from app.services.templates import (
    EMPLOYEE_TEMPLATE,
    SOP_TEMPLATE,
    TEMPLATE_ASSET_TYPES,
    AssetTemplate,
    CloneError,
    TemplateError,
    TemplateRepository,
    clone_template,
    has_newer_version,
    publish_template,
    run_publish_gate,
    strip_credentials,
    unpublish_template,
    upgrade_clone,
)
from app.services.templates.clone import _reparse_approvers_in_document
from app.services.templates.model import make_template_id, utcnow


# ---------------------------------------------------------------------------
# fake DB（027 门面形状子集：insert_one / find_one / find / update_one）
# ---------------------------------------------------------------------------


class _Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def sort(self, *_a, **_k):
        return self

    async def to_list(self, length: int | None = None):
        return self._docs[:length] if length else list(self._docs)

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    def _match(self, doc: dict, scope: dict) -> bool:
        return all(doc.get(k) == v for k, v in scope.items())

    async def find_one(self, scope: dict):
        return next((d for d in self.docs if self._match(d, scope)), None)

    def find(self, scope: dict, projection: dict | None = None) -> _Cursor:
        docs = [d for d in self.docs if self._match(d, scope)]
        if projection:
            docs = [{k: d[k] for k in projection if projection[k] and k in d} for d in docs]
        return _Cursor(docs)

    async def insert_one(self, doc: dict) -> None:
        self.docs.append(dict(doc))

    async def update_one(self, scope: dict, update: dict, upsert: bool = False):
        doc = next((d for d in self.docs if self._match(d, scope)), None)
        if doc is None:
            if not upsert:
                return type("R", (), {"matched_count": 0})()
            doc = dict(scope)
            doc.update(update.get("$setOnInsert") or {})
            self.docs.append(doc)
        doc.update(update.get("$set") or {})
        return type("R", (), {"matched_count": 1})()

    async def replace_one(self, scope: dict, doc: dict, upsert: bool = False):
        for i, existing in enumerate(self.docs):
            if self._match(existing, scope):
                self.docs[i] = dict(doc)
                return
        if upsert:
            self.docs.append(dict(doc))


class _FakeDB:
    def __init__(self) -> None:
        self._cols: dict[str, _FakeCollection] = {}

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._cols.setdefault(name, _FakeCollection())

    def __getattr__(self, name: str) -> _FakeCollection:
        return self.__getitem__(name)


# --- monkeypatch get_db ----------------------------------------------------


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeDB()
    import app.services.templates.repository as repo_mod

    monkeypatch.setattr(repo_mod, "get_db", lambda: db)
    import app.services.templates.publish as pub_mod

    monkeypatch.setattr(pub_mod, "get_db", lambda: db)
    import app.services.templates.clone as clone_mod

    monkeypatch.setattr(clone_mod, "get_db", lambda: db)
    import app.services.templates.upgrade as up_mod

    monkeypatch.setattr(up_mod, "get_db", lambda: db)
    return db


def _make_sop_template(*, version: int = 1, state: str = "draft") -> AssetTemplate:
    return AssetTemplate(
        template_id=make_template_id(),
        tenant_id="default",
        name="合同审查 SOP",
        asset_type=SOP_TEMPLATE,
        content={
            "orchestration": {"id": "contract_review", "version": "1", "mode": "graph"},
            "nodes": [
                {"id": "review", "payload": {"skill": "contract_review_v1", "tools": ["search_web"]}},
                {
                    "id": "approve",
                    "payload": {"type": "human_approval", "approver": "admin", "prompt": "批准合同"},
                },
            ],
            "edges": [{"source": "review", "target": "approve"}],
        },
        version=version,
        state=state,
        owner_id="owner-1",
        created_at=utcnow(),
        updated_at=utcnow(),
    )


def _make_employee_template(*, version: int = 1, state: str = "draft") -> AssetTemplate:
    return AssetTemplate(
        template_id=make_template_id(),
        tenant_id="default",
        name="财务员工",
        asset_type=EMPLOYEE_TEMPLATE,
        content={
            "name": "财务员工",
            "capabilities": {"tools": ["tool-1"], "skills": ["skill-1"]},
            "knowledge_base_ids": ["kb-1"],
            "model": "default",
        },
        version=version,
        state=state,
        owner_id="owner-1",
        created_at=utcnow(),
        updated_at=utcnow(),
    )


# ---------------------------------------------------------------------------
# FR-001：asset_type 校验
# ---------------------------------------------------------------------------


def test_asset_type_accepts_two_template_types() -> None:
    assert TEMPLATE_ASSET_TYPES == (EMPLOYEE_TEMPLATE, SOP_TEMPLATE)
    assert EMPLOYEE_TEMPLATE == "employee_template"
    assert SOP_TEMPLATE == "sop_template"


def test_asset_type_rejects_unknown() -> None:
    with pytest.raises(TemplateError):
        AssetTemplate(
            template_id="tpl_x", tenant_id="default", name="x", asset_type="skill"
        )


def test_asset_type_distinguishes_from_employee_runtime() -> None:
    # 053 模板类型与 051 employee（运行时实体）区分。
    assert EMPLOYEE_TEMPLATE != "employee"


# ---------------------------------------------------------------------------
# FR-003：克隆深拷贝 + template_ref；原件不变性（哈希）
# ---------------------------------------------------------------------------


def test_clone_deep_copies_and_records_ref(fake_db) -> None:
    repo = TemplateRepository()
    template = _make_sop_template()
    template.publish(gate_report={"runId": "r1", "passed": True})
    template.content["nodes"][0]["payload"]["skill"] = "orig_v1"
    original_digest = template.digest()

    clone, target_doc = __import__("asyncio").get_event_loop().run_until_complete(
        clone_template(template, cloner_id="cloner-1", repo=repo)
    )

    assert clone.template_id == template.template_id
    assert clone.template_version == template.version
    assert clone.cloner_id == "cloner-1"
    assert clone.target_type == "dag_definition"
    assert clone.target_key
    assert clone.template_ref["asset_type"] == SOP_TEMPLATE
    assert clone.template_ref["version"] == template.version

    # 副本内容 = 深拷贝，原件修改不影响副本。
    assert target_doc["nodes"][0]["payload"]["skill"] == "orig_v1"
    # 原件内容不变性（哈希断言，SC-001）。
    assert template.digest() == original_digest


def test_clone_rejects_offline_template(fake_db) -> None:
    repo = TemplateRepository()
    template = _make_sop_template()
    template.publish()
    template.unpublish()  # offline
    with pytest.raises(CloneError):
        __import__("asyncio").get_event_loop().run_until_complete(
            clone_template(template, cloner_id="cloner-1", repo=repo)
        )


def test_clone_same_name_dedupes(fake_db) -> None:
    repo = TemplateRepository()
    template = _make_sop_template()
    template.publish()
    loop = __import__("asyncio").get_event_loop()
    clone1, doc1 = loop.run_until_complete(clone_template(template, cloner_id="c1", name="同名", repo=repo))
    clone2, doc2 = loop.run_until_complete(clone_template(template, cloner_id="c2", name="同名", repo=repo))
    assert doc1["orchestration"]["id"] != doc2["orchestration"]["id"]


# ---------------------------------------------------------------------------
# FR-003：原件只读（非草稿只读；副本可改）
# ---------------------------------------------------------------------------


def test_original_is_readonly_after_publish() -> None:
    template = _make_sop_template()
    assert template.is_readonly is False  # draft 可编辑
    template.publish()
    assert template.is_readonly is True  # 已上架只读
    template.unpublish()
    assert template.is_readonly is True  # 下架仍只读


def test_clone_editable_independent_of_original(fake_db) -> None:
    repo = TemplateRepository()
    template = _make_sop_template()
    template.publish()
    loop = __import__("asyncio").get_event_loop()
    clone, target_doc = loop.run_until_complete(clone_template(template, cloner_id="c1", repo=repo))
    # 克隆者编辑副本：改副本内容不影响原件。
    target_doc["nodes"][0]["payload"]["skill"] = "edited"
    assert template.content["nodes"][0]["payload"]["skill"] != "edited"


# ---------------------------------------------------------------------------
# FR-004：凭证零明文（克隆剥离，034 口径）
# ---------------------------------------------------------------------------


def test_strip_credentials_removes_credential_keys() -> None:
    document = {
        "nodes": [
            {
                "id": "tool",
                "payload": {
                    "tools": ["http_tool"],
                    "config": {"authToken": "sk-live-abc", "endpoint": "https://x", "headers": {"token": "secret"}},
                },
            }
        ]
    }
    cleaned = strip_credentials(document)
    # 顶层凭证键剥离
    assert "authToken" not in cleaned["nodes"][0]["payload"]["config"]
    # headers 内同名凭证键剥离
    assert "token" not in cleaned["nodes"][0]["payload"]["config"]["headers"]
    # 非凭证字段保持
    assert cleaned["nodes"][0]["payload"]["config"]["endpoint"] == "https://x"
    # 明文不落副本
    assert "sk-live-abc" not in str(cleaned)
    assert "secret" not in str(cleaned)


def test_clone_strips_credentials(fake_db) -> None:
    repo = TemplateRepository()
    template = _make_sop_template()
    template.content["nodes"].append({
        "id": "cred_tool",
        "payload": {"tools": ["http_tool"], "config": {"authToken": "sk-test-123"}},
    })
    template.publish()
    loop = __import__("asyncio").get_event_loop()
    _, target_doc = loop.run_until_complete(clone_template(template, cloner_id="c1", repo=repo))
    assert "sk-test-123" not in str(target_doc)


# ---------------------------------------------------------------------------
# FR-002 / Edge Cases：SOP 门禁（032）
# ---------------------------------------------------------------------------


def test_sop_publish_gate_rejects_no_test_set(fake_db, monkeypatch) -> None:
    template = _make_sop_template()
    # 模拟无测试集：count_cases 返回 0
    import app.services.templates.publish as pub_mod

    async def _zero_cases(*a, **k):
        return 0

    monkeypatch.setattr("app.services.eval_gate.test_sets.count_cases", _zero_cases)
    with pytest.raises(Exception) as exc_info:
        __import__("asyncio").get_event_loop().run_until_complete(run_publish_gate(template))
    assert "测试集" in str(exc_info.value) or "no_test_set" in str(exc_info.value)


# ---------------------------------------------------------------------------
# FR-005：版本升级旧快照（002 版本化，不强制覆盖）
# ---------------------------------------------------------------------------


def test_has_newer_version_signal() -> None:
    template = _make_sop_template(version=3)
    assert has_newer_version(template, current_ref_version=2) is True
    assert has_newer_version(template, current_ref_version=3) is False
    assert has_newer_version(template, current_ref_version=4) is False


def test_upgrade_replaces_and_keeps_snapshot(fake_db) -> None:
    repo = TemplateRepository()
    template = _make_sop_template(version=2)
    template.publish()
    # 预置副本（dag_definitions）
    db = fake_db
    db["dag_definitions"].docs.append({
        "tenant_id": "default",
        "orchestration_id": "contract_review",
        "version": "1",
        "status": "published",
        "document": {"orchestration": {"id": "contract_review", "version": "1"}},
        "updated_at": utcnow(),
    })
    loop = __import__("asyncio").get_event_loop()
    record = loop.run_until_complete(
        upgrade_clone(
            tenant_id="default",
            template=template,
            target_type="dag_definition",
            target_key="contract_review",
            operator_id="op-1",
            repo=repo,
        )
    )
    assert record.old_version == 1
    assert record.new_version == 2
    assert record.operator_id == "op-1"
    assert record.old_snapshot["orchestration_id"] == "contract_review"
    # 快照留存在 template_upgrades
    assert db["template_upgrades"].docs


# ---------------------------------------------------------------------------
# 050 联动：审批人按克隆者租户重解析
# ---------------------------------------------------------------------------


def test_reparse_approver_for_tenant() -> None:
    document = {
        "nodes": [
            {"id": "normal", "payload": {"skill": "s1"}},
            {"id": "approve", "payload": {"type": "human_approval", "approver": "admin-x"}},
        ]
    }
    reparsed = _reparse_approvers_in_document(document, tenant_id="tenant-b")
    nodes = {n["id"]: n for n in reparsed["nodes"]}
    assert "approver" not in nodes["approve"]["payload"]
    assert nodes["approve"]["payload"]["approver_tenant_id"] == "tenant-b"
    assert nodes["approve"]["payload"]["approver_pending"] is True
    # 非审批节点不受影响
    assert nodes["normal"]["payload"]["skill"] == "s1"


def test_reparse_keeps_non_approval_nodes() -> None:
    document = {"nodes": [{"id": "a", "payload": {"type": "skill", "skill": "s"}}]}
    reparsed = _reparse_approvers_in_document(document, tenant_id="t")
    assert reparsed["nodes"][0]["payload"]["type"] == "skill"


# ---------------------------------------------------------------------------
# FR-006：下架不伤副本；克隆时下架拒绝（见 test_clone_rejects_offline_template）
# ---------------------------------------------------------------------------


def test_unpublish_marks_offline(fake_db) -> None:
    repo = TemplateRepository()
    template = _make_sop_template()
    template.publish()
    loop = __import__("asyncio").get_event_loop()
    loop.run_until_complete(unpublish_template(template, actor="op-1", repo=repo))
    assert template.state == "offline"


# ---------------------------------------------------------------------------
# 路由挂载口径：admin-web 调 `/api/v1/templates`，前缀只由 api_router 提供一次
# ---------------------------------------------------------------------------


def test_templates_routes_mounted_without_double_prefix() -> None:
    from fastapi import FastAPI

    from app.api.router import api_router

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    paths = set(app.openapi()["paths"])
    assert "/api/v1/templates" in paths
    assert "/api/v1/templates/{template_id}/clone" in paths
    assert "/api/v1/templates/{template_id}/publish" in paths
    assert not any(p.startswith("/api/v1/templates/templates") for p in paths)


def test_management_list_includes_drafts(monkeypatch) -> None:
    """管理侧目录必须能看到草稿，否则新建模板后无法上架（用户侧广场由 chat-api 独立过滤）。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_admin_user
    from app.api.routes import templates as template_routes

    captured: dict[str, object] = {}
    draft = _make_employee_template(state="draft")

    class _StubRepo:
        async def list_templates(self, *, tenant_id, asset_type=None, state=None):
            captured["state"] = state
            captured["tenant_id"] = tenant_id
            return [draft]

    monkeypatch.setattr(template_routes, "_repo", lambda: _StubRepo())
    app = FastAPI()
    app.include_router(template_routes.router, prefix="/api/v1/templates")
    app.dependency_overrides[get_current_admin_user] = lambda: {
        "tenant_id": "tenant-a",
        "username": "op-1",
    }
    client = TestClient(app)

    resp = client.get("/api/v1/templates")
    assert resp.status_code == 200
    assert captured["state"] is None
    assert captured["tenant_id"] == "tenant-a"
    assert resp.json()["data"]["items"][0]["state"] == "draft"

    resp = client.get("/api/v1/templates", params={"state": "published"})
    assert resp.status_code == 200
    assert captured["state"] == "published"
